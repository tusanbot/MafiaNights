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
    # Private / personal
    "pv": {"پیوی", "پی وی", "/pv"},
    "role": {"نقش من", "/role", "/myrole"},
    "panel": {"پنل", "/panel"},
    # Group / moderator
    "start_round": {"شروع دور", "/start_round"},
    "end_game": {"اتمام بازی", "پایان بازی", "/end"},
    "night": {"فاز شب", "شروع فاز شب", "/night"},
    "day": {"فاز روز", "شروع روز", "شروع فاز روز", "/day"},
    "warning": {"تذکر", "/warning"},
    "warning_remove": {"حذف تذکر", "تذکر منفی", "/warning_remove"},
    "kick": {"کیک", "/kick"},
    "mute": {"سکوت", "/mute"},
    "unmute": {"حذف سکوت", "/unmute"},
    "extra": {"ترن اضافه", "/extra"},
    "birthday": {"تولد", "/birthday"},
    "remove": {"حذف بازیکن", "/remove"},
    "cancel_game": {"لغو بازی", "/لغو_بازی", "/cancel_game", "/cancelgame"},
    "challenge_limited": {"چالش محدود", "/challenge_limited"},
    "challenge_free": {"چالش آزاد", "/challenge_free"},
    "chatlock": {"قفل چت", "/chatlock"},
    "chatunlock": {"بازکردن چت", "باز کردن چت", "/chatunlock"},
    "nightlock": {"قفل شب", "/nightlock"},
    "nightunlock": {"بازکردن شب", "باز کردن شب", "/nightunlock"},
    "turnlock": {"قفل نوبت", "/turnlock"},
    "turnunlock": {"بازکردن نوبت", "باز کردن نوبت", "/turnunlock"},
    # Group manager
    "newgame": {"بازی جدید", "/newgame"},
    # Public group
    "sub": {"جایگزین", "/sub"},
    "attendance": {"حاضری", "/attendance"},
    "management": {"مدیریت", "مدیریت بازی", "/management"},
    "lobby": {"لابی", "بازگشت به لابی", "/lobby"},
    "nickname_set": {"تنظیم مستعار", "تنظیم نام مستعار", "ثبت مستعار", "ثبت نام مستعار", "/nickname_set"},
    "nickname_del": {"حذف مستعار", "حذف نام مستعار", "/nickname_del"},
    "nickname_get": {"نام مستعار", "دیدن نام مستعار", "/nickname_get"},
    "nickname_list": {"لیست مستعار", "لیست نامهای مستعار", "لیست نام‌های مستعار", "/nickname_list"},
    "sub_list": {"لیست جایگزین", "لیست جایگزین‌ها", "/sub_list"},
    "sub_del": {"حذف جایگزین", "/sub_del"},
    "vote": {"رای گیری", "رأی گیری", "رای‌گیری", "رأی‌گیری", "/vote"},
    "chief": {"سردست", "تغییر سردست", "/chief"},
    "challenge_settings": {"تنظیم چالش", "/challenge_settings"},
    "next_settings": {"تنظیم نکست", "/next_settings"},
    "join": {"ورود", "/join"},
    "leave": {"خروج", "/leave"},
    "challenge": {"چالش", "/challenge"},
    "reserve": {"رزرو", "/reserve"},
    "unreserve": {"لغو رزرو", "/unreserve"},
    "seat": {"صندلی", "/seat"},
    # Turn owner / moderator
    "next": {"نکست", "/next"},
    # Existing non-game command surface
    "commands": {"commands", "دستورات", "دستورها"},
    "help": {"راهنما", "کمک", "/help"},
    "profile": {"پروفایل", "profile", "/profile"},
    "ranking": {"رتبه", "رتبه بندی", "رتبه‌بندی", "ranking", "rank", "/rank"},
    "stats": {"آمار", "امار", "آمار من", "امار من", "stats", "statistics", "امتیاز", "امتیاز من", "/stats"},
    "seats": {"لیست صندلی", "لیست صندلی‌ها", "صندلی ها", "صندلی‌ها"},
    "players": {"لیست بازیکنان", "بازیکنان"},
    "ask": {"ask", "mafia", "/ask", "/mafia", "سوال", "سؤال"},
    "ai_on": {"ai_on", "فعال کردن هوش مصنوعی"},
    "ai_off": {"ai_off", "غیرفعال کردن هوش مصنوعی"},
    "ai_status": {"ai_status", "وضعیت هوش مصنوعی"},
    "ai_key": {"ai_key", "ثبت کلید هوش مصنوعی"},
    "ai_panel": {"ai_panel", "پنل دستیار"},
    "kb_list": {"kb_list", "لیست دانش"},
    "kb_add": {"kb_add", "افزودن دانش"},
    "kb_publish": {"kb_publish", "انتشار دانش"},
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
        normalized_aliases = {normalize_text(alias) for alias in aliases}
        if normalized in normalized_aliases:
            return command
        if any(normalized.startswith(alias + " ") for alias in normalized_aliases):
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
    ("🔒 پیوی و شخصی", (
        ("پیوی", "پنل و امکانات پیوی"),
        ("نقش من", "نمایش نقش فعلی در پیوی"),
        ("پنل", "پنل متناسب با چت و سطح دسترسی"),
    )),
    ("🎩 گروه — گرداننده", (
        ("شروع دور", "شروع دور"),
        ("اتمام بازی", "اتمام دستی بازی"),
        ("فاز شب", "انتقال به فاز شب"),
        ("فاز روز", "انتقال به فاز روز"),
        ("تذکر", "ثبت تذکر با ریپلای"),
        ("حذف تذکر", "کاهش یک تذکر با ریپلای"),
        ("کیک", "حذف اجباری بازیکن با ریپلای"),
        ("سکوت", "ساکت‌کردن بازیکن با ریپلای"),
        ("حذف سکوت", "رفع سکوت با ریپلای"),
        ("ترن اضافه", "ثبت ترن اضافه با ریپلای"),
        ("تولد", "بازگردانی بازیکن حذف/مرده با ریپلای"),
        ("حذف بازیکن", "حذف بازیکن با ریپلای"),
        ("لغو بازی", "لغو بازی فعلی"),
        ("چالش محدود", "فعال‌سازی محدودیت چالش"),
        ("چالش آزاد", "آزادسازی چالش"),
        ("قفل چت", "قفل پیام برای غیر بازیکنان"),
        ("قفل شب", "فقط گرداننده اجازه صحبت دارد"),
        ("قفل نوبت", "فقط صاحب نوبت یا گرداننده؛ دیگران فقط نماد/ایموجی"),
    )),
    ("🛡 گروه — مدیر", (
        ("بازی جدید", "ایجاد بازی جدید"),
    )),
    ("👥 گروه — عمومی", (
        ("جایگزین", "افزودن بازیکن به لیست جایگزین با ریپلای اختیاری"),
        ("حاضری", "نمایش وضعیت آمادگی"),
        ("مدیریت", "بازکردن پنل مدیریت"),
        ("لابی", "نمایش و بازسازی لابی جاری"),
        ("تنظیم مستعار", "ثبت نام مستعار با ریپلای"),
        ("حذف مستعار", "حذف نام مستعار با ریپلای"),
        ("نام مستعار", "نمایش نام مستعار با ریپلای"),
        ("لیست مستعار", "لیست نام‌های مستعار"),
        ("ورود", "ورود به لابی"),
        ("خروج", "خروج از لابی"),
        ("چالش", "درخواست چالش با ریپلای"),
        ("رزرو", "رزرو پس از تکمیل ظرفیت"),
        ("لغو رزرو", "لغو رزرو"),
        ("صندلی عدد", "نمونه: صندلی 5"),
    )),
    ("🎯 صاحب ترن یا گرداننده", (
        ("نکست", "رفتن به نوبت بعدی"),
    )),
    ("ℹ️ عمومی", (
        ("/start", "نمایش منوی اصلی"),
        ("/commands", "نمایش همه دستورات متنی"),
        ("راهنما / کمک", "راهنمای دستورات"),
        ("پروفایل", "پروفایل"),
        ("رتبه", "رتبه‌بندی"),
        ("آمار", "آمار"),
        ("لیست بازیکنان", "لیست بازیکنان"),
        ("لیست صندلی", "لیست صندلی‌ها"),
    )),
    ("🤖 دستیار", (
        ("/ask", "پرسش از دستیار"),
        ("/mafia", "پرسش از دستیار"),
        ("دستیار <سؤال>", "پرسش مستقیم با کلمه کلیدی دستیار"),
        ("/ai_panel", "ثبت/انتخاب گروه و مدیریت دستیار"),
        ("/ai_on", "فعال‌سازی AI"),
        ("/ai_off", "غیرفعال‌سازی AI"),
        ("/ai_status", "وضعیت AI"),
        ("/ai_key", "ثبت امن API Key"),
        ("/kb_list", "لیست پایگاه دانش"),
        ("/kb_add", "افزودن مطلب"),
        ("/kb_publish", "انتشار مطلب"),
    )),
)



