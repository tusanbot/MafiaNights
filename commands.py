"""Canonical text-command registry for MafiaNights.

This module owns slash/text entry points that are not part of the legacy
game-state handlers. It also provides one grouped command reference so the
documented commands stay aligned with executable handlers.
"""
from __future__ import annotations

import html
import logging
from types import SimpleNamespace
from typing import Any, Awaitable, Callable

from aiogram import types
from aiogram.dispatcher.handler import CancelHandler

CommandHandler = Callable[[types.Message], Awaitable[None]]

# These are the commands implemented directly in this module. Other active
# commands are owned by runtime.command_surface_v2 and are listed below in the
# shared command reference.
COMMANDS = {
    "commands": {"commands", "دستورات", "دستورها"},
    "ask": {"ask", "mafia", "سوال", "سؤال"},
    "ai_on": {"ai_on", "فعال کردن هوش مصنوعی"},
    "ai_off": {"ai_off", "غیرفعال کردن هوش مصنوعی"},
    "ai_status": {"ai_status", "وضعیت هوش مصنوعی"},
    "ai_key": {"ai_key", "ثبت کلید هوش مصنوعی"},
    "newgame": {"newgame", "بازی جدید"},
    "join": {"join", "ورود"},
    "leave": {"leave", "خروج"},
    "chatlock": {"chatlock", "قفل چت"},
    "chatunlock": {"chatunlock", "بازکردن چت", "باز کردن چت"},
    "nightlock": {"nightlock", "قفل شب"},
    "nightunlock": {"nightunlock", "بازکردن شب", "باز کردن شب"},
    "turnlock": {"turnlock", "قفل نوبت"},
    "turnunlock": {"turnunlock", "بازکردن نوبت", "باز کردن نوبت"},
    "tag_all": {"tagall", "تگ همه", "tag all"},
    "tag_admins": {"tagadmins", "تگ ادمین", "tag admins"},
    "tag_list": {"taglist", "تگ لیست", "tag list"},
}


def normalize_text(value: str | None) -> str:
    text = (value or "").strip().replace("‌", " ")
    text = " ".join(text.split())
    if text.startswith("/"):
        text = text[1:]
    # Telegram may append a bot username to slash commands.
    if "@" in text:
        text = text.split("@", 1)[0]
    return text.casefold()


def resolve_command(value: str | None) -> str | None:
    normalized = normalize_text(value)
    for command, aliases in COMMANDS.items():
        if normalized in {normalize_text(alias) for alias in aliases}:
            return command
    return None


def _group_id(app: Any, message: types.Message) -> int | None:
    if message.chat.type in {"group", "supergroup"}:
        return int(message.chat.id)
    for key in ("group_chat_id", "ALLOWED_GROUP_ID", "GROUP_ID", "group_id"):
        value = getattr(app, key, None)
        if value:
            try:
                return int(value)
            except (TypeError, ValueError):
                pass
    return None


def _known_players(app: Any, group_id: int | None) -> dict[int, Any]:
    players = getattr(app, "players", {}) or {}
    if not isinstance(players, dict):
        return {}
    return {int(uid): value for uid, value in players.items() if str(uid).lstrip("-").isdigit()}


def _display_name(app: Any, uid: int, fallback: Any = "❓") -> str:
    try:
        fn = getattr(app, "display_name", None)
        if callable(fn):
            value = fn(uid, fallback)
            if value:
                return str(value)
    except Exception:
        logging.exception("text command: display_name failed")
    if isinstance(fallback, dict):
        return str(fallback.get("nickname") or fallback.get("full_name") or fallback.get("first_name") or "❓")
    return str(fallback or "❓")


def _mention(uid: int, name: str) -> str:
    return f"<a href='tg://user?id={uid}'>{html.escape(name)}</a>"


