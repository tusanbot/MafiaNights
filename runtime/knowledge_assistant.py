"""Context-aware Mafia knowledge assistant.

Internal verified/published knowledge is authoritative. Web search is only a
fallback and is explicitly marked as external context.
"""
from __future__ import annotations

import html
import json
import logging
import os
import asyncio
import urllib.parse
import urllib.request
from typing import Any

from repositories.knowledge_repository import KnowledgeRepository


def _game_context(app: Any, message: Any) -> tuple[str | None, str | None]:
    if getattr(message.chat, "type", None) not in {"group", "supergroup", "private"}:
        return None, None
    try:
        gid = int(message.chat.id)
        game = app.runtime.state.active_game(gid)
        if not game:
            return None, None
        scenario_name = str(game.get("scenario_name") or game.get("scenario") or "") or None
        role_name = None
        if getattr(message.chat, "type", None) == "private":
            rows = app.runtime.state.games.list_players(game["id"])
            uid = int(message.from_user.id)
            row = next((r for r in rows if int(r.get("player_id") or 0) == uid), None)
            if row:
                role_name = str(row.get("role") or row.get("role_name") or "") or None
        return scenario_name, role_name
    except Exception:
        logging.exception("knowledge assistant: context resolution failed")
        return None, None


def _looks_like_question(text: str) -> bool:
    """Recognize natural-language questions without hijacking ordinary game commands."""
    value = (text or "").strip()
    if not value or value.startswith("/"):
        return False
    lowered = value.casefold()
    if any(lowered.startswith(prefix) for prefix in ("سوال", "سؤال", "دستیار", "هوش مصنوعی", "ai ")):
        return True
    if "؟" in value or "?" in value:
        return True
    # Natural questions in Persian do not always start with the interrogative
    # word (e.g. «نقش بازپرس چیست؟»). Detect interrogative terms anywhere in
    # the sentence so the production auto-route can actually reach the AI.
    question_terms = (
        "چی", "چه", "چطور", "چگونه", "چرا", "آیا", "کی", "کجا",
        "میشه", "می‌شه", "میتونه", "می‌تونه", "چند", "کدام", "کدوم",
        "چیه", "چیست", "هست", "است", "داره", "دارم", "دارد",
        "توضیح", "توضیح بده", "توضیح دهید", "درباره", "تعریف", "معنی",
        "بگو", "بگید", "بده", "بدید",
    )
    words = lowered.replace("،", " ").replace(",", " ").replace(".", " ").split()
    if any(
        word in question_terms or any(word.startswith(term) for term in question_terms if len(term) >= 3)
        for word in words
    ):
        return True
    return False

