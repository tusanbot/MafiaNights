"""Authoritative private admin menus for game/scenario management and help.

This layer intentionally sits on top of the legacy handlers. It fixes the
private-menu UX without rewriting the game engine and adds validation around
scenario CRUD.
"""
from __future__ import annotations

import html
import json
from pathlib import Path

from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


SCENARIOS_FILE = Path("scenarios.json")


class ScenarioStates(StatesGroup):
    add_name = State()
    add_roles = State()
    add_min = State()
    edit_roles = State()
    edit_min = State()


class AdminMenusV2:
    def __init__(self, app):
        self.app = app
        self.dp = app.dp
        self.bot = app.bot

    async def _is_group_admin(self, uid: int) -> bool:
        gid = getattr(self.app, "group_chat_id", None)
        if not gid:
            return False
        try:
            return uid in {a.user.id for a in await self.bot.get_chat_administrators(gid)}
        except Exception:
            return False

    async def _can_manage(self, uid: int) -> bool:
        moderator = getattr(self.app, "moderator_id", None)
        return uid == moderator or await self._is_group_admin(uid)

    @staticmethod
    def _save(scenarios):
        with SCENARIOS_FILE.open("w", encoding="utf-8") as f:
            json.dump(scenarios, f, ensure_ascii=False, indent=2)

    def _scenarios(self):
        return self.app.scenarios

    def _main_kb(self):
        kb = InlineKeyboardMarkup(row_width=1)
        kb.add(
            InlineKeyboardButton("🛠 مدیریت بازی", callback_data="manage_game"),
            InlineKeyboardButton("⚙️ مدیریت سناریو", callback_data="adm2:scenarios"),
            InlineKeyboardButton("⚙️ امکانات اضافه", callback_data="addons_menu"),
            InlineKeyboardButton("👤 پروفایل", callback_data="up:menu"),
            InlineKeyboardButton("📚 راهنما", callback_data="help"),
        )
        return kb

    async def open_scenarios(self, callback: types.CallbackQuery):
        if not await self._can_manage(callback.from_user.id):
            await callback.answer("⛔ فقط گرداننده یا مدیر گروه دسترسی دارد.", show_alert=True)
            return
        scenarios = self._scenarios()
        body = (
            "⚙️ <b>مدیریت سناریو</b>\n\n"
            f"📚 تعداد سناریوها: <b>{len(scenarios)}</b>\n"
            "از این بخش می‌توانید سناریوها را اضافه، ویرایش، حذف یا مشاهده کنید."
        )
        kb = InlineKeyboardMarkup(row_width=1)
        kb.add(
            InlineKeyboardButton("➕ افزودن سناریو", callback_data="adm2:sc:add"),
            InlineKeyboardButton("✏️ ویرایش سناریو", callback_data="adm2:sc:edit"),
            InlineKeyboardButton("🗑 حذف سناریو", callback_data="adm2:sc:delete"),
            InlineKeyboardButton("📋 فهرست سناریوها", callback_data="adm2:sc:list"),
            InlineKeyboardButton("⬅️ بازگشت", callback_data="adm2:main"),
        )
        await callback.message.edit_text(body, reply_markup=kb, parse_mode="HTML")
        await callback.answer()

    async def list_scenarios(self, callback):
        if not await self._can_manage(callback.from_user.id):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        scenarios = self._scenarios()
        lines = ["📋 <b>فهرست سناریوها</b>", ""]
        if not scenarios:
            lines.append("هیچ سناریویی ثبت نشده است.")
        for i, (name, cfg) in enumerate(scenarios.items(), 1):
            roles = cfg.get("roles") or []
            minimum = cfg.get("min_players", 1)
            lines.append(f"{i}. <b>{html.escape(name)}</b> — {minimum} تا {len(roles)} نفر")
        kb = InlineKeyboardMarkup().add(InlineKeyboardButton("⬅️ مدیریت سناریو", callback_data="adm2:scenarios"))
        await callback.message.edit_text("\n".join(lines), reply_markup=kb, parse_mode="HTML")
        await callback.answer()

    async def add_start(self, callback, state):
        if not await self._can_manage(callback.from_user.id):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        await state.finish()
        await state.set_state(ScenarioStates.add_name)
        await callback.message.answer("➕ <b>افزودن سناریو</b>\n\nنام سناریو را ارسال کنید.\nبرای لغو: /cancel", parse_mode="HTML")
        await callback.answer()

    async def add_name(self, message, state):
        name = (message.text or "").strip()
        if not name or len(name) > 60:
            await message.answer("⚠️ نام سناریو باید بین ۱ تا ۶۰ کاراکتر باشد.")
            return
        if name in self._scenarios():
            await message.answer("⚠️ این نام قبلاً وجود دارد؛ نام دیگری انتخاب کنید.")
            return
        await state.update_data(name=name)
        await state.set_state(ScenarioStates.add_roles)
        await message.answer("🎭 نقش‌ها را با کاما جدا کنید.\nمثال: مافیا, دکتر, شهروند, شهروند")

    async def add_roles(self, message, state):
        roles = [x.strip() for x in (message.text or "").split(",") if x.strip()]
        if not roles:
            await message.answer("⚠️ حداقل یک نقش وارد کنید.")
            return
        if len(roles) > 50:
            await message.answer("⚠️ حداکثر ۵۰ نقش مجاز است.")
            return
        await state.update_data(roles=roles)
        await state.set_state(ScenarioStates.add_min)
        await message.answer(f"🔢 حداقل تعداد بازیکن را وارد کنید (۱ تا {len(roles)}):")

    async def add_min(self, message, state):
        raw = (message.text or "").strip()
        if not raw.isdigit():
            await message.answer("⚠️ فقط عدد وارد کنید.")
            return
        minimum = int(raw)
        data = await state.get_data()
        roles = data.get("roles") or []
        if minimum < 1 or minimum > len(roles):
            await message.answer(f"⚠️ حداقل بازیکن باید بین ۱ و {len(roles)} باشد.")
            return
        self._scenarios()[data["name"]] = {
            "roles": roles,
            "min_players": minimum,
            "max_players": len(roles),
        }
        self._save(self._scenarios())
        await state.finish()
        await message.answer(
            f"✅ سناریو <b>{html.escape(data['name'])}</b> ذخیره شد.\n"
            f"👥 ظرفیت: {minimum} تا {len(roles)} نفر\n"
            f"🎭 نقش‌ها: {html.escape(', '.join(roles))}", parse_mode="HTML",
            reply_markup=self._main_kb(),
        )

    async def choose_edit(self, callback):
        if not await self._can_manage(callback.from_user.id):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        kb = InlineKeyboardMarkup(row_width=1)
        for i, name in enumerate(self._scenarios()):
            kb.add(InlineKeyboardButton(f"✏️ {name}", callback_data=f"adm2:sc:edit:{i}"))
        kb.add(InlineKeyboardButton("⬅️ بازگشت", callback_data="adm2:scenarios"))
        await callback.message.edit_text("✏️ <b>انتخاب سناریو برای ویرایش</b>", reply_markup=kb, parse_mode="HTML")
        await callback.answer()

    async def edit_start(self, callback, state):
        if not await self._can_manage(callback.from_user.id):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        try:
            index = int(callback.data.rsplit(":", 1)[1])
            name = list(self._scenarios())[index]
        except Exception:
            await callback.answer("سناریو نامعتبر است.", show_alert=True); return
        await state.finish()
        await state.update_data(name=name)
        await state.set_state(ScenarioStates.edit_roles)
        await callback.message.answer(
            f"✏️ ویرایش <b>{html.escape(name)}</b>\n\n"
            "نقش‌های جدید را با کاما وارد کنید.\nبرای لغو: /cancel", parse_mode="HTML")
        await callback.answer()

    async def edit_roles(self, message, state):
        roles = [x.strip() for x in (message.text or "").split(",") if x.strip()]
        data = await state.get_data()
        if not roles:
            await message.answer("⚠️ حداقل یک نقش لازم است.")
            return
        if len(roles) > 50:
            await message.answer("⚠️ حداکثر ۵۰ نقش مجاز است.")
            return
        await state.update_data(roles=roles)
        await state.set_state(ScenarioStates.edit_min)
        await message.answer(f"🔢 حداقل بازیکن را وارد کنید (۱ تا {len(roles)}):")

    async def edit_min(self, message, state):
        raw = (message.text or "").strip()
        if not raw.isdigit():
            await message.answer("⚠️ فقط عدد وارد کنید.")
            return
        minimum = int(raw)
        data = await state.get_data()
        roles = data.get("roles") or []
        if minimum < 1 or minimum > len(roles):
            await message.answer(f"⚠️ عدد باید بین ۱ و {len(roles)} باشد.")
            return
        name = data["name"]
        self._scenarios()[name] = {"roles": roles, "min_players": minimum, "max_players": len(roles)}
        self._save(self._scenarios())
        await state.finish()
        await message.answer(f"✅ سناریو <b>{html.escape(name)}</b> ویرایش شد.", parse_mode="HTML", reply_markup=self._main_kb())

    async def choose_delete(self, callback):
        if not await self._can_manage(callback.from_user.id):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        kb = InlineKeyboardMarkup(row_width=1)
        for i, name in enumerate(self._scenarios()):
            kb.add(InlineKeyboardButton(f"🗑 {name}", callback_data=f"adm2:sc:del:{i}"))
        kb.add(InlineKeyboardButton("⬅️ بازگشت", callback_data="adm2:scenarios"))
        await callback.message.edit_text("🗑 <b>انتخاب سناریو برای حذف</b>\n\nحذف سناریوی فعال در بازی ممنوع است.", reply_markup=kb, parse_mode="HTML")
        await callback.answer()

    async def delete_confirm(self, callback):
        if not await self._can_manage(callback.from_user.id):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        try:
            index = int(callback.data.rsplit(":", 1)[1])
            name = list(self._scenarios())[index]
        except Exception:
            await callback.answer("سناریو نامعتبر است.", show_alert=True); return
        if name == getattr(self.app, "selected_scenario", None) and (getattr(self.app, "lobby_active", False) or getattr(self.app, "game_running", False)):
            await callback.answer("⚠️ سناریوی فعال بازی را نمی‌توان حذف کرد.", show_alert=True); return
        self._scenarios().pop(name, None)
        self._save(self._scenarios())
        await callback.answer("✅ سناریو حذف شد.")
        await self.open_scenarios(callback)

    async def open_game(self, callback):
        if callback.message.chat.type != "private":
            await callback.answer("این بخش فقط در پیوی قابل استفاده است.", show_alert=True); return
        if not await self._can_manage(callback.from_user.id):
            await callback.answer("⛔ فقط گرداننده یا مدیر گروه دسترسی دارد.", show_alert=True); return
        running = bool(getattr(self.app, "game_running", False))
        lobby = bool(getattr(self.app, "lobby_active", False))
        scenario = getattr(self.app, "selected_scenario", None) or "—"
        players = len(getattr(self.app, "players", {}) or {})
        seats = len(getattr(self.app, "player_slots", {}) or {})
        body = (
            "🛠 <b>مدیریت بازی</b>\n\n"
            f"📌 وضعیت: <b>{'در حال اجرا' if running else ('لابی فعال' if lobby else 'آماده')}</b>\n"
            f"📝 سناریو: <b>{html.escape(str(scenario))}</b>\n"
            f"👥 بازیکنان: <b>{players}</b>\n"
            f"💺 صندلی‌های انتخاب‌شده: <b>{seats}</b>\n"
        )
        kb = InlineKeyboardMarkup(row_width=1)
        if not running and not lobby:
            kb.add(InlineKeyboardButton("🎮 ساخت بازی جدید", callback_data="lv6_new"))
        else:
            kb.add(InlineKeyboardButton("⚙️ ادامه مدیریت لابی", callback_data="lv6_manage"))
        kb.add(InlineKeyboardButton("🎯 تنظیمات چالش", callback_data="lv6_challenge"))
        kb.add(InlineKeyboardButton("📢 حاضری / تگ لیست", callback_data="lv6_ready"))
        kb.add(InlineKeyboardButton("⬅️ بازگشت", callback_data="adm2:main"))
        await callback.message.edit_text(body, reply_markup=kb, parse_mode="HTML")
        await callback.answer()

    async def help(self, callback):
        body = (
            "📚 <b>راهنمای Mafia Nights</b>\n\n"
            "🎮 <b>شروع بازی</b>\n"
            "از منوی ربات «مدیریت بازی» و سپس «ساخت بازی جدید» را بزنید. ابتدا سناریو و سپس گرداننده انتخاب می‌شود.\n\n"
            "📝 <b>سناریو</b>\n"
            "سناریو تعداد نقش‌ها و حداقل بازیکنان را تعیین می‌کند. مدیران گروه می‌توانند سناریو را اضافه، ویرایش یا حذف کنند.\n\n"
            "💺 <b>لابی</b>\n"
            "بازیکنان وارد بازی می‌شوند، صندلی انتخاب می‌کنند و پس از تکمیل ظرفیت امکان پخش نقش فعال می‌شود. بازیکنان اضافه می‌توانند وارد لیست رزرو شوند.\n\n"
            "🎭 <b>نقش و نوبت</b>\n"
            "پس از پخش نقش، نقش هر بازیکن به‌صورت خصوصی ارسال می‌شود و نوبت‌ها در گروه اجرا می‌شوند.\n\n"
            "⚔️ <b>چالش</b>\n"
            "هر بازیکن در هر دور طبق تنظیمات بازی می‌تواند از چالش استفاده کند. چالش قبل و بعد از نوبت رفتار متفاوتی دارند.\n\n"
            "⚙️ <b>امکانات اضافه</b>\n"
            "امنیت، کنترل نوبت، ضداسپم نکست، شروع خودکار و نمایش‌های کمکی از این بخش مدیریت می‌شوند.\n\n"
            "👤 <b>پنل کاربری</b>\n"
            "پروفایل، آمار، رتبه‌بندی، تاریخچه و تنظیمات نام مستعار در پنل خصوصی قابل دسترسی است.\n\n"
            "❗ <b>نکته:</b> عملیات مدیریتی فقط برای گرداننده یا مدیران گروه مجاز است."
        )
        kb = InlineKeyboardMarkup(row_width=1).add(
            InlineKeyboardButton("⬅️ بازگشت", callback_data="adm2:main")
        )
        await callback.message.edit_text(body, reply_markup=kb, parse_mode="HTML")
        await callback.answer()

    async def cancel_state(self, message, state):
        await state.finish()
        await message.answer("❌ عملیات لغو شد.", reply_markup=self._main_kb())

    def install(self):
        dp = self.dp
        dp.register_callback_query_handler(self.open_game, lambda c: c.data == "manage_game", state="*")
        dp.register_callback_query_handler(self.open_scenarios, lambda c: c.data in {"manage_scenarios", "adm2:scenarios"}, state="*")
        dp.register_callback_query_handler(self.add_start, lambda c: c.data == "adm2:sc:add", state="*")
        dp.register_callback_query_handler(self.choose_edit, lambda c: c.data == "adm2:sc:edit", state="*")
        dp.register_callback_query_handler(self.edit_start, lambda c: c.data.startswith("adm2:sc:edit:"), state="*")
        dp.register_callback_query_handler(self.choose_delete, lambda c: c.data == "adm2:sc:delete", state="*")
        dp.register_callback_query_handler(self.delete_confirm, lambda c: c.data.startswith("adm2:sc:del:"), state="*")
        dp.register_callback_query_handler(self.list_scenarios, lambda c: c.data == "adm2:sc:list", state="*")
        dp.register_callback_query_handler(self.help, lambda c: c.data == "help", state="*")
        dp.register_callback_query_handler(lambda c: self._back_main(c), lambda c: c.data == "adm2:main", state="*")
        dp.register_message_handler(self.add_name, state=ScenarioStates.add_name)
        dp.register_message_handler(self.add_roles, state=ScenarioStates.add_roles)
        dp.register_message_handler(self.add_min, state=ScenarioStates.add_min)
        dp.register_message_handler(self.edit_roles, state=ScenarioStates.edit_roles)
        dp.register_message_handler(self.edit_min, state=ScenarioStates.edit_min)
        dp.register_message_handler(self.cancel_state, commands=["cancel"], state="*")
        self._front_registered()
        return self

    async def _back_main(self, callback):
        if not await self._can_manage(callback.from_user.id):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        await callback.message.edit_text("📋 <b>منوی ربات</b>", reply_markup=self._main_kb(), parse_mode="HTML")
        await callback.answer()

    def _front_registered(self):
        """Put authoritative exact callbacks ahead of legacy duplicates."""
        wanted = {"open_game", "open_scenarios", "add_start", "choose_edit", "edit_start", "choose_delete", "delete_confirm", "list_scenarios", "help"}
        handlers = getattr(self.dp.callback_query_handlers, "handlers", [])
        for name in wanted:
            for i, h in enumerate(handlers):
                if getattr(getattr(h, "handler", None), "__name__", "") == name:
                    handlers.insert(0, handlers.pop(i))
                    break


def install(app):
    return AdminMenusV2(app).install()