COMMAND_REFERENCE = (
    ("🎮 بازی و لابی", (
        ("/newgame", "بازی جدید"),
        ("/join", "ورود"),
        ("/leave", "خروج"),
        ("/sub", "افزودن بازیکن جایگزین"),
        ("/sub_list", "لیست جایگزین‌ها"),
        ("/sub_del", "حذف جایگزین"),
    )),
    ("🛠 مدیریت بازی", (
        ("/stats", "آمار"),
        ("/vote", "رأی‌گیری"),
        ("/end", "اتمام بازی"),
        ("/night", "فاز شب"),
        ("/day", "شروع روز"),
        ("/chief", "تغییر سردست"),
        ("/remove", "حذف بازیکن"),
        ("/start_round", "شروع دور"),
        ("/next", "نکست"),
        ("/next_settings", "تنظیم نکست"),
        ("/challenge_settings", "تنظیم چالش"),
        ("/mute", "سکوت"),
        ("/unmute", "حذف سکوت"),
        ("/extra", "ترن اضافه"),
    )),
    ("🔒 امنیت و قفل‌ها", (
        ("/chatlock", "قفل چت"),
        ("/chatunlock", "باز کردن چت"),
        ("/nightlock", "قفل شب"),
        ("/nightunlock", "باز کردن شب"),
        ("/turnlock", "قفل نوبت"),
        ("/turnunlock", "باز کردن نوبت"),
    )),
    ("👤 نام مستعار", (
        ("/nickname_set", "تنظیم مستعار"),
        ("/nickname_get", "نام مستعار"),
        ("/nickname_del", "حذف مستعار"),
        ("/nickname_list", "لیست مستعار"),
    )),
    ("📣 تگ و مدیران", (
        ("/tagall", "تگ همه بازیکنان"),
        ("/tagadmins", "تگ مدیران"),
        ("/taglist", "تگ لیست"),
    )),
    ("🤖 دستیار", (
        ("/ask", "پرسش از دستیار مافیا"),
        ("/mafia", "پرسش از دستیار مافیا"),
        ("/ai_on", "فعال‌سازی هوش مصنوعی"),
        ("/ai_off", "غیرفعال‌سازی هوش مصنوعی"),
        ("/ai_status", "وضعیت هوش مصنوعی"),
        ("/ai_key", "ثبت امن API Key"),
        ("/ask", "پرسش از دستیار مافیا"),
        ("/mafia", "پرسش از دستیار مافیا"),
    )),
    ("ℹ️ عمومی", (
        ("/start", "نمایش منوی اصلی"),
        ("/commands", "نمایش همه دستورات متنی"),
    )),
)


async def cmd_commands(message: types.Message, app: Any) -> None:
    lines = ["📖 <b>دستورات متنی Mafia Nights</b>", ""]
    for title, commands in COMMAND_REFERENCE:
        lines.append(f"<b>{html.escape(title)}</b>")
        lines.extend(f"<code>{html.escape(command)}</code> — {html.escape(label)}" for command, label in commands)
        lines.append("")
    await message.reply("\n".join(lines).rstrip(), parse_mode="HTML")