def _web_search(query: str, limit: int = 4) -> list[dict[str, str]]:
    """Optional no-key fallback using DuckDuckGo HTML search.

    This is deliberately a fallback only; internal knowledge is checked first.
    """
    if str(os.getenv("MAFIA_WEB_SEARCH_ENABLED", "true")).lower() not in {"1", "true", "yes", "on"}:
        return []
    url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
    req = urllib.request.Request(url, headers={"User-Agent": "MafiaNights/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            body = response.read().decode("utf-8", errors="ignore")
    except Exception:
        logging.exception("knowledge assistant: web search failed")
        return []
    import re
    results = []
    for match in re.finditer(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', body, re.I | re.S):
        href, title = match.groups()
        title = re.sub(r"<[^>]+>", "", title)
        title = html.unescape(title).strip()
        href = html.unescape(href)
        if title and href:
            results.append({"title": title, "url": href})
        if len(results) >= limit:
            break
    return results


def _ai_config(app: Any, message: Any, resolved_gid: int | None = None) -> tuple[bool, str | None, str, str | None]:
    """Load the AI credential owned by the current group."""
    try:
        is_private = getattr(message.chat, "type", None) == "private"
        gid = resolved_gid if is_private else int(message.chat.id)
        if gid is None:
            return False, None, "gemini", None
        with KnowledgeRepository().SessionLocal() as session:
            from sqlalchemy import text
            row = session.execute(
                text("""select enabled, private_enabled,
                               provider, model, private_provider, private_model,
                               case when api_key_ciphertext is null then null
                                    else pgp_sym_decrypt(api_key_ciphertext, :secret)
                               end as api_key
                        from public.mafia_ai_settings where group_id=:gid limit 1"""),
                {"gid": gid, "secret": os.getenv("MAFIA_AI_ENCRYPTION_SECRET") or os.getenv("DATABASE_URL") or ""},
            ).mappings().first()
        if not row or (is_private and not row["private_enabled"]):
            return False, None, "gemini", None
        key = str(row["api_key"]) if row["api_key"] else None
        if not key:
            return False, None, "gemini", None

        # Provider is explicit configuration. For private requests use the
        # private provider/model fields because the PV shares the group's key
        # but may have its own provider metadata.
        provider = str(
            (row["private_provider"] if is_private else row["provider"]) or ""
        ).lower()
        model = (
            row["private_model"] if is_private else row["model"]
        )
        model = str(model) if model else None

        # Backward compatibility for rows written by the legacy /ai_key route:
        # that route used provider=openai while leaving private_provider=gemini.
        # The current product uses Gemini, so treat that exact stale combination
        # as Gemini rather than sending the Gemini credential to OpenAI.
        if (
            provider == "openai"
            and str(row["private_provider"] or "").lower() == "gemini"
            and str(row["model"] or "").lower().startswith(("gpt-", "o1", "o3", "o4"))
        ):
            provider = "gemini"
            model = "gemini-2.5-flash"

        if provider not in {"gemini", "openai"}:
            provider = "gemini"
        if provider == "gemini" and (not model or model.startswith(("gpt-", "o1", "o3", "o4"))):
            model = "gemini-2.5-flash"
        enabled = bool(row["private_enabled"]) if is_private else bool(row["enabled"])
        return enabled, key, provider, model
    except Exception:
        logging.exception("knowledge assistant: AI config lookup failed")
        return False, None, "gemini", None
def _call_ai(
    prompt: str,
    context: list[dict[str, Any]],
    web: list[dict[str, str]],
    api_key: str | None = None,
    provider: str = "openai",
    model: str | None = None,
) -> str | None:
    api_key = api_key or os.getenv("MAFIA_AI_API_KEY")
    if not api_key:
        return None

    provider = (provider or "openai").lower()
    if provider == "gemini":
        model = model or os.getenv("MAFIA_AI_MODEL") or "gemini-2.5-flash"
        system = (
            "تو دستیار رسمی Mafia Nights هستی. "
            "پاسخ را فارسی، دقیق و کوتاه بده. "
            "قوانین داخلی تاییدشده ربات بر هر منبع وب اولویت دارند. "
            "اطلاعات مخفی نقش، نقش سایر بازیکنان، هدف شبانه، رای یا استراتژی خصوصی بازیکنان را افشا نکن. "
            "اگر منبع داخلی کافی نیست، صریحاً بگو که پاسخ بر پایه منبع بیرونی است. "
            "برای سوال نامرتبط هم پاسخ مفید و عمومی بده."
        )
        payload = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{
                "role": "user",
                "parts": [{
                    "text": json.dumps(
                        {"question": prompt, "knowledge": context, "web_sources": web},
                        ensure_ascii=False,
                    )
                }]
            }],
            "generationConfig": {"temperature": 0.2},
        }
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            + urllib.parse.quote(model, safe="")
            + ":generateContent"
        )
        req = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=25) as response:
                obj = json.loads(response.read().decode("utf-8"))
            parts = obj.get("candidates", [{}])[0].get("content", {}).get("parts", [])
            text_parts = [str(p.get("text", "")) for p in parts if p.get("text")]
            return "".join(text_parts).strip() or None
        except urllib.error.HTTPError as exc:
            # Gemini availability can vary by API key/project. A newly issued
            # key may return 404 for an older model such as 2.5 Flash even though
            # the model exists globally. Discover models allowed for this key and
            # retry once with a currently available text-generation model.
            if exc.code == 404:
                try:
                    list_req = urllib.request.Request(
                        "https://generativelanguage.googleapis.com/v1beta/models",
                        headers={"x-goog-api-key": api_key},
                        method="GET",
                    )
                    with urllib.request.urlopen(list_req, timeout=10) as list_response:
                        models_obj = json.loads(list_response.read().decode("utf-8"))
                    available = []
                    for item in models_obj.get("models", []):
                        name = str(item.get("name") or "")
                        methods = item.get("supportedGenerationMethods") or []
                        if "generateContent" in methods and name.startswith("models/"):
                            available.append(name.split("/", 1)[1])
                    preferred = [
                        "gemini-3.8-flash",
                        "gemini-3.7-flash",
                        "gemini-3.6-flash",
                        "gemini-3.5-flash",
                        "gemini-3.5-flash-lite",
                        "gemini-3.1-flash-lite",
                        "gemini-2.5-flash",
                        "gemini-2.5-flash-lite",
                        "gemini-2.0-flash",
                    ]
                    candidates = [m for m in preferred if m in available]
                    candidates += [m for m in available if m not in candidates and "flash" in m.lower()]
                    for fallback_model in candidates:
                        if fallback_model == model:
                            continue
                        try:
                            logging.warning(
                                "knowledge assistant: Gemini model %s unavailable; trying %s",
                                model, fallback_model,
                            )
                            retry_url = (
                                "https://generativelanguage.googleapis.com/v1beta/models/"
                                + urllib.parse.quote(fallback_model, safe="")
                                + ":generateContent"
                            )
                            retry_req = urllib.request.Request(
                                retry_url,
                                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                                headers={
                                    "Content-Type": "application/json",
                                    "x-goog-api-key": api_key,
                                },
                                method="POST",
                            )
                            with urllib.request.urlopen(retry_req, timeout=20) as retry_response:
                                retry_obj = json.loads(retry_response.read().decode("utf-8"))
                            retry_parts = retry_obj.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                            retry_text = [str(p.get("text", "")) for p in retry_parts if p.get("text")]
                            generated = "".join(retry_text).strip()
                            if generated:
                                logging.info("knowledge assistant: Gemini fallback succeeded with %s", fallback_model)
                                return generated
                        except urllib.error.HTTPError as retry_exc:
                            logging.warning("knowledge assistant: Gemini fallback %s returned HTTP %s", fallback_model, retry_exc.code)
                        except Exception:
                            logging.exception("knowledge assistant: Gemini fallback %s failed")
                except Exception:
                    logging.exception("knowledge assistant: Gemini model discovery/retry failed")
            logging.error("knowledge assistant: Gemini HTTP %s", exc.code)
            return None
        except Exception:
            logging.exception("knowledge assistant: Gemini request failed")
            return None

    model = model or os.getenv("MAFIA_AI_MODEL", "gpt-5.6-mini")
    base = os.getenv("MAFIA_AI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    system = (
        "تو دستیار رسمی Mafia Nights هستی. "
        "پاسخ را فارسی، دقیق و کوتاه بده. "
        "قوانین داخلی تاییدشده ربات بر هر منبع وب اولویت دارند. "
        "اطلاعات مخفی نقش، نقش سایر بازیکنان، هدف شبانه، رای یا استراتژی خصوصی بازیکنان را افشا نکن. "
        "اگر منبع داخلی کافی نیست، صریحاً بگو که پاسخ بر پایه منبع بیرونی است. "
        "برای سوال نامرتبط هم پاسخ مفید و عمومی بده، ولی خودت را مرجع قطعی اطلاعات بیرونی معرفی نکن."
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": json.dumps(
                    {"question": prompt, "knowledge": context, "web_sources": web},
                    ensure_ascii=False,
                ),
            },
        ],
        "temperature": 0.2,
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        base + "/chat/completions",
        data=data,
        headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as response:
            obj = json.loads(response.read().decode("utf-8"))
        return str(obj["choices"][0]["message"]["content"]).strip()
    except Exception:
        logging.exception("knowledge assistant: AI request failed")
        return None


