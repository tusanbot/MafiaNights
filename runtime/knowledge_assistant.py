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


def _ai_config(app: Any, message: Any) -> tuple[bool, str | None]:
    try:
        gid = int(message.chat.id)
        with KnowledgeRepository().SessionLocal() as session:
            from sqlalchemy import text
            row = session.execute(
                text(
                    """select enabled,
                              case when api_key_ciphertext is null then null
                                   else pgp_sym_decrypt(api_key_ciphertext, :secret)
                              end as api_key
                       from public.mafia_ai_settings where group_id=:gid"""
                ),
                {"gid": gid, "secret": os.getenv("DATABASE_URL") or ""},
            ).mappings().first()
        if not row:
            return False, os.getenv("MAFIA_AI_API_KEY")
        return bool(row["enabled"]), (
            str(row["api_key"]) if row["api_key"] else os.getenv("MAFIA_AI_API_KEY")
        )
    except Exception:
        logging.exception("knowledge assistant: AI config lookup failed")
        return False, os.getenv("MAFIA_AI_API_KEY")


def _call_ai(
    prompt: str,
    context: list[dict[str, Any]],
    web: list[dict[str, str]],
    api_key: str | None = None,
) -> str | None:
    api_key = api_key or os.getenv("MAFIA_AI_API_KEY")
    if not api_key:
        return None

    model = os.getenv("MAFIA_AI_MODEL", "gpt-5.6-mini")
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


async def answer(message: Any, app: Any, question: str) -> None:
    question = (question or "").strip()
    if not question:
        await message.reply("❓ سوالت را بعد از /ask بنویس.")
        return

    try:
        await message.bot.send_chat_action(message.chat.id, "typing")
    except Exception:
        pass

    scenario_name, role_name = _game_context(app, message)
    repo = KnowledgeRepository()
    # Repository/network operations are synchronous; never block aiogram's event loop.
    rows = await asyncio.to_thread(
        repo.get_context,
        question,
        scenario_name=scenario_name,
        role_name=role_name,
        limit=8,
    )

    # Only query the web when internal knowledge is absent or clearly insufficient.
    web = (
        []
        if len(rows) >= 2
        else await asyncio.to_thread(
            _web_search,
            (f"مافیا {scenario_name or ''} {role_name or ''} {question}").strip(),
        )
    )
    ai_enabled, api_key = await asyncio.to_thread(_ai_config, app, message)
    response = (
        await asyncio.to_thread(_call_ai, question, rows, web, api_key)
        if ai_enabled
        else None
    )

    if response is None:
        if rows:
            response = rows[0]["content"]
            suffix = "\n\n<i>منبع: پایگاه دانش داخلی Mafia Nights</i>"
        elif web:
            response = "اطلاعات داخلی کافی نبود. منابع بیرونی مرتبط پیدا شد:\n" + "\n".join(
                f'• <a href="{html.escape(x["url"], quote=True)}">{html.escape(x["title"])}</a>'
                for x in web
            )
            suffix = "\n\n<i>منبع: جست‌وجوی وب؛ نیازمند بررسی</i>"
        else:
            response = (
                "در پایگاه دانش ربات اطلاعات کافی برای این سؤال پیدا نشد و "
                "جست‌وجوی وب هم نتیجه قابل اتکایی نداد."
            )
            suffix = ""
    else:
        suffix = ""
        if rows:
            suffix += "\n\n<i>پاسخ بر اساس پایگاه دانش داخلی و قوانین سناریوی جاری تنظیم شده است.</i>"
        elif web:
            suffix += "\n\n<i>پاسخ با کمک منابع بیرونی تهیه شده است.</i>"

    await message.reply(
        response + suffix,
        parse_mode="HTML",
        disable_web_page_preview=True,
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