async def _ai_control(message: types.Message, app: Any, action: str) -> None:
    if message.chat.type not in {"group", "supergroup"}:
        await message.reply("⚠️ این دستور فقط داخل گروه قابل استفاده است.")
        return
    gid = int(message.chat.id)
    try:
        status = (await app.bot.get_chat_member(gid, int(message.from_user.id))).status
    except Exception:
        status = "left"
    if status not in {"creator", "administrator"} and int(message.from_user.id) != int(getattr(app, "moderator_id", 0) or 0):
        await message.reply("⛔ فقط گرداننده یا مدیر گروه.")
        return
    from repositories.knowledge_repository import KnowledgeRepository
    from sqlalchemy import text
    import os
    enabled = action == "on"
    if action != "status":
        with KnowledgeRepository().SessionLocal() as session:
            session.execute(text("""
                insert into public.mafia_ai_settings(group_id,provider,model,enabled,web_search_enabled,updated_at)
                values(:gid,'openai',:model,:enabled,true,now())
                on conflict(group_id) do update set enabled=:enabled, updated_at=now()
            """), {"gid": gid, "model": os.getenv("MAFIA_AI_MODEL") or None, "enabled": enabled})
            session.commit()
    if action == "status":
        with KnowledgeRepository().SessionLocal() as session:
            row=session.execute(text("select provider,model,enabled,web_search_enabled from public.mafia_ai_settings where group_id=:gid"),{"gid":gid}).mappings().first()
        key = bool(os.getenv("MAFIA_AI_API_KEY"))
        if not row:
            await message.reply(f"🤖 وضعیت: <b>غیرفعال</b>\n🔑 API Key: <b>{'ثبت شده در محیط اجرا' if key else 'ثبت نشده'}</b>",parse_mode="HTML")
            return
        await message.reply(
            f"🤖 وضعیت: <b>{'فعال' if row['enabled'] else 'غیرفعال'}</b>\n"
            f"🧠 مدل: <code>{html.escape(str(row['model'] or os.getenv('MAFIA_AI_MODEL') or 'پیش‌فرض'))}</code>\n"
            f"🔑 API Key: <b>{'ثبت شده در محیط اجرا' if key else 'ثبت نشده'}</b>\n"
            f"🌐 جست‌وجوی وب: <b>{'فعال' if row['web_search_enabled'] else 'غیرفعال'}</b>",
            parse_mode="HTML"
        )
        return
    await message.reply(f"✅ دستیار هوش مصنوعی {'فعال' if enabled else 'غیرفعال'} شد.")

async def _ai_key(message: types.Message, app: Any) -> None:
    if message.chat.type not in {"group", "supergroup"}:
        await message.reply("⚠️ این دستور فقط داخل گروه قابل استفاده است.")
        return
    gid = int(message.chat.id)
    try:
        status = (await app.bot.get_chat_member(gid, int(message.from_user.id))).status
    except Exception:
        status = "left"
    if status not in {"creator", "administrator"} and int(message.from_user.id) != int(getattr(app, "moderator_id", 0) or 0):
        await message.reply("⛔ فقط گرداننده یا مدیر گروه.")
        return
    parts = (message.text or "").split(None, 1)
    key = parts[1].strip() if len(parts) > 1 else ""
    if not key:
        await message.reply("❗ فرمت: <code>/ai_key YOUR_API_KEY</code>\nکلید در پایگاه‌داده به‌صورت رمزنگاری‌شده نگهداری می‌شود.", parse_mode="HTML")
        return
    import os
    from repositories.knowledge_repository import KnowledgeRepository
    from sqlalchemy import text
    secret = os.getenv("DATABASE_URL") or ""
    if not secret:
        await message.reply("❌ اتصال امن پایگاه‌داده برای رمزنگاری در دسترس نیست.")
        return
    with KnowledgeRepository().SessionLocal() as session:
        session.execute(text("""
            insert into public.mafia_ai_settings(group_id,provider,model,enabled,web_search_enabled,api_key_ciphertext,updated_at)
            values(:gid,'openai',:model,false,true,pgp_sym_encrypt(:key,:secret),now())
            on conflict(group_id) do update set api_key_ciphertext=pgp_sym_encrypt(:key,:secret), updated_at=now()
        """), {"gid": gid, "model": os.getenv("MAFIA_AI_MODEL") or None, "key": key, "secret": secret})
        session.commit()
    try:
        await message.delete()
    except Exception:
        pass
    await message.answer("✅ API Key با موفقیت و به‌صورت رمزنگاری‌شده ثبت شد. برای فعال‌سازی از /ai_on استفاده کنید.")

