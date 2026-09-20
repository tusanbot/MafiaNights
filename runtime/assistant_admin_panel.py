"""Private administration panel for the Mafia Nights knowledge assistant."""
from __future__ import annotations

import html
import os
import logging
from typing import Any

from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import text

from repositories.knowledge_repository import KnowledgeRepository


class AssistantAdminStates(StatesGroup):
    waiting_title = State()
    waiting_content = State()
    waiting_scenario = State()
    waiting_role = State()
    waiting_source = State()
    waiting_group_key = State()


class AssistantAdminPanel:
    def __init__(self, app: Any):
        self.app = app

    @staticmethod
    def _group_id() -> int | None:
        raw = os.getenv("AI_PRIMARY_GROUP_ID") or os.getenv("ALLOWED_GROUP_ID") or ""
        try:
            return int(raw)
        except Exception:
            return None

    async def _authorized(self, user_id: int) -> bool:
        group_id = self._group_id()
        if not group_id:
            return False
        try:
            member = await self.app.bot.get_chat_member(group_id, int(user_id))
            return str(getattr(member, "status", "")) in {"creator", "administrator"}
        except Exception:
            logging.exception("assistant admin: group-admin authorization check failed")
            return False

    async def _guard(self, message_or_callback: Any) -> bool:
        uid = int(message_or_callback.from_user.id)
        if await self._authorized(uid):
            return True
        target = getattr(message_or_callback, "message", message_or_callback)
        await target.answer("⛔ این پنل فقط برای مدیر/گرداننده مجاز گروه فعال است.")
        return False

    def _repo(self):
        KnowledgeRepository.ensure_schema()
        return KnowledgeRepository()

    @staticmethod
    def _menu() -> InlineKeyboardMarkup:
        kb = InlineKeyboardMarkup(row_width=2)
        kb.add(
            InlineKeyboardButton("📚 پایگاه دانش", callback_data="aip:kb"),
            InlineKeyboardButton("➕ افزودن اطلاعات", callback_data="aip:add"),
            InlineKeyboardButton("🤖 تنظیمات AI", callback_data="aip:ai"),
            InlineKeyboardButton("🔑 کلید AI گروه", callback_data="aip:groupkey"),
            InlineKeyboardButton("📊 وضعیت", callback_data="aip:status"),
            InlineKeyboardButton("❓ راهنمای افزودن مطلب", callback_data="aip:guide"),
        )
        return kb

    @staticmethod
    def _back() -> InlineKeyboardMarkup:
        kb = InlineKeyboardMarkup(row_width=1)
        kb.add(InlineKeyboardButton("⬅️ پنل دستیار", callback_data="aip:menu"))
        return kb

    async def open(self, message: types.Message):
        if message.chat.type != "private":
            await message.reply("⚠️ پنل مدیریت دستیار فقط در پیوی مدیران گروه قابل استفاده است.")
            return
        if not await self._guard(message):
            return
        await message.answer(
            "🤖 <b>پنل مدیریت دستیار Mafia Nights</b>\n\n"
            "از این بخش می‌توانید پایگاه دانش، تنظیمات هوش مصنوعی و کلید مشترک گروه برای درخواست‌های پیوی را مدیریت کنید.",
            reply_markup=self._menu(), parse_mode="HTML",
        )

    async def menu(self, callback: types.CallbackQuery):
        if not await self._guard(callback):
            await callback.answer()
            return
        await callback.message.edit_text(
            "🤖 <b>پنل مدیریت دستیار Mafia Nights</b>\n\nیک بخش را انتخاب کنید:",
            reply_markup=self._menu(), parse_mode="HTML",
        )
        await callback.answer()

    async def kb(self, callback: types.CallbackQuery):
        if not await self._guard(callback):
            await callback.answer()
            return
        repo = self._repo()
        with repo.SessionLocal() as session:
            rows = session.execute(text("""
                select id,title,scope,status,scenario_name,role_name
                from public.mafia_knowledge_documents
                where is_active=true
                order by updated_at desc limit 12
            """)).mappings().all()
        lines = ["📚 <b>پایگاه دانش</b>", "", f"تعداد نمایش‌داده‌شده: <b>{len(rows)}</b>", ""]
        kb = InlineKeyboardMarkup(row_width=1)
        for r in rows:
            scope = {"scenario":"سناریو","role":"نقش","tutorial":"آموزش","faq":"FAQ","global":"عمومی"}.get(str(r["scope"]), str(r["scope"]))
            lines.append(f"• <code>{r['id']}</code> — {html.escape(str(r['title']))} — {scope} — {r['status']}")
            kb.add(InlineKeyboardButton(
                f"📄 {str(r['title'])[:35]}",
                callback_data=f"aip:doc:{int(r['id'])}",
            ))
        kb.row(InlineKeyboardButton("➕ افزودن اطلاعات", callback_data="aip:add"))
        kb.row(InlineKeyboardButton("⬅️ پنل دستیار", callback_data="aip:menu"))
        await callback.message.edit_text("\n".join(lines), reply_markup=kb, parse_mode="HTML")
        await callback.answer()

    async def doc(self, callback: types.CallbackQuery):
        if not await self._guard(callback):
            await callback.answer()
            return
        try:
            doc_id = int(str(callback.data).split(":")[2])
        except Exception:
            await callback.answer("شناسه نامعتبر.", show_alert=True); return
        repo = self._repo()
        with repo.SessionLocal() as session:
            row = session.execute(text("""
                select id,title,content,scope,status,scenario_name,role_name,
                       source_type,source_url,source_title,confidence,is_active
                from public.mafia_knowledge_documents where id=:id
            """), {"id": doc_id}).mappings().first()
        if not row:
            await callback.answer("مطلب پیدا نشد.", show_alert=True); return
        content = str(row["content"] or "")
        if len(content) > 1800:
            content = content[:1800] + "…"
        body = (
            f"📄 <b>{html.escape(str(row['title']))}</b>\n\n"
            f"نوع: <b>{html.escape(str(row['scope']))}</b>\n"
            f"وضعیت: <b>{html.escape(str(row['status']))}</b>\n"
            f"سناریو: <b>{html.escape(str(row['scenario_name'] or '—'))}</b>\n"
            f"نقش: <b>{html.escape(str(row['role_name'] or '—'))}</b>\n"
            f"منبع: <b>{html.escape(str(row['source_title'] or row['source_type'] or '—'))}</b>\n\n"
            f"{html.escape(content)}"
        )
        kb = InlineKeyboardMarkup(row_width=2)
        if str(row["status"]) not in {"published","verified"}:
            kb.add(InlineKeyboardButton("✅ انتشار", callback_data=f"aip:publish:{doc_id}"))
        kb.add(InlineKeyboardButton("🗑 غیرفعال‌کردن", callback_data=f"aip:disable:{doc_id}"))
        kb.add(InlineKeyboardButton("⬅️ پایگاه دانش", callback_data="aip:kb"))
        await callback.message.edit_text(body, reply_markup=kb, parse_mode="HTML")
        await callback.answer()

    async def publish(self, callback: types.CallbackQuery):
        if not await self._guard(callback):
            await callback.answer(); return
        doc_id = int(str(callback.data).split(":")[2])
        with self._repo().SessionLocal() as session:
            session.execute(text("update public.mafia_knowledge_documents set status='published',updated_at=now() where id=:id"), {"id":doc_id})
            session.commit()
        await callback.answer("✅ مطلب منتشر شد.")
        await self.doc(callback)

    async def disable(self, callback: types.CallbackQuery):
        if not await self._guard(callback):
            await callback.answer(); return
        doc_id = int(str(callback.data).split(":")[2])
        with self._repo().SessionLocal() as session:
            session.execute(text("update public.mafia_knowledge_documents set is_active=false,updated_at=now() where id=:id"), {"id":doc_id})
            session.commit()
        await callback.answer("🗑 مطلب غیرفعال شد.")
        await self.kb(callback)

    async def guide(self, callback: types.CallbackQuery):
        if not await self._guard(callback):
            await callback.answer(); return
        kb = InlineKeyboardMarkup(row_width=1)
        kb.add(InlineKeyboardButton("➕ شروع افزودن مطلب", callback_data="aip:add"))
        kb.add(InlineKeyboardButton("⬅️ پنل دستیار", callback_data="aip:menu"))
        await callback.message.edit_text(
            "❓ <b>راهنمای افزودن مطلب</b>\n\n"
            "• <b>عمومی:</b> اطلاعات و قوانین مشترک\n"
            "• <b>سناریو:</b> مطلب مخصوص یک سناریو\n"
            "• <b>نقش:</b> مطلب مربوط به یک نقش\n"
            "• <b>آموزش:</b> راهنمای انجام یک کار\n"
            "• <b>FAQ:</b> پرسش و پاسخ پرتکرار\n\n"
            "مراحل: ۱) عنوان ۲) متن کامل ۳) سناریو/نقش در صورت نیاز ۴) منبع.\n"
            "اگر منبع ندارید فقط «ندارد» بنویسید.\n"
            "مطلب ابتدا پیش‌نویس است و برای استفاده باید منتشر شود.",
            reply_markup=kb, parse_mode="HTML"
        )
        await callback.answer()

    async def add_start(self, callback: types.CallbackQuery, state: FSMContext):
        if not await self._guard(callback):
            await callback.answer(); return
        await state.finish()
        await state.update_data(scope="global")
        kb = InlineKeyboardMarkup(row_width=2)
        for value,label in (("global","عمومی"),("scenario","سناریو"),("role","نقش"),("tutorial","آموزش"),("faq","FAQ")):
            kb.add(InlineKeyboardButton(label, callback_data=f"aip:scope:{value}"))
        kb.add(InlineKeyboardButton("❌ لغو", callback_data="aip:menu"))
        await callback.message.edit_text("➕ <b>افزودن اطلاعات</b>\n\nنوع مطلب را انتخاب کنید:", reply_markup=kb, parse_mode="HTML")
        await callback.answer()

    async def scope(self, callback: types.CallbackQuery, state: FSMContext):
        if not await self._guard(callback):
            await callback.answer(); return
        value = str(callback.data).split(":")[2]
        await state.update_data(scope=value)
        await AssistantAdminStates.waiting_title.set()
        await callback.message.edit_text("✏️ عنوان مطلب را ارسال کنید.\n\nبرای لغو: /cancel")
        await callback.answer()

    async def title(self, message: types.Message, state: FSMContext):
        await state.update_data(title=(message.text or "").strip())
        await AssistantAdminStates.waiting_content.set()
        await message.answer("📝 متن کامل مطلب را ارسال کنید.")

    async def content(self, message: types.Message, state: FSMContext):
        await state.update_data(content=(message.text or "").strip())
        data = await state.get_data()
        if data.get("scope") in {"scenario","role"}:
            await AssistantAdminStates.waiting_scenario.set()
            await message.answer("🎭 نام سناریو را ارسال کنید.")
        else:
            await AssistantAdminStates.waiting_source.set()
            await message.answer("🔗 آدرس منبع را ارسال کنید؛ اگر منبع داخلی است «ندارد» بنویسید.")

    async def scenario(self, message: types.Message, state: FSMContext):
        await state.update_data(scenario=(message.text or "").strip())
        data = await state.get_data()
        if data.get("scope") == "role":
            await AssistantAdminStates.waiting_role.set()
            await message.answer("🎭 نام نقش را ارسال کنید.")
        else:
            await AssistantAdminStates.waiting_source.set()
            await message.answer("🔗 آدرس منبع را ارسال کنید؛ اگر منبع داخلی است «ندارد» بنویسید.")

    async def role(self, message: types.Message, state: FSMContext):
        await state.update_data(role=(message.text or "").strip())
        await AssistantAdminStates.waiting_source.set()
        await message.answer("🔗 آدرس منبع را ارسال کنید؛ اگر منبع داخلی است «ندارد» بنویسید.")

    async def source(self, message: types.Message, state: FSMContext):
        data = await state.get_data()
        url = (message.text or "").strip()
        if url in {"", "ندارد", "-", "none"}:
            url = None
        scope = str(data.get("scope") or "global")
        try:
            doc_id = self._repo().add_document(
                title=str(data.get("title") or "بدون عنوان"),
                content=str(data.get("content") or ""),
                scope=scope,
                scenario_name=data.get("scenario") or None,
                role_name=data.get("role") or None,
                status="draft",
                source_type="web" if url else "internal",
                source_url=url,
                confidence="unverified",
            )
            await state.finish()
            await message.answer(
                f"✅ مطلب با شناسه <code>{doc_id}</code> به‌صورت پیش‌نویس ثبت شد.\n"
                "برای استفاده در پاسخ‌های داخلی، آن را از بخش پایگاه دانش منتشر کنید.",
                reply_markup=self._menu(), parse_mode="HTML",
            )
        except Exception:
            logging.exception("assistant admin: add knowledge failed")
            await state.finish()
            await message.answer("❌ ثبت مطلب انجام نشد.", reply_markup=self._menu())

    def _settings_row(self):
        with self._repo().SessionLocal() as session:
            return session.execute(text("""
                select enabled,provider,model,web_search_enabled,
                       private_enabled,private_provider,private_model,
                       private_web_search_enabled,
                       (api_key_ciphertext is not null) as has_group_key,
                       (private_api_key_ciphertext is not null) as has_private_key
                from public.mafia_ai_settings where group_id=:gid
            """), {"gid": self._group_id()}).mappings().first()

    async def status(self, callback):
        if not await self._guard(callback):
            await callback.answer(); return
        row = self._settings_row()
        if not row:
            body = "📊 <b>وضعیت دستیار</b>\n\nهنوز تنظیماتی ثبت نشده است."
        else:
            body = (
                "📊 <b>وضعیت دستیار</b>\n\n"
                f"🤖 AI گروه: <b>{'فعال' if row['enabled'] else 'غیرفعال'}</b>\n"
                f"🧠 مدل گروه: <code>{html.escape(str(row['model'] or 'پیش‌فرض'))}</code>\n"
                f"🔑 کلید گروه: <b>{'ثبت شده' if row['has_group_key'] else 'ثبت نشده'}</b>\n"
                f"🔐 AI پیوی: <b>{'فعال' if row['private_enabled'] else 'غیرفعال'}</b>\n"
                f"🧠 مدل پیوی: <code>{html.escape(str(row['private_model'] or 'پیش‌فرض'))}</code>\n"
                f"🔑 کلید مشترک گروه: <b>{'ثبت شده و رمزنگاری‌شده' if row['has_group_key'] else 'ثبت نشده'}</b>"
            )
        await callback.message.edit_text(body, reply_markup=self._back(), parse_mode="HTML")
        await callback.answer()

    async def ai(self, callback):
        if not await self._guard(callback):
            await callback.answer(); return
        row = self._settings_row()
        enabled = bool(row and row["enabled"])
        kb = InlineKeyboardMarkup(row_width=1)
        kb.add(InlineKeyboardButton(f"🤖 AI گروه: {'روشن' if enabled else 'خاموش'}", callback_data="aip:toggle_group"))
        kb.add(InlineKeyboardButton("⬅️ پنل دستیار", callback_data="aip:menu"))
        await callback.message.edit_text("🤖 <b>تنظیمات AI گروه</b>\n\nکلید گروه از مسیر فعلی /ai_key مدیریت می‌شود.", reply_markup=kb, parse_mode="HTML")
        await callback.answer()

    async def toggle_group(self, callback):
        if not await self._guard(callback):
            await callback.answer(); return
        repo=self._repo()
        with repo.SessionLocal() as session:
            session.execute(text("""
                insert into public.mafia_ai_settings(group_id,enabled,web_search_enabled,updated_at)
                values(:gid,true,true,now())
                on conflict(group_id) do update set enabled=not public.mafia_ai_settings.enabled,updated_at=now()
            """), {"gid": self._group_id()})
            session.commit()
        await callback.answer("وضعیت AI گروه تغییر کرد.")
        await self.ai(callback)

    async def group_key(self, callback: types.CallbackQuery, state: FSMContext):
        if not await self._guard(callback):
            await callback.answer(); return
        await AssistantAdminStates.waiting_group_key.set()
        await callback.message.edit_text("🔑 <b>ثبت کلید AI گروه</b>\n\nاین کلید مشترک برای دستیار گروه و درخواست‌های پیوی اعضای همین گروه است.\nکلید Gemini یا OpenAI را ارسال کنید؛ پیام حاوی کلید بلافاصله حذف می‌شود.", parse_mode="HTML")
        await callback.answer()

    async def save_group_key(self, message: types.Message, state: FSMContext):
        if message.chat.type != "private" or not await self._authorized(message.from_user.id):
            await state.finish(); return
        key=(message.text or "").strip(); gid=self._group_id(); secret=os.getenv("DATABASE_URL") or ""
        if not key or not gid or not secret:
            await message.answer("❌ کلید، گروه اصلی یا تنظیمات رمزنگاری ناقص است."); return
        provider="gemini" if key.startswith("AIza") else "openai"
        model="gemini-2.5-flash" if provider=="gemini" else (os.getenv("MAFIA_AI_MODEL") or "gpt-5.6-mini")
        try:
            try: await message.delete()
            except Exception: pass
            with self._repo().SessionLocal() as session:
                session.execute(text("insert into public.mafia_ai_settings (group_id,provider,model,enabled,web_search_enabled,api_key_ciphertext,private_enabled,private_web_search_enabled,updated_at,private_updated_at) values(:gid,:provider,:model,true,true,pgp_sym_encrypt(:key,:secret),true,true,now(),now()) on conflict(group_id) do update set provider=:provider,model=:model,enabled=true,api_key_ciphertext=pgp_sym_encrypt(:key,:secret),private_enabled=true,updated_at=now(),private_updated_at=now()"), {"gid":gid,"provider":provider,"model":model,"key":key,"secret":secret})
                session.commit()
            await state.finish()
            await message.answer("✅ کلید مشترک AI گروه ثبت شد؛ دستیار گروه و پیوی اعضای گروه فعال شدند.", reply_markup=self._menu())
        except Exception:
            logging.exception("assistant admin: group key save failed")
            await state.finish()
            await message.answer("❌ ثبت کلید انجام نشد.", reply_markup=self._menu())

    async def pv(self, callback):
        if not await self._guard(callback):
            await callback.answer(); return
        row = self._settings_row()
        enabled = bool(row and row["private_enabled"])
        has_key = bool(row and row["has_private_key"])
        kb = InlineKeyboardMarkup(row_width=1)
        kb.add(InlineKeyboardButton("🔑 ثبت / تغییر کلید پیوی", callback_data="aip:pvkey"))
        kb.add(InlineKeyboardButton(f"🔐 AI پیوی: {'روشن' if enabled else 'خاموش'}", callback_data="aip:pvtoggle"))
        kb.add(InlineKeyboardButton("⬅️ پنل دستیار", callback_data="aip:menu"))
        await callback.message.edit_text(
            "🔐 <b>دستیار درخواست‌های پیوی</b>\n\n"
            f"کلید: <b>{'ثبت شده' if has_key else 'ثبت نشده'}</b>\n"
            f"وضعیت: <b>{'فعال' if enabled else 'غیرفعال'}</b>\n\n"
            "کلید در دیتابیس رمزنگاری می‌شود و متن پیام کلید بعد از ثبت حذف خواهد شد.",
            reply_markup=kb, parse_mode="HTML",
        )
        await callback.answer()

    async def pv_toggle(self, callback):
        if not await self._guard(callback):
            await callback.answer(); return
        with self._repo().SessionLocal() as session:
            session.execute(text("""
                insert into public.mafia_ai_settings(group_id,private_enabled,private_web_search_enabled,updated_at)
                values(:gid,true,true,now())
                on conflict(group_id) do update set private_enabled=not public.mafia_ai_settings.private_enabled,updated_at=now()
            """), {"gid": self._group_id()})
            session.commit()
        await callback.answer("وضعیت AI پیوی تغییر کرد.")
        await self.pv(callback)

    def register(self):
        dp = self.app.dp

        # Register the entry-point before generic text-command surfaces. The
        # production bot has several command routers and some consume messages
        # with CancelHandler; the assistant panel must own /ai_panel deterministically.
        dp.register_message_handler(
            self.open,
            lambda m: str(getattr(m, "text", "") or "").strip().split("@", 1)[0].casefold() in {"/ai_panel", "/پنل_دستیار"},
            state="*",
            content_types=types.ContentTypes.TEXT,
        )
        try:
            handlers = getattr(dp.message_handlers, "handlers", [])
            for item in list(handlers):
                callback = getattr(item, "callback", None) or getattr(item, "handler", None)
                if callback is self.open:
                    handlers.remove(item)
                    handlers.insert(0, item)
                    break
        except Exception:
            logging.exception("assistant admin: failed to prioritize panel handler")

        dp.register_message_handler(self.title, state=AssistantAdminStates.waiting_title)
        dp.register_message_handler(self.content, state=AssistantAdminStates.waiting_content)
        dp.register_message_handler(self.scenario, state=AssistantAdminStates.waiting_scenario)
        dp.register_message_handler(self.role, state=AssistantAdminStates.waiting_role)
        dp.register_message_handler(self.source, state=AssistantAdminStates.waiting_source)
        dp.register_message_handler(self.save_group_key, state=AssistantAdminStates.waiting_group_key)
        for action, fn in {
            "menu": self.menu, "kb": self.kb, "doc": self.doc,
            "publish": self.publish, "disable": self.disable,
            "add": self.add_start, "guide": self.guide, "scope": self.scope,
            "status": self.status, "ai": self.ai, "toggle_group": self.toggle_group,
            "pv": self.pv, "groupkey": self.group_key, "pvtoggle": self.pv_toggle,
        }.items():
            dp.register_callback_query_handler(
                fn, lambda c, a=action: str(c.data or "").startswith(f"aip:{a}"), state="*"
            )


def install(app: Any):
    panel = AssistantAdminPanel(app)
    panel.register()
    return panel