def _ensure_ai_settings_table() -> None:
    """Ensure the legacy production database has the AI settings table."""
    with KnowledgeRepository().SessionLocal() as session:
        from sqlalchemy import text
        session.execute(text("create extension if not exists pgcrypto"))
        session.execute(text("""
            create table if not exists public.mafia_ai_settings (
                group_id bigint primary key,
                provider text not null default 'openai',
                model text,
                api_key_ciphertext bytea,
                web_search_enabled boolean not null default true,
                enabled boolean not null default false,
                updated_at timestamptz not null default now(),
                private_enabled boolean not null default false,
                private_provider text not null default 'gemini',
                private_model text,
                private_api_key_ciphertext bytea,
                private_web_search_enabled boolean not null default true,
                private_updated_at timestamptz
            )
        """))
        session.execute(text("""
            alter table public.mafia_ai_settings
              add column if not exists private_enabled boolean not null default false,
              add column if not exists private_provider text not null default 'gemini',
              add column if not exists private_model text,
              add column if not exists private_api_key_ciphertext bytea,
              add column if not exists private_web_search_enabled boolean not null default true,
              add column if not exists private_updated_at timestamptz
        """))
        session.execute(text("""
            create table if not exists public.mafia_ai_user_preferences (
                user_id bigint primary key,
                group_id bigint not null,
                updated_at timestamptz not null default now()
            )
        """))
        session.commit()