async def cmd_tag_all(message: types.Message, app: Any) -> None:
    if message.chat.type not in {"group", "supergroup"}:
        await message.reply("⚠️ این دستور فقط داخل گروه قابل استفاده است.")
        return
    players = _known_players(app, message.chat.id)
    if not players:
        await message.reply("ℹ️ هنوز بازیکنی برای تگ‌کردن ثبت نشده است.")
        return
    mentions = [_mention(uid, _display_name(app, uid, value)) for uid, value in players.items()]
    await message.reply("🔔 <b>تگ بازیکنان شناخته‌شده:</b>\n" + "، ".join(mentions), parse_mode="HTML")


async def cmd_tag_admins(message: types.Message, app: Any) -> None:
    if message.chat.type not in {"group", "supergroup"}:
        await message.reply("⚠️ این دستور فقط داخل گروه قابل استفاده است.")
        return
    try:
        admins = await app.bot.get_chat_administrators(message.chat.id)
    except Exception:
        logging.exception("text command: failed to fetch administrators")
        await message.reply("❌ دریافت لیست مدیران گروه انجام نشد.")
        return
    mentions = [_mention(a.user.id, a.user.full_name or str(a.user.id)) for a in admins]
    await message.reply("🛡 <b>مدیران گروه:</b>\n" + "، ".join(mentions), parse_mode="HTML")


async def cmd_tag_players(message: types.Message, app: Any) -> None:
    await cmd_tag_all(message, app)


async def _newgame(message: types.Message, app: Any) -> None:
    if message.chat.type not in {"group", "supergroup"}:
        await message.reply("⚠️ این دستور فقط داخل گروه قابل استفاده است.")
        return
    handler = getattr(app, "_canonical_new_game_handler", None)
    if handler is None:
        await message.reply("⚠️ مسیر ایجاد بازی در دسترس نیست.")
        return
    callback = SimpleNamespace(
        message=message,
        from_user=message.from_user,
        data="fl_new",
        answer=message.answer,
        _from_text_command=True,
    )
    await handler(callback)


async def _join(message: types.Message, app: Any) -> None:
    if message.chat.type not in {"group", "supergroup"}:
        await message.reply("⚠️ این دستور فقط داخل گروه قابل استفاده است.")
        return
    gid = int(message.chat.id)
    game = app.runtime.state.active_game(gid)
    if not game or str(game.get("status") or "") != "lobby":
        await message.reply("❌ لابی فعالی وجود ندارد.")
        return
    from repositories.scenario_repository import ScenarioRepository
    scenario = ScenarioRepository().get_by_id(int(game.get("scenario_id") or 0))
    capacity = len((scenario or {}).get("roles") or [])
    rows = app.runtime.state.games.list_players(game["id"])
    uid = int(message.from_user.id)
    current = next((r for r in rows if int(r.get("player_id") or 0) == uid), None)
    if current and current.get("seat") is not None:
        await message.reply(f"ℹ️ شما قبلاً وارد بازی شده‌اید؛ صندلی {int(current['seat'])}.")
        return
    occupied = {int(r["seat"]) for r in rows if r.get("seat") is not None and str(r.get("status") or "active") not in {"removed", "dead", "finished", "kicked"}}
    seat = next((n for n in range(1, capacity + 1) if n not in occupied), None)
    if seat is None:
        await message.reply("🎟 ظرفیت اصلی تکمیل است؛ برای رزرو از پنل لابی استفاده کنید.")
        return
    try:
        await app._ensure_player(message.from_user)
    except Exception:
        pass
    app.runtime.state.lobby.join(game["id"], uid, seat, is_substitute=False)
    await message.reply(f"✅ وارد بازی شدید؛ صندلی <b>{seat}</b>.", parse_mode="HTML")


async def _leave(message: types.Message, app: Any) -> None:
    if message.chat.type not in {"group", "supergroup"}:
        await message.reply("⚠️ این دستور فقط داخل گروه قابل استفاده است.")
        return
    gid = int(message.chat.id)
    game = app.runtime.state.active_game(gid)
    if not game or str(game.get("status") or "") != "lobby":
        await message.reply("❌ لابی فعالی وجود ندارد.")
        return
    uid = int(message.from_user.id)
    rows = app.runtime.state.games.list_players(game["id"])
    current = next((r for r in rows if int(r.get("player_id") or 0) == uid), None)
    if not current:
        await message.reply("ℹ️ شما در لابی ثبت نشده‌اید.")
        return
    app.runtime.state.lobby.leave(game["id"], uid)
    await message.reply("🚪 از بازی خارج شدید.")