async def cmd_commands(message: types.Message, app: Any) -> None:
    lines = ["📖 <b>دستورات متنی Mafia Nights</b>", ""]
    for title, commands in COMMAND_REFERENCE:
        lines.append(f"<b>{html.escape(title)}</b>")
        lines.extend(f"<code>{html.escape(command)}</code> — {html.escape(label)}" for command, label in commands)
        lines.append("")
    await message.reply("\n".join(lines).rstrip(), parse_mode="HTML")


async def _ai_panel_text(message: types.Message, app: Any) -> None:
    from runtime.assistant_admin_panel import AssistantAdminPanel
    await AssistantAdminPanel(app).open(message)


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
    with KnowledgeRepository().SessionLocal() as session:
        session.execute(text("create extension if not exists pgcrypto"))
        session.execute(text("""
            create extension if not exists pgcrypto
        """))
        session.execute(text("""
            create table if not exists public.mafia_ai_settings (
                group_id bigint primary key,
                provider text not null default 'gemini',
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
        session.commit()
    if action != "status":
        with KnowledgeRepository().SessionLocal() as session:
            session.execute(text("""
                insert into public.mafia_ai_settings(group_id,provider,model,enabled,web_search_enabled,updated_at)
                values(:gid,'gemini',:model,:enabled,true,now())
                on conflict(group_id) do update set enabled=:enabled, updated_at=now()
            """), {"gid": gid, "model": "gemini-2.5-flash", "enabled": enabled})
            session.commit()
    if action == "status":
        with KnowledgeRepository().SessionLocal() as session:
            row=session.execute(text("""select provider,model,enabled,web_search_enabled,
                                      (api_key_ciphertext is not null) as has_db_key
                               from public.mafia_ai_settings
                               where group_id=:gid
                               limit 1""")).mappings().first()
        key = bool(os.getenv("MAFIA_AI_API_KEY")) or bool(row and row["has_db_key"])
        if not row:
            await message.reply(f"🤖 وضعیت: <b>غیرفعال</b>\n🔑 API Key: <b>{'ثبت شده در محیط اجرا' if key else 'ثبت نشده'}</b>",parse_mode="HTML")
            return
        await message.reply(
            f"🤖 وضعیت: <b>{'فعال' if row['enabled'] else 'غیرفعال'}</b>\n"
            f"🧠 مدل: <code>{html.escape(str(row['model'] or os.getenv('MAFIA_AI_MODEL') or 'پیش‌فرض'))}</code>\n"
            f"🔑 API Key: <b>{'ثبت شده و رمزنگاری‌شده' if row and row.get('has_db_key') else ('ثبت شده در محیط اجرا' if key else 'ثبت نشده')}</b>\n"
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
    with KnowledgeRepository().SessionLocal() as session:
        session.execute(text("create extension if not exists pgcrypto"))
        session.execute(text("""
            create extension if not exists pgcrypto
        """))
        session.execute(text("""
            create table if not exists public.mafia_ai_settings (
                group_id bigint primary key,
                provider text not null default 'gemini',
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
        session.commit()
    if not secret:
        await message.reply("❌ اتصال امن پایگاه‌داده برای رمزنگاری در دسترس نیست.")
        return
    # The legacy text command remains available, but the assistant is Gemini-only.
    provider = "gemini"
    default_model = "gemini-2.5-flash"
    with KnowledgeRepository().SessionLocal() as session:
        session.execute(text("""
            insert into public.mafia_ai_settings(group_id,provider,model,enabled,private_enabled,web_search_enabled,api_key_ciphertext,updated_at)
            values(:gid,:provider,:model,true,true,true,pgp_sym_encrypt(:key,:secret),now())
            on conflict(group_id) do update set
                provider=:provider,
                model=:model,
                enabled=true,
                private_enabled=true,
                api_key_ciphertext=pgp_sym_encrypt(:key,:secret),
                updated_at=now()
        """), {
            "gid": gid, "provider": provider, "model": default_model,
            "key": key, "secret": secret
        })
        session.commit()
    try:
        await message.delete()
    except Exception:
        pass
    await message.answer("✅ API Key با موفقیت و به‌صورت رمزنگاری‌شده ثبت شد و دستیار به‌صورت سراسری فعال شد.")

async def _kb_control(message: types.Message, app: Any, action: str) -> None:
    if message.chat.type not in {"group", "supergroup"}:
        await message.reply("⚠️ این دستور فقط داخل گروه قابل استفاده است.")
        return
    try:
        status = (await app.bot.get_chat_member(message.chat.id, int(message.from_user.id))).status
    except Exception:
        status = "left"
    if status not in {"creator", "administrator"} and int(message.from_user.id) != int(getattr(app, "moderator_id", 0) or 0):
        await message.reply("⛔ فقط گرداننده یا مدیر گروه.")
        return
    from repositories.knowledge_repository import KnowledgeRepository
    from sqlalchemy import text
    repo = KnowledgeRepository()
    if action == "list":
        with repo.SessionLocal() as session:
            rows = session.execute(text("select id,title,scope,status,scenario_name,role_name from public.mafia_knowledge_documents where is_active=true order by updated_at desc limit 20")).mappings().all()
        if not rows:
            await message.reply("📚 پایگاه دانش خالی است.")
            return
        lines = ["📚 <b>آخرین مطالب پایگاه دانش</b>", ""]
        lines += [f"<code>{r['id']}</code> — {html.escape(str(r['title']))} — {r['status']}" for r in rows]
        await message.reply("\n".join(lines), parse_mode="HTML")
        return
    parts = (message.text or "").split("|")
    if action == "add":
        if len(parts) < 7:
            await message.reply("فرمت: <code>/kb_add|scope|عنوان|متن|نام سناریو|نام نقش|آدرس منبع</code>", parse_mode="HTML")
            return
        scope, title, content, scenario, role, url = (x.strip() for x in parts[1:7])
        if scope not in {"global", "scenario", "role", "tutorial", "faq"}:
            await message.reply("❌ scope باید global یا scenario یا role یا tutorial یا faq باشد.")
            return
        doc_id = repo.add_document(
            title=title, content=content, scope=scope,
            scenario_name=scenario or None, role_name=role or None,
            status="draft", source_type="web" if url else "internal",
            source_url=url or None, confidence="unverified",
        )
        await message.reply(f"✅ مطلب با شناسه <code>{doc_id}</code> به‌صورت پیش‌نویس ثبت شد.", parse_mode="HTML")
        return
    try:
        doc_id = int((message.text or "").split(None, 1)[1].strip())
    except Exception:
        await message.reply("❗ شناسه مطلب را وارد کنید.")
        return
    if action == "publish":
        with repo.SessionLocal() as session:
            session.execute(text("update public.mafia_knowledge_documents set status='published',updated_at=now() where id=:id"), {"id": doc_id})
            session.commit()
        await message.reply("✅ مطلب منتشر شد و در پاسخ‌گویی داخلی قابل استفاده است.")

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
    callback = _callback_proxy(message, "fl_new"); callback._from_text_command = True
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
    # A player row is mandatory because mafia_game_players.player_id has
    # a foreign-key constraint. Never swallow registration failures and then
    # attempt the membership insert.
    try:
        await app._ensure_player(message.from_user)
    except Exception:
        logging.exception("text join: app._ensure_player failed; using direct player upsert")
        try:
            from player_repository import PlayerRepository
            with PlayerRepository().SessionLocal() as session:
                session.execute(text("""
                    insert into public.mafia_players
                        (id, username, first_name, last_name, created_at, updated_at)
                    values (:id, :username, :first_name, :last_name, now(), now())
                    on conflict (id) do update set
                        username=coalesce(excluded.username, public.mafia_players.username),
                        first_name=coalesce(excluded.first_name, public.mafia_players.first_name),
                        last_name=coalesce(excluded.last_name, public.mafia_players.last_name),
                        updated_at=now()
                """), {
                    "id": uid,
                    "username": message.from_user.username,
                    "first_name": message.from_user.first_name,
                    "last_name": message.from_user.last_name,
                })
                session.commit()
        except Exception:
            logging.exception("text join: direct player upsert failed")
            await message.reply("❌ ثبت بازیکن انجام نشد. لطفاً دوباره «ورود» را ارسال کنید.")
            return
    try:
        app.runtime.state.lobby.join(game["id"], uid, seat, is_substitute=False)
    except Exception:
        logging.exception("text join: lobby membership insert failed")
        await message.reply("❌ ورود به بازی انجام نشد. ثبت بازیکن یا ظرفیت لابی با مشکل مواجه شد.")
        return
    refresh = getattr(app, "_refresh_final_lobby_from_text", None)
    if refresh:
        await refresh(message)
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
    freed_seat = current.get("seat")
    app.runtime.state.lobby.leave(game["id"], uid)
    if freed_seat is not None:
        try:
            app.runtime.state.lobby.promote_waiting(game["id"], int(freed_seat))
        except Exception:
            logging.exception("text leave: waiting promotion failed")
    refresh = getattr(app, "_refresh_final_lobby_from_text", None)
    if refresh:
        await refresh(message)
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


def _game(app, message):
    if message.chat.type not in {"group", "supergroup"}:
        return None
    return app.runtime.state.active_game(int(message.chat.id))


async def _manager(app, message, game=None) -> bool:
    game = game or _game(app, message)
    if game and int(message.from_user.id) == int(game.get("moderator_id") or 0):
        return True
    if message.chat.type not in {"group", "supergroup"}:
        return False
    try:
        return (await app.bot.get_chat_member(message.chat.id, int(message.from_user.id))).status in {"creator", "administrator"}
    except Exception:
        return False


async def _reply_target(message):
    reply = getattr(message, "reply_to_message", None)
    return getattr(reply, "from_user", None)


async def _simple_phase(message, app, phase: str):
    game = _game(app, message)
    if not game or not await _manager(app, message, game):
        await message.reply("⛔ فقط گرداننده یا مدیر گروه می‌تواند فاز را تغییر دهد.")
        return
    try:
        if phase == "night":
            snapshot = app.runtime.days.start_night(int(message.chat.id), extra={"phase_changed_by": int(message.from_user.id)})
        else:
            snapshot = app.runtime.days.start_new_day(int(message.chat.id), extra={
                "phase_changed_by": int(message.from_user.id),
                "turn_order": [],
                "current_turn_index": 0,
            })
        app._stable_day_active = False
        app._stable_day_ended = False
        app._stable_phase = "ended" if phase == "night" else "normal"
    except Exception as exc:
        logging.exception("text phase transition failed")
        await message.reply(f"❌ تغییر فاز انجام نشد: {type(exc).__name__}: {exc}")
        return
    title = "🌙 فاز شب" if phase == "night" else "☀️ فاز روز"
    await message.reply(f"✅ <b>{title}</b> فعال شد.", parse_mode="HTML")


async def _callback_answer(*args, **kwargs):
    return None


def _callback_proxy(message, data):
    return SimpleNamespace(message=message, from_user=message.from_user, data=data, answer=_callback_answer)


async def _start_round_text(message, app):
    game = _game(app, message)
    if not game or not await _manager(app, message, game):
        await message.reply("⛔ فقط گرداننده یا مدیر گروه می‌تواند دور را شروع کند.")
        return
    handler = getattr(app, "_stable_round_start_handler", None)
    if handler is None:
        # The stable engine keeps the callback owner internal; reproduce its
        # canonical entry state if the callback reference is unavailable.
        state = dict(game.get("state") or {})
        order = [int(r["seat"]) for r in app.runtime.state.games.list_players(game["id"])
                 if r.get("seat") is not None and str(r.get("status") or "active") not in {"removed","dead","finished","kicked"}]
        if not order:
            await message.reply("⚠️ بازیکن فعالی برای شروع دور وجود ندارد.")
            return
        app.turn_order = order
        app.current_turn_index = 0
        app._stable_day_active = True
        app._stable_day_ended = False
        state["turn_order"] = order
        app.runtime.state.games.update_game(game["id"], state=state, current_turn_index=0)
        await message.reply("✅ دور شروع شد.")
        return
    cb = _callback_proxy(message, "start_round")
    await handler(cb)


async def _next_text(message, app):
    game = _game(app, message)
    if not game:
        await message.reply("❌ بازی فعالی وجود ندارد.")
        return
    order = list(getattr(app, "turn_order", []) or [])
    if not order:
        order = [int(r["seat"]) for r in app.runtime.state.games.list_players(game["id"])
                 if r.get("seat") is not None and str(r.get("status") or "active") not in {"removed","dead","finished","kicked"}]
    if not order:
        await message.reply("⚠️ نوبتی برای ادامه وجود ندارد.")
        return
    idx = int(getattr(app, "current_turn_index", 0) or 0)
    seat = int(order[idx % len(order)])
    handler = getattr(app, "_stable_next_handler", None)
    if handler is None:
        await message.reply("⚠️ موتور نوبت در دسترس نیست.")
        return
    cb = _callback_proxy(message, f"next_{seat}")
    await handler(cb)


async def _end_game_text(message, app):
    game = _game(app, message)
    if not game or not await _manager(app, message, game):
        await message.reply("⛔ فقط گرداننده یا مدیر گروه می‌تواند بازی را تمام کند.")
        return
    if str(game.get("status") or "") not in {"running","paused","turn"}:
        await message.reply("❌ فقط بازی در حال اجرا قابل اتمام است.")
        return
    from runtime.game_end import _summary_text, _main_markup
    state = dict(game.get("state") or {})
    await message.reply(_summary_text(game), parse_mode="HTML",
                        reply_markup=_main_markup(int(game["id"]), state.get("game_result"),
                                                  bool((state.get("game_events") or {}).get("enabled"))))


async def _cancel_game_text(message, app):
    game = _game(app, message)
    if not game or not await _manager(app, message, game):
        await message.reply("⛔ فقط گرداننده یا مدیر گروه می‌تواند بازی را لغو کند.")
        return
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup(row_width=2).add(
        InlineKeyboardButton("🚫 بله، لغو شود", callback_data=f"cancel_text:{int(game['id'])}:confirm"),
        InlineKeyboardButton("⬅️ انصراف", callback_data=f"cancel_text:{int(game['id'])}:back"),
    )
    await message.reply(
        "⚠️ <b>لغو بازی</b>\n\nآیا مطمئن هستید که می‌خواهید بازی فعلی لغو شود؟\n"
        "این عملیات قابل بازگشت نیست.",
        parse_mode="HTML",
        reply_markup=kb,
    )

async def _player_state_action(message, app, action: str):
    game = _game(app, message)
    if not game or not await _manager(app, message, game):
        await message.reply("⛔ فقط گرداننده یا مدیر گروه.")
        return
    target = await _reply_target(message)
    if not target:
        await message.reply("❗ این دستور باید با ریپلای روی بازیکن استفاده شود.")
        return
    rows = app.runtime.state.games.list_players(game["id"])
    row = next((r for r in rows if int(r.get("player_id") or 0) == int(target.id)), None)
    if not row:
        await message.reply("❌ بازیکن پیدا نشد.")
        return
    state = dict(game.get("state") or {})
    uid = int(target.id)
    name = str(row.get("nickname") or row.get("first_name") or target.full_name or uid)
    if action == "warning":
        values = dict(state.get("warnings") or {}); values[str(uid)] = int(values.get(str(uid), 0)) + 1; state["warnings"] = values
        text = f"⚠️ تذکر ثبت شد: <b>{html.escape(name)}</b> — {values[str(uid)]}"
    elif action == "warning_remove":
        values = dict(state.get("warnings") or {}); values[str(uid)] = max(0, int(values.get(str(uid), 0)) - 1)
        if not values[str(uid)]: values.pop(str(uid), None)
        state["warnings"] = values; text = f"🗑 یک تذکر از {html.escape(name)} حذف شد."
    elif action == "kick":
        app.runtime.state.games.set_player_seat(game["id"], uid, None)
        app.runtime.state.games.set_player_status(game["id"], uid, "kicked")
        alive = getattr(app.runtime.state.games, "set_player_alive", None)
        if alive: alive(game["id"], uid, False)
        text = f"🦵 <b>{html.escape(name)}</b> از بازی حذف شد."
    elif action == "birthday":
        return_seats = dict(state.get("birthday_return_seats") or {})
        target_seat = row.get("seat")
        if target_seat is None:
            target_seat = return_seats.get(str(uid))
        occupied = {
            int(r.get("seat")) for r in rows
            if r.get("seat") is not None and int(r.get("player_id") or 0) != uid
            and str(r.get("status") or "active") not in {"removed", "dead", "finished", "kicked"}
        }
        if target_seat is None or int(target_seat) in occupied:
            await message.reply("⚠️ صندلی قبلی بازیکن برای بازگشت آزاد نیست.")
            return
        app.runtime.state.games.set_player_seat(game["id"], uid, int(target_seat))
        app.runtime.state.games.set_player_status(game["id"], uid, "active")
        alive = getattr(app.runtime.state.games, "set_player_alive", None)
        if alive: alive(game["id"], uid, True)
        return_seats.pop(str(uid), None)
        state["birthday_return_seats"] = return_seats
        text = f"🎂 <b>{html.escape(name)}</b> بازگردانده شد — صندلی <b>{int(target_seat):02d}</b>."
    elif action == "remove":
        seat = row.get("seat")
        return_seats = dict(state.get("birthday_return_seats") or {})
        if seat is not None:
            return_seats[str(uid)] = int(seat)
        state["birthday_return_seats"] = return_seats
        app.runtime.state.games.set_player_seat(game["id"], uid, None)
        app.runtime.state.games.set_player_status(game["id"], uid, "removed")
        text = f"🗑 <b>{html.escape(name)}</b> از بازی حذف شد."
    elif action == "extra":
        seats = set(int(x) for x in (getattr(app, "_gm_extra_next_round", set()) or set()))
        if row.get("seat") is None: await message.reply("❌ بازیکن صندلی فعال ندارد."); return
        seats.add(int(row["seat"])); app._gm_extra_next_round = seats; state["extra_turn_seats"] = sorted(seats)
        text = f"➕ ترن اضافه برای <b>{html.escape(name)}</b> ثبت شد."
    elif action in {"mute","unmute"}:
        seats = set(int(x) for x in (getattr(app, "_gm_muted_next_round", set()) or set()))
        if row.get("seat") is None: await message.reply("❌ بازیکن صندلی فعال ندارد."); return
        seat = int(row["seat"])
        if action == "mute":
            seats.add(seat); app._gm_muted_active = set(getattr(app, "_gm_muted_active", set()) or set()) | {seat}
            text = f"🔇 <b>{html.escape(name)}</b> ساکت شد."
        else:
            seats.discard(seat); app._gm_muted_active = set(getattr(app, "_gm_muted_active", set()) or set()); app._gm_muted_active.discard(seat)
            text = f"🔊 سکوت <b>{html.escape(name)}</b> حذف شد."
        app._gm_muted_next_round = seats; state["muted_next_round_seats"] = sorted(seats)
    else:
        return
    app.runtime.state.games.update_game(game["id"], state=state)
    await message.reply(text, parse_mode="HTML")


async def _challenge_toggle_text(message, app, enabled: bool):
    game = _game(app, message)
    if not game or not await _manager(app, message, game):
        await message.reply("⛔ فقط گرداننده یا مدیر گروه.")
        return
    if not hasattr(app, "challenge_enabled"): app.challenge_enabled = {}
    app.challenge_enabled[int(message.chat.id)] = bool(enabled)
    state = dict(game.get("state") or {}); state["challenge_enabled"] = bool(enabled)
    app.runtime.state.games.update_game(game["id"], state=state)
    await message.reply("⚔️ چالش آزاد شد." if enabled else "⚔️ چالش محدود شد.")


async def _attendance_text(message, app):
    game = _game(app, message)
    if not game or str(game.get("status") or "") != "lobby":
        await message.reply("❌ لابی فعالی وجود ندارد."); return
    rows = [r for r in app.runtime.state.games.list_players(game["id"])
            if r.get("seat") is not None and str(r.get("status") or "active") not in {"removed","dead","finished","kicked"}]
    ready = {int(x) for x in (dict(game.get("state") or {}).get("ready_players") or [])}
    lines = ["📢 <b>حاضری بازیکنان</b>", ""]
    for r in sorted(rows, key=lambda x:int(x.get("seat") or 999)):
        uid=int(r["player_id"]); name=str(r.get("nickname") or r.get("first_name") or r.get("username") or uid)
        lines.append(f"{int(r['seat']):02d}. {'🟢' if uid in ready else '⚪'} <a href='tg://user?id={uid}'>{html.escape(name)}</a>")
    lines.append(""); lines.append("🙋‍♂️ روی «آماده‌ام» بزنید.")
    kb = __import__("aiogram").types.InlineKeyboardMarkup(row_width=1).add(
        __import__("aiogram").types.InlineKeyboardButton("🙋‍♂️ آماده‌ام", callback_data=f"mgmt:{int(game['id'])}:attendance_ready")
    )
    await message.reply("\n".join(lines), parse_mode="HTML", reply_markup=kb)


async def _role_text(message, app):
    if message.chat.type not in {"private"}:
        await message.reply("ℹ️ «نقش من» را در پیوی ربات ارسال کنید."); return
    gid = int(getattr(app, "ALLOWED_GROUP_ID", 0) or 0)
    game = app.runtime.state.active_game(gid) if gid else None
    if not game:
        await message.reply("ℹ️ بازی فعالی پیدا نشد."); return
    rows = app.runtime.state.games.list_players(game["id"])
    row = next((r for r in rows if int(r.get("player_id") or 0) == int(message.from_user.id)), None)
    if not row or not row.get("role"):
        await message.reply("ℹ️ هنوز نقشی برای شما ثبت نشده است."); return

    event_no = game.get("event_number") or game.get("game_number") or game.get("number") or "—"
    scenario_name = str(game.get("scenario_name") or game.get("scenario") or "—")
    created = game.get("created_at") or game.get("started_at") or game.get("createdAt")
    date_text = str(created or "—")
    if "T" in date_text:
        date_text = date_text.replace("T", " ", 1).split("+", 1)[0].split("Z", 1)[0]
    moderator_id = game.get("moderator_id") or game.get("host_id") or game.get("owner_id") or game.get("created_by")
    moderator_name = game.get("moderator_name") or game.get("host_name") or game.get("owner_name") or game.get("moderator_username")
    if not moderator_name and moderator_id:
        moderator_row = next((r for r in rows if int(r.get("player_id") or 0) == int(moderator_id)), None)
        if moderator_row:
            moderator_name = moderator_row.get("nickname") or moderator_row.get("first_name") or moderator_row.get("username")
    moderator_name = str(moderator_name or "—")
    role = str(row.get("role") or row.get("role_name") or "—")
    side = str(row.get("side") or row.get("faction") or row.get("team") or "—")
    seat = row.get("seat")
    seat_text = str(int(seat)) if seat is not None else "—"
    player_name = str(row.get("nickname") or row.get("first_name") or message.from_user.full_name or "بازیکن")

    body = (
        "╔══════════════════════╗\n"
        "║ 🎭 <b>کارت نقش شما</b>\n"
        "╚══════════════════════╝\n\n"
        f"🎮 <b>شماره بازی:</b> <code>{html.escape(str(event_no))}</code>\n"
        f"📅 <b>تاریخ:</b> <code>{html.escape(date_text)}</code>\n"
        f"🎬 <b>سناریو:</b> <b>{html.escape(scenario_name)}</b>\n"
        f"🎙 <b>گرداننده:</b> <b>{html.escape(moderator_name)}</b>\n"
        f"👤 <b>بازیکن:</b> {html.escape(player_name)}\n"
        f"💺 <b>صندلی:</b> <b>{html.escape(seat_text)}</b>\n"
        f"🎭 <b>نقش:</b> <b>{html.escape(role)}</b>\n"
        f"🛡 <b>ساید:</b> <b>{html.escape(side)}</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "ℹ️ این اطلاعات مربوط به بازی جاری شماست.\n"
        "🔒 اطلاعات نقش سایر بازیکنان و اطلاعات مخفی بازی نمایش داده نمی‌شود."
    )
    await message.reply(body, parse_mode="HTML")


async def _lobby_text(message, app):
    if message.chat.type not in {"group", "supergroup"}:
        await message.reply("ℹ️ «لابی» را داخل گروه بازی ارسال کنید.")
        return
    game = app.runtime.state.active_game(int(message.chat.id))
    if not game or str(game.get("status") or "") != "lobby":
        await message.reply("❌ لابی فعالی وجود ندارد.")
        return
    render = getattr(app, "_render_production_lobby", None) or getattr(app, "_production_lobby_render", None)
    if not render:
        await message.reply("❌ سیستم لابی در دسترس نیست.")
        return
    ok = await render(int(message.chat.id), game)
    if not ok:
        await message.reply("❌ نمایش لابی انجام نشد.")

async def _nickname_direct(message, app, kind):
    # Canonical router delegates the full nickname implementation to the
    # existing command-surface v2 handler. Keeping one implementation avoids
    # divergent permission rules (especially for group administrators).
    dispatch = getattr(app, "_command_surface_v2_dispatch", None)
    if dispatch:
        await dispatch(message)
        return
    await message.reply("⚠️ بخش نام مستعار در دسترس نیست.")

async def _pv_text(message, app):
    if message.chat.type != "private":
        await message.reply("ℹ️ «پیوی» را در چت خصوصی ربات ارسال کنید."); return
    kb = __import__("aiogram").types.InlineKeyboardMarkup(row_width=2).add(
        __import__("aiogram").types.InlineKeyboardButton("🎭 نقش من", callback_data="pv:role"),
        __import__("aiogram").types.InlineKeyboardButton("📊 آمار", callback_data="pv:stats"),
        __import__("aiogram").types.InlineKeyboardButton("📚 دستورات", callback_data="pv:commands"),
        __import__("aiogram").types.InlineKeyboardButton("🤖 پنل دستیار", callback_data="aip:menu"),
    )
    await message.reply("👤 <b>پنل پیوی Mafia Nights</b>\n\nیکی از گزینه‌ها را انتخاب کنید:", parse_mode="HTML", reply_markup=kb)


async def _panel_text(message, app):
    if message.chat.type == "private":
        await _pv_text(message, app); return
    game = _game(app, message)
    if not game:
        await message.reply("ℹ️ بازی فعالی وجود ندارد."); return
    if not await _manager(app, message, game):
        await message.reply("⛔ فقط گرداننده یا مدیر گروه می‌تواند پنل را باز کند."); return
    from runtime.game_management import GameManagement
    await message.reply("⚙️ <b>مدیریت بازی</b>", parse_mode="HTML",
                        reply_markup=GameManagement(app).panel(int(game["id"])))


async def _seat_text(message, app):
    if message.chat.type not in {"group","supergroup"}:
        await message.reply("ℹ️ این دستور فقط در گروه بازی است."); return
    raw=(message.text or "").strip().replace("‌"," ")
    parts=raw.split()
    if len(parts)!=2 or not parts[1].isdigit():
        await message.reply("❗ نمونه صحیح: <code>صندلی 5</code>", parse_mode="HTML"); return
    game=_game(app,message)
    if not game or str(game.get("status") or "")!="lobby":
        await message.reply("❌ لابی فعالی وجود ندارد."); return
    uid=int(message.from_user.id); target=int(parts[1])
    from repositories.scenario_repository import ScenarioRepository
    scenario=ScenarioRepository().get_by_id(int(game.get("scenario_id") or 0))
    cap=len((scenario or {}).get("roles") or [])
    if target<1 or target>cap:
        await message.reply("❌ شماره صندلی نامعتبر است."); return
    rows=app.runtime.state.games.list_players(game["id"])
    current=next((r for r in rows if int(r.get("player_id") or 0)==uid and str(r.get("status") or "") not in {"removed","finished","kicked"}),None)
    if not current:
        await message.reply("❗ ابتدا «ورود» را بزنید."); return
    occupied={int(r["seat"]):int(r["player_id"]) for r in rows if r.get("seat") is not None and str(r.get("status") or "") not in {"removed","finished","kicked"}}
    if target in occupied and occupied[target]!=uid:
        await message.reply("❌ این صندلی قبلاً گرفته شده است."); return
    app.runtime.state.lobby.assign_seat(game["id"],uid,target)
    await message.reply(f"✅ صندلی شما به <b>{target}</b> تغییر کرد.",parse_mode="HTML")


async def _reserve_text(message, app, cancel=False):
    if message.chat.type not in {"group", "supergroup"}:
        await message.reply("ℹ️ این دستور فقط داخل گروه بازی است."); return
    game = _game(app, message)
    if not game or str(game.get("status") or "") != "lobby":
        await message.reply("❌ لابی فعالی وجود ندارد."); return
    uid = int(message.from_user.id)
    rows = app.runtime.state.games.list_players(game["id"])
    current = next(
        (r for r in rows if int(r.get("player_id") or 0) == uid
         and str(r.get("status") or "") not in {"removed", "finished", "kicked"}),
        None,
    )
    if cancel:
        if current and current.get("seat") is None and str(current.get("status") or "") in {"waiting", "substitute"}:
            app.runtime.state.lobby.leave(game["id"], uid)
            refresh = getattr(app, "_refresh_final_lobby_from_text", None)
            if refresh:
                await refresh(message)
            await message.reply("✅ رزرو شما لغو شد.")
        else:
            await message.reply("ℹ️ رزرو فعالی برای شما ثبت نشده است.")
        return

    from repositories.scenario_repository import ScenarioRepository
    scenario = ScenarioRepository().get_by_id(int(game.get("scenario_id") or 0))
    cap = len((scenario or {}).get("roles") or [])
    active = [
        r for r in rows
        if r.get("seat") is not None
        and str(r.get("status") or "") not in {"removed", "dead", "finished", "kicked"}
    ]
    if current and current.get("seat") is not None:
        await message.reply("ℹ️ شما داخل بازی هستید."); return
    if current and current.get("seat") is None and str(current.get("status") or "") in {"waiting", "substitute"}:
        await message.reply("ℹ️ شما از قبل در لیست رزرو هستید."); return
    if len(active) < cap:
        await message.reply("ℹ️ رزرو پس از تکمیل ظرفیت فعال می‌شود."); return

    try:
        await app._ensure_player(message.from_user)
    except Exception:
        pass
    try:
        app.runtime.state.lobby.join(game["id"], uid, None, is_substitute=True)
    except Exception:
        logging.exception("text reserve failed")
        await message.reply("❌ ثبت رزرو انجام نشد. احتمالاً رزرو شما از قبل ثبت شده یا اطلاعات بازیکن تکراری است.")
        return
    refresh = getattr(app, "_refresh_final_lobby_from_text", None)
    if refresh:
        await refresh(message)
    await message.reply("🎟 رزرو شما با موفقیت ثبت شد.")


async def _sub_text(message, app):
    game=_game(app,message)
    if not game or str(game.get("status") or "")!="lobby":
        await message.reply("❌ لابی فعالی وجود ندارد."); return
    target=(await _reply_target(message)) or message.from_user
    rows=app.runtime.state.games.list_players(game["id"])
    if any(int(r.get("player_id") or 0)==int(target.id) and r.get("seat") is None and str(r.get("status") or "")=="waiting" for r in rows):
        await message.reply("ℹ️ این کاربر قبلاً در لیست جایگزین است."); return
    await app._ensure_player(target)
    app.runtime.state.lobby.join(game["id"],int(target.id),None,is_substitute=True)
    await message.reply(f"🔄 <b>{html.escape(target.full_name)}</b> به لیست جایگزین اضافه شد.",parse_mode="HTML")


async def _challenge_text(message, app):
    game=_game(app,message)
    if not game:
        await message.reply("❌ بازی فعالی وجود ندارد."); return
    if not getattr(app,"challenge_enabled",{}).get(int(message.chat.id),True):
        await message.reply("⚔️ چالش در حال حاضر محدود است."); return
    target=await _reply_target(message)
    if not target:
        await message.reply("❗ برای چالش روی پیام بازیکن ریپلای کنید."); return
    rows=app.runtime.state.games.list_players(game["id"])
    a=next((r for r in rows if int(r.get("player_id") or 0)==int(message.from_user.id) and r.get("seat") is not None),None)
    b=next((r for r in rows if int(r.get("player_id") or 0)==int(target.id) and r.get("seat") is not None),None)
    if not a or not b or int(a["player_id"])==int(b["player_id"]):
        await message.reply("❌ هر دو نفر باید بازیکن فعال باشند."); return
    state=dict(game.get("state") or {}); pending=dict(state.get("challenge_requests") or {})
    bucket=dict(pending.get(str(b["seat"])) or {}); bucket[str(message.from_user.id)]="pending"; pending[str(b["seat"])]=bucket
    state["challenge_requests"]=pending; app.runtime.state.games.update_game(game["id"],state=state)
    await message.reply(f"⚔️ <b>{html.escape(str(a.get('nickname') or message.from_user.full_name))}</b> برای <b>{html.escape(str(b.get('nickname') or target.full_name))}</b> درخواست چالش داد.",parse_mode="HTML")


async def _legacy_command_adapter(name, message, app):
    # Keep the already-working assistant/tag surfaces available without
    # creating a second text-command registration surface.
    await run_command(name, message, app)

async def _nickname_set_text(message: types.Message, app: Any) -> None:
    if message.chat.type not in {"group", "supergroup"}:
        await message.reply("⚠️ این دستور فقط داخل گروه قابل استفاده است.")
        return
    try:
        status = (await app.bot.get_chat_member(message.chat.id, int(message.from_user.id))).status
    except Exception:
        status = "left"
    if status not in {"creator", "administrator"} and int(message.from_user.id) != int(getattr(app, "moderator_id", 0) or 0):
        await message.reply("⛔ فقط گرداننده یا مدیر گروه می‌تواند نام مستعار ثبت کند.")
        return
    target = message.reply_to_message.from_user if message.reply_to_message else None
    if not target:
        await message.reply("❗ برای ثبت مستعار باید روی پیام کاربر ریپلای کنید.\nمثال: «تنظیم مستعار علی» همراه با ریپلای")
        return
    raw = (message.text or "").strip().replace("‌", " ")
    parts = raw.split(None, 2)
    nickname = parts[2].strip() if len(parts) >= 3 else ""
    if not nickname:
        await message.reply("❗ نام مستعار را بعد از دستور وارد کنید.\nمثال: تنظیم مستعار علی")
        return
    from player_repository import PlayerRepository
    repo = PlayerRepository()
    repo.upsert(target.id, target.full_name, target.username)
    if not repo.set_nickname(target.id, nickname):
        await message.reply("❌ ثبت نام مستعار انجام نشد.")
        return
    await message.reply(
        f"✅ نام مستعار <b>{html.escape(nickname)}</b> برای <a href='tg://user?id={int(target.id)}'>{html.escape(target.full_name or str(target.id))}</a> ثبت شد.",
        parse_mode="HTML",
    )


async def _nickname_del_text(message: types.Message, app: Any) -> None:
    if message.chat.type not in {"group", "supergroup"}:
        await message.reply("⚠️ این دستور فقط داخل گروه قابل استفاده است.")
        return
    target = message.reply_to_message.from_user if message.reply_to_message else None
    if not target:
        await message.reply("❗ روی پیام کاربر ریپلای کنید.")
        return
    from player_repository import PlayerRepository
    if not PlayerRepository().delete_nickname(target.id):
        await message.reply("ℹ️ نام مستعاری برای این کاربر ثبت نشده است.")
        return
    await message.reply("🗑 نام مستعار حذف شد.")


async def _nickname_get_text(message: types.Message, app: Any) -> None:
    if message.chat.type not in {"group", "supergroup"}:
        await message.reply("⚠️ این دستور فقط داخل گروه قابل استفاده است.")
        return
    target = message.reply_to_message.from_user if message.reply_to_message else message.from_user
    from player_repository import PlayerRepository
    row = PlayerRepository().get(target.id)
    nickname = (row or {}).get("nickname")
    await message.reply(
        f"📛 نام مستعار: <b>{html.escape(str(nickname))}</b>" if nickname else "ℹ️ نام مستعاری برای این کاربر ثبت نشده است.",
        parse_mode="HTML",
    )


async def _nickname_list_text(message: types.Message, app: Any) -> None:
    if message.chat.type not in {"group", "supergroup"}:
        await message.reply("⚠️ این دستور فقط داخل گروه قابل استفاده است.")
        return
    try:
        status = (await app.bot.get_chat_member(message.chat.id, int(message.from_user.id))).status
    except Exception:
        status = "left"
    if status not in {"creator", "administrator"} and int(message.from_user.id) != int(getattr(app, "moderator_id", 0) or 0):
        await message.reply("⛔ فقط مدیر گروه.")
        return
    from player_repository import PlayerRepository
    rows = PlayerRepository().all_nicknames()
    if not rows:
        await message.reply("📛 نام مستعاری ثبت نشده است.")
        return
    lines = ["📛 <b>لیست نام‌های مستعار</b>", ""]
    lines.extend(f"• <a href='tg://user?id={uid}'>{html.escape(str(nickname))}</a> — <code>{uid}</code>" for uid, nickname in rows.items())
    await message.reply("\n".join(lines), parse_mode="HTML")


async def run_command(name: str, message: types.Message, app: Any) -> None:
    direct = {
        "pv": _pv_text, "role": _role_text, "panel": _panel_text,
        "start_round": _start_round_text, "end_game": _end_game_text,
        "night": lambda m,a: _simple_phase(m,a,"night"), "day": lambda m,a: _simple_phase(m,a,"day"),
        "warning": lambda m,a: _player_state_action(m,a,"warning"),
        "warning_remove": lambda m,a: _player_state_action(m,a,"warning_remove"),
        "kick": lambda m,a: _player_state_action(m,a,"kick"),
        "mute": lambda m,a: _player_state_action(m,a,"mute"),
        "unmute": lambda m,a: _player_state_action(m,a,"unmute"),
        "extra": lambda m,a: _player_state_action(m,a,"extra"),
        "birthday": lambda m,a: _player_state_action(m,a,"birthday"),
        "remove": lambda m,a: _player_state_action(m,a,"remove"),
        "cancel_game": _cancel_game_text,
        "challenge_limited": lambda m,a: _challenge_toggle_text(m,a,False),
        "challenge_free": lambda m,a: _challenge_toggle_text(m,a,True),
        "attendance": _attendance_text,
        "seat": _seat_text,
        "reserve": _reserve_text,
        "unreserve": lambda m,a: _reserve_text(m,a,True),
        "sub": _sub_text,
        "challenge": _challenge_text,
        "next": _next_text,
        "newgame": _newgame,
        "join": _join,
        "leave": _leave,
        "chatlock": lambda m,a: _set_lock(m,a,"chat_lock",True,"قفل چت"),
        "chatunlock": lambda m,a: _set_lock(m,a,"chat_lock",False,"قفل چت"),
        "nightlock": lambda m,a: _set_lock(m,a,"night_lock",True,"قفل شب"),
        "nightunlock": lambda m,a: _set_lock(m,a,"night_lock",False,"قفل شب"),
        "turnlock": lambda m,a: _set_lock(m,a,"turn_lock",True,"قفل نوبت"),
        "turnunlock": lambda m,a: _set_lock(m,a,"turn_lock",False,"قفل نوبت"),
        "commands": cmd_commands, "help": cmd_commands,
        "ask": lambda m,a: __import__("runtime.knowledge_assistant", fromlist=["answer"]).answer(m,a,(m.text or "").split(" ",1)[1] if " " in (m.text or "") else ""),
        "ai_on": lambda m,a: _ai_control(m,a,"on"), "ai_off": lambda m,a: _ai_control(m,a,"off"),
        "ai_status": lambda m,a: _ai_control(m,a,"status"), "ai_key": _ai_key,
        "ai_panel": _ai_panel_text,\n        "nickname_set": _nickname_set_text, "nickname_del": _nickname_del_text, "nickname_get": _nickname_get_text, "nickname_list": _nickname_list_text,
        "kb_list": lambda m,a: _kb_control(m,a,"list"), "kb_add": lambda m,a: _kb_control(m,a,"add"),
        "kb_publish": lambda m,a: _kb_control(m,a,"publish"),
        "tag_all": cmd_tag_all, "tag_admins": cmd_tag_admins, "tag_list": cmd_tag_players,
    }
    if name in {"profile","ranking","stats"}:
        stats = getattr(app,"_user_stats_instance",None)
        if stats is not None:
            uid=int(message.reply_to_message.from_user.id if message.reply_to_message else message.from_user.id)
            gid=int(message.chat.id) if message.chat.type in {"group","supergroup"} else None
            if name=="profile": await stats.show_profile(message,uid,gid)
            elif name=="ranking": await stats.show_ranking(message,gid)
            else: await stats.show_stats(message,uid,gid)
        else: await message.reply("⚠️ بخش آمار در دسترس نیست.")
        return
    handler=direct.get(name)
    if handler:
        await handler(message,app)
        return
    # Legacy/extended command surface remains available through the same
    # canonical webhook route. This is deliberately a fallback, not a second
    # message-handler registration.
    dispatch = getattr(app, "_command_surface_v2_dispatch", None)
    if dispatch:
        await dispatch(message)


def register_commands(app: Any) -> bool:
    dp = getattr(app, "dp", None)
    if dp is None or getattr(app, "_canonical_text_commands_installed", False):
        return False

    async def _cancel_callback_allowed(callback, game) -> bool:
        if not game:
            return False
        uid = int(callback.from_user.id)
        if uid == int(game.get("moderator_id") or 0):
            return True
        try:
            return (await app.bot.get_chat_member(int(callback.message.chat.id), uid)).status in {"creator", "administrator"}
        except Exception:
            return False

    async def _cancel_text_confirm(callback):
        parts = str(callback.data or "").split(":")
        if len(parts) != 3 or parts[0] != "cancel_text" or parts[2] != "confirm":
            return
        gid = int(callback.message.chat.id)
        game = _game(app, callback.message)
        if not game or int(game.get("id") or 0) != int(parts[1]) or not await _cancel_callback_allowed(callback, game):
            await callback.answer("⛔ دسترسی ندارید یا بازی فعال نیست.", show_alert=True)
            return
        status = str(game.get("status") or "")
        if status not in {"lobby", "running", "paused", "turn"}:
            await callback.answer("ℹ️ این بازی دیگر قابل لغو نیست.", show_alert=True)
            return
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        state = dict(game.get("state") or {})
        state.update({
            "cancelled": True,
            "cancel_reason": "text_command_confirmed",
            "cancelled_at": now.isoformat(),
            "cancelled_from_status": status,
        })
        ok = app.runtime.state.games.update_game(
            game["id"], status="cancelled", event_number=0, state=state, finished_at=now
        )
        if not ok:
            await callback.answer("❌ لغو بازی انجام نشد.", show_alert=True)
            return
        for owner, attr in (
            (getattr(app, "ui", None), "turn_timer_task"),
            (getattr(app, "ui", None), "voting_timer_task"),
            (getattr(app, "ui", None), "day_timer_task"),
            (app, "_voting_task"),
        ):
            task = getattr(owner, attr, None) if owner is not None else None
            if task is not None and hasattr(task, "done") and not task.done():
                try:
                    task.cancel()
                except Exception:
                    logging.exception("cancel_text_confirm: failed to cancel task %s", attr)
        lobby_message_id = state.get("lobby_message_id")
        if lobby_message_id:
            try:
                await app.bot.edit_message_text(
                    "🚫 <b>این بازی لغو شد.</b>\n\nاطلاعات بازی در بایگانی بازی‌های لغوشده نگهداری شد.",
                    gid, int(lobby_message_id), parse_mode="HTML", reply_markup=None,
                )
            except Exception:
                logging.info("cancel_text_confirm: lobby message edit failed")
        await callback.message.edit_text(
            "🚫 <b>بازی لغو شد.</b>\n\nاین بازی در تاریخچه بازی‌های انجام‌شده ثبت نمی‌شود و امتیاز و سابقه بازیکنان تغییر نمی‌کند.",
            parse_mode="HTML",
        )
        await callback.answer("🚫 بازی لغو شد.")

    async def _cancel_text_back(callback):
        parts = str(callback.data or "").split(":")
        if len(parts) != 3 or parts[0] != "cancel_text" or parts[2] != "back":
            return
        await callback.message.edit_text("ℹ️ لغو بازی انجام نشد.")
        await callback.answer("لغو شد.")

    dp.register_callback_query_handler(
        _cancel_text_confirm,
        lambda c: str(c.data or "").startswith("cancel_text:") and str(c.data or "").endswith(":confirm"),
        state="*",
    )
    dp.register_callback_query_handler(
        _cancel_text_back,
        lambda c: str(c.data or "").startswith("cancel_text:") and str(c.data or "").endswith(":back"),
        state="*",
    )

    @dp.message_handler(lambda m: bool(resolve_command(getattr(m, "text", None))), state="*")
    async def handle_text_commands(message: types.Message):
        name = resolve_command(message.text)
        if not name:
            return
        await run_command(name, message, app)
        raise CancelHandler()

    async def _register_menu():
        try:
            from aiogram.types import BotCommand, BotCommandScopeChat
            group_commands = [
                BotCommand("newgame", "بازی جدید"),
                BotCommand("join", "ورود"),
                BotCommand("leave", "خروج"),
                BotCommand("sub", "جایگزین"),
                BotCommand("attendance", "حاضری"),
                BotCommand("management", "مدیریت"),
                BotCommand("lobby", "لابی"),
                BotCommand("nickname_set", "تنظیم مستعار"),
                BotCommand("nickname_del", "حذف مستعار"),
                BotCommand("nickname_get", "نام مستعار"),
                BotCommand("nickname_list", "لیست مستعار"),
                BotCommand("reserve", "رزرو"),
                BotCommand("unreserve", "لغو رزرو"),
                BotCommand("seat", "صندلی عدد"),
                BotCommand("challenge", "چالش"),
                BotCommand("start_round", "شروع دور"),
                BotCommand("end", "اتمام بازی"),
                BotCommand("night", "فاز شب"),
                BotCommand("day", "فاز روز"),
                BotCommand("warning", "تذکر"),
                BotCommand("warning_remove", "حذف تذکر"),
                BotCommand("kick", "کیک"),
                BotCommand("mute", "سکوت"),
                BotCommand("unmute", "حذف سکوت"),
                BotCommand("extra", "ترن اضافه"),
                BotCommand("birthday", "تولد"),
                BotCommand("remove", "حذف بازیکن"),
                BotCommand("cancel_game", "لغو بازی"),
                BotCommand("challenge_limited", "چالش محدود"),
                BotCommand("challenge_free", "چالش آزاد"),
                BotCommand("chatlock", "قفل چت"),
                BotCommand("nightlock", "قفل شب"),
                BotCommand("turnlock", "قفل نوبت"),
                BotCommand("next", "نکست"),
                BotCommand("role", "نقش من"),
                BotCommand("panel", "پنل"),
                BotCommand("stats", "آمار"),
                BotCommand("rank", "رتبه"),
                BotCommand("commands", "دستورات"),
                BotCommand("ask", "سؤال از دستیار"),
                BotCommand("mafia", "سؤال از دستیار"),
            ]
            gid = int(getattr(app, "ALLOWED_GROUP_ID", 0) or 0)
            if gid:
                await app.bot.set_my_commands(group_commands, scope=BotCommandScopeChat(chat_id=gid))
            await app.bot.set_my_commands([
                BotCommand("start", "منوی اصلی"),
                BotCommand("pv", "پنل پیوی"),
                BotCommand("role", "نقش من"),
                BotCommand("panel", "پنل"),
                BotCommand("stats", "آمار"),
                BotCommand("commands", "دستورات"),
            ])
        except Exception:
            logging.exception("Canonical Telegram command menu registration failed")

    app._register_telegram_commands = _register_menu
    app._canonical_text_commands_installed = True
    logging.info("CANONICAL TEXT COMMAND AUTHORITY installed: single registry")
    return True