async def _thread_call(label: str, func: Any, *args: Any, timeout: float = 12.0, **kwargs: Any) -> Any:
    """Run blocking DB/network work without allowing one stage to swallow the whole webhook."""
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(func, *args, **kwargs),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        logging.error("knowledge assistant: %s timed out after %.1fs", label, timeout)
        return None
    except Exception:
        logging.exception("knowledge assistant: %s failed", label)
        return None


async def _send_plain_reply(message: Any, text: str) -> bool:
    """Send a plain Telegram message with a guaranteed fallback path."""
    if not text:
        text = "پاسخی تولید نشد."
    for kwargs in (
        {"disable_web_page_preview": True},
        {},
    ):
        try:
            await message.reply(text, **kwargs)
            return True
        except Exception:
            logging.exception("knowledge assistant: reply failed kwargs=%s", kwargs)
    return False


async def _edit_assistant_message(bot: Any, sent_message: Any, text: str) -> bool:
    """Replace the temporary acknowledgement with the final answer."""
    if not sent_message or not text:
        return False
    try:
        await bot.edit_message_text(
            chat_id=sent_message.chat.id,
            message_id=sent_message.message_id,
            text=text,
            disable_web_page_preview=True,
        )
        return True
    except Exception:
        logging.exception("knowledge assistant: final message edit failed")
        return False


def _ai_private_candidate_groups() -> list[int]:
    _ensure_ai_settings_table()
    with KnowledgeRepository().SessionLocal() as session:
        from sqlalchemy import text
        rows = session.execute(text("""
            select group_id from public.mafia_ai_settings
            where private_enabled=true and api_key_ciphertext is not null
            order by group_id
        """)).mappings().all()
    return [int(r["group_id"]) for r in rows]


def _get_ai_user_preference(user_id: int) -> int | None:
    _ensure_ai_settings_table()
    with KnowledgeRepository().SessionLocal() as session:
        from sqlalchemy import text
        row = session.execute(
            text("select group_id from public.mafia_ai_user_preferences where user_id=:uid limit 1"),
            {"uid": int(user_id)},
        ).mappings().first()
    return int(row["group_id"]) if row else None


def _set_ai_user_preference(user_id: int, group_id: int) -> None:
    _ensure_ai_settings_table()
    with KnowledgeRepository().SessionLocal() as session:
        from sqlalchemy import text
        session.execute(text("""
            insert into public.mafia_ai_user_preferences(user_id,group_id,updated_at)
            values(:uid,:gid,now())
            on conflict(user_id) do update set group_id=:gid,updated_at=now()
        """), {"uid": int(user_id), "gid": int(group_id)})
        session.commit()


