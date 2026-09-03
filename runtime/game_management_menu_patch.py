"""Restore the full private game-management menu and bridge private actions to the group."""
from __future__ import annotations

import html
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from runtime.admin_menus_v2 import AdminMenusV2


def _group_id(app):
    for attr in ("group_chat_id", "ALLOWED_GROUP_ID", "GROUP_ID", "group_id"):
        value = getattr(app, attr, None)
        if value:
            try:
                return int(value)
            except (TypeError, ValueError):
                pass
    return None


def install(app):
    async def open_game(self, callback):
        if callback.message.chat.type != "private":
            await callback.answer("این بخش فقط در پیوی قابل استفاده است.", show_alert=True)
            return
        if not await self._can_manage(callback.from_user.id):
            await callback.answer("⛔ فقط گرداننده یا مدیر گروه دسترسی دارد.", show_alert=True)
            return
        gid = _group_id(self.app)
        if gid:
            self.app.group_chat_id = gid
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
            f"💺 صندلی‌های انتخاب‌شده: <b>{seats}</b>\n\n"
            "از این بخش تمام عملیات مدیریتی بازی در گروه کنترل می‌شود."
        )
        kb = InlineKeyboardMarkup(row_width=1)
        if not running and not lobby:
            kb.add(InlineKeyboardButton("🎮 ساخت بازی جدید", callback_data="lv6_new"))
        else:
            kb.add(InlineKeyboardButton("⚙️ ادامه مدیریت لابی", callback_data="lv6_manage"))
        for text, data in [
            ("🚫 لغو بازی", "lv6_cancel"),
            ("📝 تغییر سناریو", "lv6_change_s"),
            ("🎩 تغییر گرداننده", "lv6_change_m"),
            ("⚔️ وضعیت چالش", "lv6_challenge"),
            ("🗑 حذف بازیکن", "lv6_remove"),
            ("📢 حاضری / تگ لیست", "lv6_ready"),
            ("⬅️ بازگشت", "adm2:main"),
        ]:
            kb.add(InlineKeyboardButton(text, callback_data=data))
        await callback.message.edit_text(body, reply_markup=kb, parse_mode="HTML")
        await callback.answer()

    AdminMenusV2.open_game = open_game

    async def private_new(callback):
        if callback.message.chat.type != "private":
            return
        uid = callback.from_user.id
        gid = _group_id(app)
        if not gid:
            await callback.answer("⛔ گروه بازی تنظیم نشده است.", show_alert=True)
            return
        try:
            admins = await app.bot.get_chat_administrators(gid)
            is_admin = any(a.user.id == uid for a in admins)
        except Exception:
            is_admin = False
        if not is_admin and uid != getattr(app, "moderator_id", None):
            await callback.answer("⛔ فقط مدیر گروه می‌تواند بازی جدید بسازد.", show_alert=True)
            return
        if getattr(app, "game_running", False) or getattr(app, "round_active", False) or getattr(app, "lobby_active", False):
            await callback.answer("⚠️ یک بازی یا لابی فعال است. ابتدا آن را مدیریت یا لغو کنید.", show_alert=True)
            return
        app.group_chat_id = gid
        app.lobby_active = True
        app.selected_scenario = None
        app.moderator_id = None
        app.MAX_SEATS = 0
        app.players.clear(); app.player_slots.clear(); app.waiting_list.clear()
        if hasattr(app, "_lv6_ready_players"):
            app._lv6_ready_players.clear()
        app._lv6_setup = True
        app._lv6_change_scenario = False
        kb = InlineKeyboardMarkup(row_width=1)
        for i, (name, cfg) in enumerate((app.scenarios or {}).items()):
            roles = (cfg or {}).get("roles") or []
            kb.add(InlineKeyboardButton(
                f"📝 {name} ({(cfg or {}).get('min_players', 1)}-{len(roles)})",
                callback_data=f"lv6_s:{i}",
            ))
        kb.add(InlineKeyboardButton("⬅️ بازگشت", callback_data="lv6_home"))
        try:
            await app.bot.send_message(
                gid,
                "📝 <b>انتخاب سناریو</b>\n\nابتدا سناریوی بازی را انتخاب کنید.",
                reply_markup=kb,
                parse_mode="HTML",
            )
        except Exception:
            app.lobby_active = False
            await callback.answer("❌ ارسال منوی بازی به گروه ناموفق بود. دسترسی ربات به گروه را بررسی کنید.", show_alert=True)
            return
        await callback.answer("✅ منوی ساخت بازی در گروه ارسال شد.")

    app.dp.register_callback_query_handler(
        private_new,
        lambda c: c.data == "lv6_new" and c.message.chat.type == "private",
        state="*",
    )
    handlers = getattr(app.dp.callback_query_handlers, "handlers", [])
    for i, h in enumerate(handlers):
        if getattr(getattr(h, "handler", None), "__name__", "") == "private_new":
            handlers.insert(0, handlers.pop(i))
            break
    return True
