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


def _ai_config(app: Any, message: Any) -> tuple[bool, str | None, str, str | None]:
    """Load AI settings and safely infer Gemini from an AIza key.
    
    Older installations stored every key as provider=openai. Gemini keys are
    recognizable by the AIza prefix, so an existing registration is upgraded
    transparently without requiring the moderator to re-enter the key.
    """
    try:
        gid = int(message.chat.id)
        with KnowledgeRepository().SessionLocal() as session:
            from sqlalchemy import text
            row = session.execute(
                text(
                    """select enabled, provider, model,
                              case when api_key_ciphertext is null then null
                                   else pgp_sym_decrypt(api_key_ciphertext, :secret)
                              end as api_key
                       from public.mafia_ai_settings where group_id=:gid"""
                ),
                {"gid": gid, "secret": os.getenv("DATABASE_URL") or ""},
            ).mappings().first()
        if not row:
            # AI configuration is global. A private chat, another group, or a
            # group without an explicit registration must never lose access to
            # the bot-wide assistant settings. Row 0 is the canonical global
            # setting; the final query keeps compatibility with older installs.
            with KnowledgeRepository().SessionLocal() as fallback_session:
                row = fallback_session.execute(
                    text(
                        """select enabled, provider, model,
                                  case when api_key_ciphertext is null then null
                                       else pgp_sym_decrypt(api_key_ciphertext, :secret)
                                  end as api_key
                           from public.mafia_ai_settings
                           where group_id = 0
                           limit 1"""
                    ),
                    {"secret": os.getenv("DATABASE_URL") or ""},
                ).mappings().first()
            if not row:
                # Migrate the newest legacy group-scoped key into the global row
                # transparently. This is important for installations where the
                # moderator registered the Gemini key before global settings
                # were introduced.
                with KnowledgeRepository().SessionLocal() as fallback_session:
                    legacy = fallback_session.execute(
                        text(
                            """select enabled, provider, model, api_key_ciphertext
                               from public.mafia_ai_settings
                               where group_id <> 0
                                 and api_key_ciphertext is not null
                               order by updated_at desc
                               limit 1"""
                        )
                    ).mappings().first()
                    if legacy:
                        fallback_session.execute(
                            text(
                                """insert into public.mafia_ai_settings
                                   (group_id,provider,model,api_key_ciphertext,
                                    web_search_enabled,enabled,updated_at)
                                   values(0,:provider,:model,:ciphertext,true,:enabled,now())
                                   on conflict(group_id) do nothing"""
                            ),
                            dict(legacy),
                        )
                        fallback_session.commit()
                        row = fallback_session.execute(
                            text(
                                """select enabled, provider, model,
                                          case when api_key_ciphertext is null then null
                                               else pgp_sym_decrypt(api_key_ciphertext, :secret)
                                          end as api_key
                                   from public.mafia_ai_settings
                                   where group_id = 0
                                   limit 1"""
                            ),
                            {"secret": os.getenv("DATABASE_URL") or ""},
                        ).mappings().first()
            if not row:
                with KnowledgeRepository().SessionLocal() as fallback_session:
                    row = fallback_session.execute(
                        text(
                            """select enabled, provider, model,
                                      case when api_key_ciphertext is null then null
                                           else pgp_sym_decrypt(api_key_ciphertext, :secret)
                                      end as api_key
                               from public.mafia_ai_settings
                               where enabled = true
                                 and api_key_ciphertext is not null
                               order by updated_at desc
                               limit 1"""
                        ),
                        {"secret": os.getenv("DATABASE_URL") or ""},
                    ).mappings().first()
        if not row:
            key = os.getenv("MAFIA_AI_API_KEY")
            provider = "gemini" if str(key or "").startswith("AIza") else "openai"
            return False, key, provider, None
        key = str(row["api_key"]) if row["api_key"] else os.getenv("MAFIA_AI_API_KEY")
        provider = str(row["provider"] or "").lower()
        if str(key or "").startswith("AIza"):
            provider = "gemini"
        if provider not in {"gemini", "openai"}:
            provider = "gemini" if str(key or "").startswith("AIza") else "openai"
        model = str(row["model"]) if row["model"] else None
        if provider == "gemini" and (not model or model.startswith(("gpt-", "o1", "o3", "o4"))):
            model = "gemini-2.5-flash"
        return bool(row["enabled"]), key, provider, model
    except Exception:
        logging.exception("knowledge assistant: AI config lookup failed")
        key = os.getenv("MAFIA_AI_API_KEY")
        provider = "gemini" if str(key or "").startswith("AIza") else "openai"
        return False, key, provider, None


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
            + ":generateContent?key="
            + urllib.parse.quote(api_key, safe="")
        )
        req = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=25) as response:
                obj = json.loads(response.read().decode("utf-8"))
            parts = obj.get("candidates", [{}])[0].get("content", {}).get("parts", [])
            text_parts = [str(p.get("text", "")) for p in parts if p.get("text")]
            return "".join(text_parts).strip() or None
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