async def _resolve_private_group(message: Any, app: Any) -> tuple[int | None, str]:
    if getattr(message.chat, "type", None) != "private":
        return None, ""
    candidates = await _thread_call("AI private group candidates", _ai_private_candidate_groups, timeout=5.0)
    candidates = [int(x) for x in (candidates or [])]
    if not candidates:
        return None, "none"
    preferred = await _thread_call("AI private group preference", _get_ai_user_preference, int(message.from_user.id), timeout=4.0)
    if preferred is not None and int(preferred) in candidates:
        try:
            member = await app.bot.get_chat_member(int(preferred), int(message.from_user.id))
            if str(getattr(member, "status", "")) not in {"left", "kicked"}:
                return int(preferred), "selected"
        except Exception:
            logging.exception("knowledge assistant: preferred private group membership check failed")
    eligible: list[int] = []
    for gid in candidates:
        try:
            member = await app.bot.get_chat_member(gid, int(message.from_user.id))
            if str(getattr(member, "status", "")) not in {"left", "kicked"}:
                eligible.append(gid)
        except Exception:
            logging.exception("knowledge assistant: private group membership check failed for %s", gid)
    if len(eligible) == 1:
        await _thread_call("save AI private group preference", _set_ai_user_preference, int(message.from_user.id), eligible[0], timeout=4.0)
        return eligible[0], "selected"
    if len(eligible) > 1:
        return None, "multiple"
    return None, "none"