def _authorized(app: Any, message: types.Message) -> bool:
    uid = int(message.from_user.id)
    if uid == int(getattr(app, "moderator_id", 0) or 0):
        return True
    return False


async def _set_lock(message: types.Message, app: Any, key: str, enabled: bool, label: str) -> None:
    if message.chat.type not in {"group", "supergroup"}:
        await message.reply("⚠️ این دستور فقط داخل گروه قابل استفاده است.")
        return
    if not _authorized(app, message):
        try:
            status = (await app.bot.get_chat_member(message.chat.id, int(message.from_user.id))).status
        except Exception:
            status = "left"
        if status not in {"creator", "administrator"}:
            await message.reply("⛔ فقط گرداننده یا مدیر گروه می‌تواند این قفل را تغییر دهد.")
            return
    addons = getattr(app, "addons", None)
    if addons is None:
        await message.reply("❌ تنظیمات امکانات اضافه در دسترس نیست.")
        return
    gid = int(message.chat.id)
    settings = addons.get_group_settings(gid)
    settings.setdefault("security", {})[key] = bool(enabled)
    addons.set_group_settings(gid, settings)
    addons.settings = settings
    if key in {"chat_lock", "night_lock"}:
        try:
            from runtime.chat_locks import sync_group_permissions
            await sync_group_permissions(app, gid)
        except Exception:
            logging.exception("text command: failed to sync chat lock permissions")
    state = "فعال" if enabled else "غیرفعال"
    await message.reply(f"✅ {label}: <b>{state}</b>", parse_mode="HTML")


async def run_command(name: str, message: types.Message, app: Any) -> None:
    handlers = {
        "commands": cmd_commands,
        "ask": lambda m, a: __import__("runtime.knowledge_assistant", fromlist=["answer"]).answer(m, a, (m.text or "").split(" ", 1)[1] if " " in (m.text or "") else ""),
        "ai_on": lambda m, a: _ai_control(m, a, "on"),
        "ai_off": lambda m, a: _ai_control(m, a, "off"),
        "ai_status": lambda m, a: _ai_control(m, a, "status"),
        "ai_key": _ai_key,
        "newgame": _newgame,
        "join": _join,
        "leave": _leave,
        "chatlock": lambda m, a: _set_lock(m, a, "chat_lock", True, "قفل چت"),
        "chatunlock": lambda m, a: _set_lock(m, a, "chat_lock", False, "قفل چت"),
        "nightlock": lambda m, a: _set_lock(m, a, "night_lock", True, "قفل شب"),
        "nightunlock": lambda m, a: _set_lock(m, a, "night_lock", False, "قفل شب"),
        "turnlock": lambda m, a: _set_lock(m, a, "turn_lock", True, "قفل نوبت"),
        "turnunlock": lambda m, a: _set_lock(m, a, "turn_lock", False, "قفل نوبت"),
        "tag_all": cmd_tag_all,
        "tag_admins": cmd_tag_admins,
        "tag_list": cmd_tag_players,
    }
    handler = handlers.get(name)
    if handler:
        await handler(message, app)


def register_commands(app: Any) -> bool:
    dp = getattr(app, "dp", None)
    if dp is None or getattr(app, "_canonical_text_commands_installed", False):
        return False

    @dp.message_handler(lambda m: bool(resolve_command(getattr(m, "text", None))), state="*")
    async def handle_text_commands(message: types.Message):
        name = resolve_command(message.text)
        if not name:
            return
        await run_command(name, message, app)
        raise CancelHandler()

    app._canonical_text_commands_installed = True
    logging.info("Canonical text-command registry installed")
    return True