async def answer(message: Any, app: Any, question: str) -> None:
    question = (question or "").strip()
    if not question:
        await _send_plain_reply(message, "❓ سوالت را بعد از /ask بنویس.")
        return

    try:
        await message.bot.send_chat_action(message.chat.id, "typing")
    except Exception:
        pass

    # Immediate acknowledgement is intentionally sent before every DB/network stage.
    try:
        await message.reply("⏳ در حال بررسی پایگاه دانش و آماده‌سازی پاسخ...")
    except Exception:
        logging.exception("knowledge assistant: acknowledgement send failed")

    scenario_name, role_name = _game_context(app, message)

    # Do not let a slow/broken legacy DB prevent an answer.
    repo = None
    try:
        repo = KnowledgeRepository()
    except Exception:
        logging.exception("knowledge assistant: repository initialization failed")

    rows: list[dict[str, Any]] = []
    if repo is not None:
        result = await _thread_call(
            "knowledge lookup",
            repo.get_context,
            question,
            scenario_name=scenario_name,
            role_name=role_name,
            limit=8,
            timeout=10.0,
        )
        if isinstance(result, list):
            rows = result

    # Web is only a fallback, and is bounded so it cannot block Telegram indefinitely.
    web: list[dict[str, str]] = []
    if len(rows) < 2:
        result = await _thread_call(
            "web search",
            _web_search,
            (f"مافیا {scenario_name or ''} {role_name or ''} {question}").strip(),
            timeout=10.0,
        )
        if isinstance(result, list):
            web = result

    # Load the key/config separately from the AI call. If settings are broken,
    # the internal KB/web fallback must still produce a visible answer.
    config = await _thread_call("AI settings lookup", _ai_config, app, message, timeout=8.0)
    if isinstance(config, tuple) and len(config) == 4:
        ai_enabled, api_key, provider, model = config
    else:
        ai_enabled, api_key, provider, model = False, None, "gemini", None

    response: str | None = None
    if ai_enabled and api_key:
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
        if rows:
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

    # Telegram has a message-size limit. Keep every chunk safely below it.
    chunks = [final_text[i:i + 3800] for i in range(0, len(final_text), 3800)] or ["پاسخی تولید نشد."]
    sent = False
    for chunk in chunks:
        if await _send_plain_reply(message, chunk):
            sent = True
        else:
            logging.error("knowledge assistant: unable to deliver final response chunk")

    # Never leave the user with only the acknowledgement.
    if not sent:
        await _send_plain_reply(
            message,
            "⚠️ پاسخ آماده شد اما ارسال پیام نهایی ناموفق بود. لطفاً دوباره سؤال را ارسال کنید.",
        )


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
    registry = getattr(getattr(app.dp, "message_handlers", None), "handlers", [])
    for i, item in enumerate(list(registry)):
        if getattr(item, "handler", None) is handler:
            registry.insert(0, registry.pop(i))
            break
    logging.info("Mafia knowledge assistant installed")
    return True