async def answer(message: Any, app: Any, question: str) -> None:
    resolved_private_gid = None
    if getattr(message.chat, "type", None) == "private":
        resolved_private_gid, resolution = await _resolve_private_group(message, app)
        if resolution == "multiple":
            await _send_plain_reply(message, "ℹ️ شما عضو چند گروه فعال برای دستیار هستید. ابتدا از «🤖 پنل دستیار» گروه موردنظر را انتخاب کنید و سپس سؤال را ارسال کنید.")
            return
        if resolution != "selected":
            await _send_plain_reply(message, "⛔ شما در هیچ گروه فعالِ دستیار عضو نیستید.")
            return

    question = (question or "").strip()
    if not question:
        await _send_plain_reply(message, "❓ سوالت را بعد از /ask بنویس.")
        return

    try:
        await message.bot.send_chat_action(message.chat.id, "typing")
    except Exception:
        pass

    # Use one visible message for the whole interaction. It starts as a
    # progress notice and is replaced by the final answer instead of creating
    # a second message for the same question.
    progress_message = None
    try:
        progress_message = await message.reply(
            "⏳ در حال بررسی پایگاه دانش و آماده‌سازی پاسخ..."
        )
    except Exception:
        logging.exception("knowledge assistant: acknowledgement send failed")

    scenario_name, role_name = _game_context(app, message)

    repo = None
    try:
        repo = KnowledgeRepository()
    except Exception:
        logging.exception("knowledge assistant: repository initialization failed")

    rows: list[dict[str, Any]] = []
    explicit_role: str | None = None
    explicit_scenario: str | None = None
    if repo is not None:
        explicit = await _thread_call(
            "explicit knowledge context",
            repo.find_explicit_context,
            question,
            timeout=8.0,
        )
        if isinstance(explicit, dict):
            roles = [str(x).strip() for x in (explicit.get("roles") or []) if str(x).strip()]
            scenarios = [str(x).strip() for x in (explicit.get("scenarios") or []) if str(x).strip()]
            qnorm = question.replace("ي", "ی").replace("ك", "ک")
            import re
            m_role = re.search(r"(?:نقش|کاراکتر)\s+([^\s؟?]+(?:\s+[^\s؟?]+)?)", qnorm)
            m_scenario = re.search(r"(?:سناریو|سناریوی)\s+([^\s؟?]+(?:\s+[^\s؟?]+)?)", qnorm)
            if m_role:
                candidate = m_role.group(1).strip()
                explicit_role = next((r for r in roles if r in candidate or candidate in r), None)
            if m_scenario:
                candidate = m_scenario.group(1).strip()
                explicit_scenario = next((s for s in scenarios if s in candidate or candidate in s), None)
            if explicit_role is None and roles and not m_scenario:
                explicit_role = roles[0]
            if explicit_scenario is None and scenarios and not m_role:
                explicit_scenario = scenarios[0]

    if repo is not None:
        result = await _thread_call(
            "knowledge lookup",
            repo.get_context,
            question,
            scenario_name=explicit_scenario if explicit_scenario is not None else (None if explicit_role else scenario_name),
            role_name=explicit_role if explicit_role is not None else (None if explicit_scenario else role_name),
            limit=8,
            timeout=10.0,
        )
        if isinstance(result, list):
            rows = result
        if not rows:
            broad = " ".join(
                token for token in question.replace("؟", " ").replace("?", " ").split()
                if len(token.strip()) >= 3
            )
            if broad and broad != question:
                result = await _thread_call(
                    "broad knowledge lookup",
                    repo.get_context,
                    broad,
                    scenario_name=explicit_scenario if explicit_scenario is not None else (None if explicit_role else scenario_name),
                    role_name=explicit_role if explicit_role is not None else (None if explicit_scenario else role_name),
                    limit=8,
                    timeout=8.0,
                )
                if isinstance(result, list):
                    rows = result

    # Explicit/internal knowledge must not be diluted with unrelated web results.
    web: list[dict[str, str]] = []
    if not rows:
        result = await _thread_call(
            "web search",
            _web_search,
            (f"مافیا {scenario_name or ''} {role_name or ''} {question}").strip(),
            timeout=10.0,
        )
        if isinstance(result, list):
            web = result

    config = await _thread_call(
        "AI settings lookup", _ai_config, app, message, resolved_private_gid, timeout=8.0
    )
    if isinstance(config, tuple) and len(config) == 4:
        ai_enabled, api_key, provider, model = config
    else:
        ai_enabled, api_key, provider, model = False, None, "gemini", None

    response: str | None = None
    if ai_enabled and api_key:
        logging.info(
            "knowledge assistant: AI generation starting provider=%s model=%s context_rows=%s web_rows=%s chat_type=%s",
            provider, model or "default", len(rows), len(web), getattr(message.chat, "type", None),
        )
        response = await _thread_call(
            "AI generation",
            _call_ai,
            question,
            rows,
            web,
            api_key,
            provider,
            model,
            timeout=35.0,
        )

    if response is None:
        # Never silently turn an AI-enabled request into a shallow first-document
        # answer. That masks provider/routing failures and makes the user think
        # the model answered when it did not.
        if ai_enabled and api_key:
            logging.error(
                "knowledge assistant: AI generation returned no response; refusing silent KB fallback provider=%s model=%s",
                provider, model or "default",
            )
            response = (
                "⚠️ سؤال به دستیار هوش مصنوعی رسید، اما تولید پاسخ توسط سرویس AI انجام نشد. "
                "پایگاه دانش داخلی پیدا شد، ولی برای جلوگیری از پاسخ سطحی، آن را به‌جای پاسخ هوش مصنوعی نمایش نمی‌دهم."
            )
            suffix = ""
        elif rows:
            response = str(rows[0].get("content") or "").strip()
            suffix = "\n\nمنبع: پایگاه دانش داخلی Mafia Nights"
        elif web:
            response = "اطلاعات داخلی کافی نبود. منابع بیرونی مرتبط پیدا شد:\n" + "\n".join(
                f'• {x.get("title", "").strip()} — {x.get("url", "").strip()}'
                for x in web
                if x.get("title") and x.get("url")
            )
            suffix = "\n\nمنبع: جست‌وجوی وب؛ نیازمند بررسی"
        else:
            response = (
                "در پایگاه دانش ربات اطلاعات کافی برای این سؤال پیدا نشد. "
                "اگر API دستیار فعال باشد، پاسخ هوش مصنوعی نیز در دسترس خواهد بود."
            )
            suffix = ""
    else:
        suffix = ""
        if rows:
            suffix += "\n\nپاسخ بر اساس پایگاه دانش داخلی و قوانین سناریوی جاری تنظیم شده است."
        elif web:
            suffix += "\n\nپاسخ با کمک منابع بیرونی تهیه شده است."

    final_text = (response or "پاسخی تولید نشد.") + suffix
    chunks = [final_text[i:i + 3800] for i in range(0, len(final_text), 3800)] or ["پاسخی تولید نشد."]

    # First chunk replaces the progress message. Only additional chunks create
    # new messages when Telegram's 4096-character limit requires them.
    edited = await _edit_assistant_message(
        getattr(message, "bot", None), progress_message, chunks[0]
    )
    if not edited:
        if not await _send_plain_reply(message, chunks[0]):
            logging.error("knowledge assistant: unable to deliver first response chunk")

    for chunk in chunks[1:]:
        if not await _send_plain_reply(message, chunk):
            logging.error("knowledge assistant: unable to deliver response chunk")


def install(app: Any) -> bool:
    if getattr(app, "_knowledge_assistant_installed", False):
        return False
    app._knowledge_assistant_installed = True

    async def handler(message: Any):
        text = str(getattr(message, "text", "") or "").strip()
        lowered = text.casefold()
        question = ""
        if lowered.startswith("/ask"):
            question = text[4:].strip()
        elif lowered.startswith("/mafia"):
            question = text[6:].strip()
        elif lowered.startswith("سوال"):
            question = text[4:].strip()
        elif lowered.startswith("سؤال"):
            question = text[4:].strip()

        if not question:
            await message.reply(
                "🤖 <b>دستیار Mafia Nights</b>\n\n"
                "مثال:\n<code>/ask نقش زودیاک چه توانایی دارد؟</code>",
                parse_mode="HTML",
            )
            return
        try:
            await answer(message, app, question)
        except Exception:
            logging.exception("knowledge assistant: answer failed")
            await message.reply("⚠️ پردازش سؤال با خطا مواجه شد. لطفاً دوباره تلاش کنید.")

    from aiogram import types

    app.dp.register_message_handler(
        handler,
        lambda m: (
            str(getattr(m, "text", "") or "")
            .casefold()
            .startswith(("/ask", "/mafia", "سوال", "سؤال"))
        ),
        state="*",
        content_types=types.ContentTypes.TEXT,
    )
    async def auto_handler(message: Any):
        text = str(getattr(message, "text", "") or "").strip()
        if not _looks_like_question(text):
            return
        enabled, _api_key, _provider, _model = await _thread_call(
            "AI auto-route settings", _ai_config, app, message, None, timeout=5.0
        )
        if not enabled:
            return
        await answer(message, app, text)

    app.dp.register_message_handler(
        auto_handler,
        lambda m: _looks_like_question(str(getattr(m, "text", "") or "")),
        state="*",
        content_types=types.ContentTypes.TEXT,
    )
    # Expose both handlers so the real production entry can re-arm their
    # priority after later feature installers register generic text handlers.
    app._knowledge_assistant_handler = handler
    app._knowledge_assistant_auto_handler = auto_handler
    registry = getattr(getattr(app.dp, "message_handlers", None), "handlers", [])
    for i, item in enumerate(list(registry)):
        callback = getattr(item, "handler", None) or getattr(item, "callback", None)
        if callback is handler:
            registry.insert(0, registry.pop(i))
            break
    for i, item in enumerate(list(registry)):
        callback = getattr(item, "handler", None) or getattr(item, "callback", None)
        if callback is auto_handler:
            registry.insert(1 if registry else 0, registry.pop(i))
            break
    logging.info("Mafia knowledge assistant installed")
    return True
