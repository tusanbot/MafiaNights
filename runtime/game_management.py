"""Central, game-id-bound game management for lobby and live games."""
from __future__ import annotations

import html
import logging
from typing import Any

from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from repositories.scenario_repository import ScenarioRepository


class ManagementState(StatesGroup):
    waiting_event_number = State()


class GameManagement:
    """One management surface shared by lobby and live gameplay."""

    def __init__(self, app: Any):
        self.app = app
        self.scenarios = ScenarioRepository()

    def _game(self, gid: int):
        return self.app.runtime.state.active_game(int(gid))

    def _state(self, game: dict[str, Any]) -> dict[str, Any]:
        return dict(game.get("state") or {})

    def _save_state(self, game: dict[str, Any], **changes: Any) -> bool:
        state = self._state(game)
        state.update(changes)
        game["state"] = state
        return bool(self.app.runtime.state.games.update_game(game["id"], state=state))

    async def _allowed(self, obj: Any, gid: int, game: dict[str, Any] | None = None) -> bool:
        game = game or self._game(gid)
        if not game:
            return False
        uid = int(obj.from_user.id)
        if uid == int(game.get("moderator_id") or 0):
            return True
        try:
            member = await self.app.bot.get_chat_member(gid, uid)
            return member.status in {"creator", "administrator"}
        except Exception:
            return False

    def _parse(self, callback: types.CallbackQuery, action: str, size: int):
        p = str(callback.data or "").split(":")
        if len(p) != size or p[0] != "mgmt" or p[2] != action:
            return None
        return p

    def _players(self, game_id: int):
        return self.app.runtime.state.games.list_players(game_id)

    def _name(self, row: dict[str, Any]) -> str:
        return str(row.get("nickname") or row.get("first_name") or row.get("username") or row.get("player_id") or "👤")

    def panel_keyboard(self, game_id: int) -> InlineKeyboardMarkup:
        kb = InlineKeyboardMarkup(row_width=3)
        buttons = [
            ("🔢 شماره بازی", "event"), ("📝 تغییر سناریو", "scenario"), ("🗑 حذف بازیکن", "remove"),
            ("🎟 لغو رزرو", "unreserve"), ("🔄 جایگزین بازیکن", "replace"), ("✅ حاضری", "attendance"),
            ("🎂 تولد بازیکن", "birthday"), ("⚔ وضعیت چالش", "challenge"), ("⏭ مدیریت نکست", "next"),
            ("🚫 لغو بازی", "cancel"), ("🔄 بازسازی لابی", "refresh"), ("✖️ بستن مدیریت", "close"),
        ]
        for i in range(0, len(buttons), 3):
            row = [InlineKeyboardButton(label, callback_data=f"mgmt:{game_id}:{action}") for label, action in buttons[i:i + 3]]
            kb.row(*row)
        return kb

    async def open(self, callback: types.CallbackQuery):
        gid = int(callback.message.chat.id)
        game = self._game(gid)
        if not game:
            await callback.answer("❌ بازی فعالی وجود ندارد.", show_alert=True)
            return
        if not await self._allowed(callback, gid, game):
            await callback.answer("⛔ فقط گرداننده یا مدیر گروه.", show_alert=True)
            return
        number = int(game.get("event_number") or 1)
        status = str(game.get("status") or "lobby")
        text = f"⚙️ <b>مدیریت بازی</b>\n\n🔢 شماره: {number}\n📌 وضعیت: {html.escape(status)}"
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=self.panel_keyboard(int(game["id"])))
        await callback.answer()

    async def event(self, callback: types.CallbackQuery):
        gid = int(callback.message.chat.id); game = self._game(gid)
        if not game or not await self._allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید یا بازی فعال نیست.", show_alert=True); return
        number = int(game.get("event_number") or 1)
        kb = InlineKeyboardMarkup(row_width=3)
        kb.row(
            InlineKeyboardButton("−100", callback_data=f"mgmt:{game['id']}:event_delta:-100"),
            InlineKeyboardButton("−10", callback_data=f"mgmt:{game['id']}:event_delta:-10"),
            InlineKeyboardButton("−1", callback_data=f"mgmt:{game['id']}:event_delta:-1"),
        )
        kb.row(
            InlineKeyboardButton(f"🔢 {number}", callback_data=f"mgmt:{game['id']}:event_noop"),
            InlineKeyboardButton("+1", callback_data=f"mgmt:{game['id']}:event_delta:1"),
            InlineKeyboardButton("+10", callback_data=f"mgmt:{game['id']}:event_delta:10"),
        )
        kb.row(
            InlineKeyboardButton("+100", callback_data=f"mgmt:{game['id']}:event_delta:100"),
            InlineKeyboardButton("✍️ ورود دستی", callback_data=f"mgmt:{game['id']}:event_input"),
            InlineKeyboardButton("⬅️ مدیریت", callback_data=f"mgmt:{game['id']}:open"),
        )
        await callback.message.edit_text("🔢 <b>تغییر شماره بازی</b>\n\nمقدار دلخواه را مستقیم وارد کنید یا از افزایش/کاهش استفاده کنید.", parse_mode="HTML", reply_markup=kb)
        await callback.answer()

    async def event_delta(self, callback: types.CallbackQuery):
        p = self._parse(callback, "event_delta", 4)
        if not p: return
        gid = int(callback.message.chat.id); game = self._game(gid)
        if not game or not await self._allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        try: delta = int(p[3])
        except ValueError: await callback.answer("❌ مقدار نامعتبر.", show_alert=True); return
        number = max(1, int(game.get("event_number") or 1) + delta)
        if not self.app.runtime.state.games.update_game(game["id"], event_number=number):
            await callback.answer("❌ تغییر شماره انجام نشد.", show_alert=True); return
        await callback.answer(f"🔢 شماره بازی: {number}")
        await self.event(callback)

    async def event_input(self, callback: types.CallbackQuery, state: FSMContext):
        gid = int(callback.message.chat.id); game = self._game(gid)
        if not game or not await self._allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        await state.update_data(game_id=int(game["id"]), group_id=gid)
        await state.set_state(ManagementState.waiting_event_number)
        await callback.message.edit_text("✍️ <b>شماره بازی جدید</b>\n\nیک عدد مثبت وارد کنید:", parse_mode="HTML")
        await callback.answer()

    async def event_input_value(self, message: types.Message, state: FSMContext):
        data = await state.get_data()
        gid = int(data.get("group_id") or message.chat.id)
        game = self._game(gid)
        if not game or not await self._allowed(message, gid, game):
            await state.finish(); await message.reply("⛔ دسترسی ندارید."); return
        raw = (message.text or "").strip().replace("٬", "").replace(",", "")
        if not raw.isdigit() or int(raw) < 1:
            await message.reply("❌ فقط یک عدد مثبت وارد کنید.")
            return
        number = int(raw)
        if not self.app.runtime.state.games.update_game(game["id"], event_number=number):
            await state.finish(); await message.reply("❌ ذخیره شماره انجام نشد."); return
        await state.finish()
        await message.reply(f"✅ شماره بازی روی <b>{number}</b> تنظیم شد.", parse_mode="HTML")

    async def scenario(self, callback: types.CallbackQuery):
        gid = int(callback.message.chat.id); game = self._game(gid)
        if not game or not await self._allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        kb = InlineKeyboardMarkup(row_width=2)
        for row in self.scenarios.list_active():
            kb.insert(InlineKeyboardButton(f"📝 {row.get('name')} ({len(row.get('roles') or [])})", callback_data=f"mgmt:{game['id']}:scenario_pick:{int(row['id'])}"))
        kb.row(InlineKeyboardButton("⬅️ مدیریت", callback_data=f"mgmt:{game['id']}:open"))
        await callback.message.edit_text("📝 <b>تغییر سناریو</b>\n\nبا تغییر سناریو، انتخاب گرداننده الزامی است.", parse_mode="HTML", reply_markup=kb)
        await callback.answer()

    async def scenario_pick(self, callback: types.CallbackQuery):
        p = self._parse(callback, "scenario_pick", 4)
        if not p: return
        gid = int(callback.message.chat.id); game = self._game(gid); sid = int(p[3])
        if not game or not await self._allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        row = self.scenarios.get_by_id(sid)
        if not row or not row.get("is_active", True):
            await callback.answer("❌ سناریو معتبر نیست.", show_alert=True); return
        self.app.runtime.state.games.update_game(game["id"], scenario_id=sid, moderator_id=None)
        admins = await self.app.bot.get_chat_administrators(gid)
        kb = InlineKeyboardMarkup(row_width=2)
        for admin in admins:
            kb.insert(InlineKeyboardButton(admin.user.full_name, callback_data=f"mgmt:{game['id']}:moderator_pick:{int(admin.user.id)}"))
        await callback.message.edit_text("🎩 <b>انتخاب گرداننده</b>\n\nبعد از تغییر سناریو، حتماً گرداننده جدید را انتخاب کنید:", parse_mode="HTML", reply_markup=kb)
        await callback.answer("سناریو ثبت شد؛ انتخاب گرداننده الزامی است.")

    async def moderator_pick(self, callback: types.CallbackQuery):
        p = self._parse(callback, "moderator_pick", 4)
        if not p: return
        gid = int(callback.message.chat.id); game = self._game(gid); uid = int(p[3])
        if not game or not await self._allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        admins = await self.app.bot.get_chat_administrators(gid)
        if uid not in {int(a.user.id) for a in admins}:
            await callback.answer("❌ این کاربر مدیر گروه نیست.", show_alert=True); return
        self.app.runtime.state.games.update_game(game["id"], moderator_id=uid)
        await callback.answer("✅ گرداننده ثبت شد.")
        await callback.message.edit_text("✅ <b>سناریو و گرداننده با موفقیت تغییر کردند.</b>", parse_mode="HTML", reply_markup=self.panel_keyboard(int(game["id"])))

    async def remove(self, callback: types.CallbackQuery):
        await self._player_picker(callback, "remove", "🗑 حذف بازیکن", active_only=True)

    async def unreserve(self, callback: types.CallbackQuery):
        gid = int(callback.message.chat.id); game = self._game(gid)
        if not game or not await self._allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        waiting = [r for r in self._players(int(game["id"])) if r.get("seat") is None and str(r.get("status") or "") == "waiting"]
        kb = InlineKeyboardMarkup(row_width=2)
        for r in waiting:
            uid = int(r["player_id"]); kb.insert(InlineKeyboardButton(self._name(r), callback_data=f"mgmt:{game['id']}:unreserve_pick:{uid}"))
        kb.row(InlineKeyboardButton("⬅️ مدیریت", callback_data=f"mgmt:{game['id']}:open"))
        await callback.message.edit_text("🎟 <b>لغو رزرو</b>\n\nبازیکن موردنظر را انتخاب کنید:", parse_mode="HTML", reply_markup=kb)
        await callback.answer()

    async def unreserve_pick(self, callback: types.CallbackQuery):
        p = self._parse(callback, "unreserve_pick", 4)
        if not p: return
        await self._remove_player_by_id(callback, int(p[3]), "رزرو بازیکن لغو شد.")

    async def _player_picker(self, callback, action: str, title: str, active_only=False):
        gid = int(callback.message.chat.id); game = self._game(gid)
        if not game or not await self._allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        rows = self._players(int(game["id"]))
        if active_only: rows = [r for r in rows if r.get("seat") is not None and str(r.get("status") or "") not in {"removed", "dead"}]
        kb = InlineKeyboardMarkup(row_width=2)
        for r in rows:
            uid = int(r["player_id"]); seat = r.get("seat")
            label = f"{seat}. {self._name(r)}" if seat is not None else self._name(r)
            kb.insert(InlineKeyboardButton(label, callback_data=f"mgmt:{game['id']}:{action}_pick:{uid}"))
        kb.row(InlineKeyboardButton("⬅️ مدیریت", callback_data=f"mgmt:{game['id']}:open"))
        await callback.message.edit_text(title, parse_mode="HTML", reply_markup=kb)
        await callback.answer()

    async def remove_pick(self, callback: types.CallbackQuery):
        p = self._parse(callback, "remove_pick", 4)
        if not p: return
        await self._remove_player_by_id(callback, int(p[3]), "بازیکن از بازی حذف شد.")

    async def _remove_player_by_id(self, callback, uid: int, message: str):
        gid = int(callback.message.chat.id); game = self._game(gid)
        if not game or not await self._allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        rows = self._players(int(game["id"]))
        row = next((r for r in rows if int(r["player_id"]) == uid), None)
        if not row:
            await callback.answer("❌ بازیکن پیدا نشد.", show_alert=True); return
        seat = row.get("seat")
        try:
            self.app.runtime.state.games.set_player_seat(game["id"], uid, None)
            self.app.runtime.state.games.set_player_status(game["id"], uid, "removed")
            if seat is not None and str(game.get("status")) == "lobby":
                try: self.app.runtime.lobby.promote_waiting(game["id"], int(seat))
                except Exception: pass
        except Exception:
            logging.exception("remove player failed game=%s uid=%s", game["id"], uid)
            await callback.answer("❌ حذف بازیکن انجام نشد.", show_alert=True); return
        await callback.message.edit_text(f"✅ {html.escape(self._name(row))} — {message}", parse_mode="HTML", reply_markup=self.panel_keyboard(int(game["id"])))
        await callback.answer("✅ انجام شد.")

    async def replace(self, callback: types.CallbackQuery):
        gid = int(callback.message.chat.id); game = self._game(gid)
        if not game or not await self._allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        waiting = [r for r in self._players(int(game["id"])) if r.get("seat") is None and str(r.get("status") or "") == "waiting"]
        kb = InlineKeyboardMarkup(row_width=2)
        for r in waiting:
            kb.insert(InlineKeyboardButton(self._name(r), callback_data=f"mgmt:{game['id']}:replace_sub:{int(r['player_id'])}"))
        kb.row(InlineKeyboardButton("⬅️ مدیریت", callback_data=f"mgmt:{game['id']}:open"))
        await callback.message.edit_text("🔄 <b>جایگزین بازیکن</b>\n\nابتدا بازیکن جایگزین را انتخاب کنید:", parse_mode="HTML", reply_markup=kb)
        await callback.answer()

    async def replace_sub(self, callback: types.CallbackQuery):
        p = self._parse(callback, "replace_sub", 4)
        if not p: return
        gid = int(callback.message.chat.id); game = self._game(gid); sub_id = int(p[3])
        if not game or not await self._allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        rows = [r for r in self._players(int(game["id"])) if r.get("seat") is not None and str(r.get("status") or "") not in {"removed"}]
        kb = InlineKeyboardMarkup(row_width=2)
        for r in rows:
            kb.insert(InlineKeyboardButton(f"{r.get('seat')}. {self._name(r)}", callback_data=f"mgmt:{game['id']}:replace_target:{sub_id}:{int(r['player_id'])}"))
        await callback.message.edit_text("👤 بازیکن جایگزین، بازیکن مقصد را انتخاب کنید:", reply_markup=kb)
        await callback.answer()

    async def replace_target(self, callback: types.CallbackQuery):
        p = str(callback.data or "").split(":")
        if len(p) != 5 or p[0] != "mgmt" or p[2] != "replace_target": return
        gid = int(callback.message.chat.id); game = self._game(gid); sub_id = int(p[3]); old_id = int(p[4])
        if not game or not await self._allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        rows = self._players(int(game["id"])); old = next((r for r in rows if int(r["player_id"]) == old_id), None); sub = next((r for r in rows if int(r["player_id"]) == sub_id), None)
        if not old or not sub or old.get("seat") is None or sub.get("seat") is not None:
            await callback.answer("❌ اطلاعات جایگزینی نامعتبر است.", show_alert=True); return
        seat = int(old["seat"])
        try:
            self.app.runtime.state.games.set_player_seat(game["id"], old_id, None)
            self.app.runtime.state.games.set_player_status(game["id"], old_id, "removed")
            self.app.runtime.state.games.set_player_seat(game["id"], sub_id, seat)
            self.app.runtime.state.games.set_player_status(game["id"], sub_id, "active")
        except Exception:
            logging.exception("replace failed game=%s", game["id"])
            await callback.answer("❌ جایگزینی انجام نشد.", show_alert=True); return
        await callback.message.edit_text(f"✅ {html.escape(self._name(old))} با {html.escape(self._name(sub))} جایگزین شد.\n💺 صندلی: {seat}", parse_mode="HTML", reply_markup=self.panel_keyboard(int(game["id"])))
        await callback.answer("🔄 جایگزینی انجام شد.")

    async def attendance(self, callback: types.CallbackQuery):
        gid = int(callback.message.chat.id); game = self._game(gid)
        if not game or not await self._allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        state = self._state(game); attendance = dict(state.get("attendance") or {})
        rows = [r for r in self._players(int(game["id"])) if r.get("seat") is not None and str(r.get("status") or "") not in {"removed"}]
        kb = InlineKeyboardMarkup(row_width=2)
        for r in rows:
            uid = int(r["player_id"]); present = bool(attendance.get(str(uid), True)); mark = "🟢" if present else "🔴"
            kb.insert(InlineKeyboardButton(f"{mark} {r.get('seat')}. {self._name(r)}", callback_data=f"mgmt:{game['id']}:attendance_toggle:{uid}"))
        kb.row(InlineKeyboardButton("⬅️ مدیریت", callback_data=f"mgmt:{game['id']}:open"))
        await callback.message.edit_text("✅ <b>حاضری بازیکنان</b>\n\nبرای تغییر وضعیت روی بازیکن بزنید.", reply_markup=kb, parse_mode="HTML")
        await callback.answer()

    async def attendance_toggle(self, callback: types.CallbackQuery):
        p = self._parse(callback, "attendance_toggle", 4)
        if not p: return
        gid = int(callback.message.chat.id); game = self._game(gid); uid = int(p[3])
        if not game or not await self._allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        state = self._state(game); attendance = dict(state.get("attendance") or {}); attendance[str(uid)] = not bool(attendance.get(str(uid), True))
        self._save_state(game, attendance=attendance)
        await callback.answer("✅ وضعیت حاضری تغییر کرد."); await self.attendance(callback)

    async def birthday(self, callback: types.CallbackQuery):
        await self._player_picker(callback, "birthday", "🎂 <b>بازگردانی / تولد بازیکن</b>\n\nبازیکن حذف‌شده یا مرده را انتخاب کنید:")

    async def birthday_pick(self, callback: types.CallbackQuery):
        p = self._parse(callback, "birthday_pick", 4)
        if not p: return
        gid = int(callback.message.chat.id); game = self._game(gid); uid = int(p[3])
        if not game or not await self._allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        rows = self._players(int(game["id"])); row = next((r for r in rows if int(r["player_id"]) == uid), None)
        if not row:
            await callback.answer("❌ بازیکن پیدا نشد.", show_alert=True); return
        try:
            self.app.runtime.state.games.set_player_status(game["id"], uid, "active")
            alive = getattr(self.app.runtime.state.games, "set_player_alive", None)
            if alive: alive(game["id"], uid, True)
            if row.get("seat") is None:
                seats = {int(r["seat"]) for r in rows if r.get("seat") is not None}
                cap = len(self.scenarios.get_by_id(int(game.get("scenario_id"))) .get("roles") or []) if game.get("scenario_id") else 0
                free = next((s for s in range(1, cap + 1) if s not in seats), None)
                if free is not None: self.app.runtime.state.games.set_player_seat(game["id"], uid, free)
        except Exception:
            logging.exception("birthday failed game=%s uid=%s", game["id"], uid)
            await callback.answer("❌ بازگردانی انجام نشد.", show_alert=True); return
        await callback.message.edit_text(f"🎂 {html.escape(self._name(row))} بازگردانده شد.", parse_mode="HTML", reply_markup=self.panel_keyboard(int(game["id"])))
        await callback.answer("🎂 بازیکن بازگردانده شد.")

    async def challenge(self, callback: types.CallbackQuery):
        gid = int(callback.message.chat.id); game = self._game(gid)
        if not game or not await self._allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        challenges = self.app.runtime.state.challenges.list_challenges(game["id"])
        state = self._state(game)
        enabled = bool(getattr(self.app, "challenge_enabled", {}).get(gid, True))
        pending = len([c for c in challenges if str(c.get("status")) == "pending"])
        active = len([c for c in challenges if str(c.get("status")) in {"accepted", "active"}])
        text = f"⚔ <b>وضعیت چالش</b>\n\n🟢 سرویس: {'فعال' if enabled else 'خاموش'}\n⏳ در انتظار: {pending}\n⚡ فعال: {active}\n📦 ثبت‌شده: {len(challenges)}\n\nدرخواست‌های موقت: {len(state.get('challenge_requests') or {})}"
        kb = InlineKeyboardMarkup(row_width=2).add(
            InlineKeyboardButton("🔴 خاموش" if enabled else "🟢 روشن", callback_data=f"mgmt:{game['id']}:challenge_toggle"),
            InlineKeyboardButton("⬅️ مدیریت", callback_data=f"mgmt:{game['id']}:open"),
        )
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb); await callback.answer()

    async def challenge_toggle(self, callback: types.CallbackQuery):
        gid = int(callback.message.chat.id); game = self._game(gid)
        if not game or not await self._allowed(callback, gid, game): await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        if not hasattr(self.app, "challenge_enabled"): self.app.challenge_enabled = {}
        self.app.challenge_enabled[gid] = not self.app.challenge_enabled.get(gid, True)
        await callback.answer("⚔ وضعیت چالش تغییر کرد."); await self.challenge(callback)

    async def next(self, callback: types.CallbackQuery):
        gid = int(callback.message.chat.id); game = self._game(gid)
        if not game or not await self._allowed(callback, gid, game): await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        s = dict(self._state(game).get("next_settings") or {})
        s.setdefault("allow_players_next", True); s.setdefault("allow_moderator_next", True); s.setdefault("anti_spam", True)
        kb = InlineKeyboardMarkup(row_width=2)
        kb.add(
            InlineKeyboardButton(f"👤 نکست بازیکن: {'روشن' if s['allow_players_next'] else 'خاموش'}", callback_data=f"mgmt:{game['id']}:next_toggle:allow_players_next"),
            InlineKeyboardButton(f"🎩 نکست گرداننده: {'روشن' if s['allow_moderator_next'] else 'خاموش'}", callback_data=f"mgmt:{game['id']}:next_toggle:allow_moderator_next"),
            InlineKeyboardButton(f"🛡 ضداسپم: {'روشن' if s['anti_spam'] else 'خاموش'}", callback_data=f"mgmt:{game['id']}:next_toggle:anti_spam"),
            InlineKeyboardButton("⬅️ مدیریت", callback_data=f"mgmt:{game['id']}:open"),
        )
        await callback.message.edit_text("⏭ <b>مدیریت نکست</b>", parse_mode="HTML", reply_markup=kb); await callback.answer()

    async def next_toggle(self, callback: types.CallbackQuery):
        p = self._parse(callback, "next_toggle", 4)
        if not p: return
        gid = int(callback.message.chat.id); game = self._game(gid)
        if not game or not await self._allowed(callback, gid, game): await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        key = p[3]; s = dict(self._state(game).get("next_settings") or {}); s[key] = not bool(s.get(key, True)); self._save_state(game, next_settings=s)
        await callback.answer("⏭ تنظیم نکست ذخیره شد."); await self.next(callback)

    async def cancel(self, callback: types.CallbackQuery):
        gid = int(callback.message.chat.id); game = self._game(gid)
        if not game or not await self._allowed(callback, gid, game): await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        self.app.runtime.state.games.update_game(game["id"], status="finished", state={})
        task = getattr(getattr(self.app, "ui", None), "turn_timer_task", None)
        if task and not task.done(): task.cancel()
        lobby_id = (game.get("state") or {}).get("lobby_message_id")
        if lobby_id:
            try: await self.app.bot.edit_message_text("🚫 <b>این بازی لغو شد.</b>", gid, int(lobby_id), parse_mode="HTML", reply_markup=None)
            except Exception: pass
        await callback.message.edit_text("🚫 <b>بازی لغو شد.</b>", parse_mode="HTML"); await callback.answer("🚫 بازی لغو شد.")

    async def close(self, callback: types.CallbackQuery):
        await callback.message.delete(); await callback.answer("مدیریت بسته شد.")

    async def install(self):
        dp = self.app.dp
        # Registered before the production lobby so the management surface owns
        # the management action even when the game is already running.
        dp.register_callback_query_handler(self.open, lambda c: str(c.data or "").startswith("lobby:") and c.data.endswith(":management"), state="*")
        for action, fn in [
            ("event", self.event), ("event_delta", self.event_delta), ("event_input", self.event_input),
            ("scenario", self.scenario), ("scenario_pick", self.scenario_pick), ("moderator_pick", self.moderator_pick),
            ("remove", self.remove), ("remove_pick", self.remove_pick), ("unreserve", self.unreserve), ("unreserve_pick", self.unreserve_pick),
            ("replace", self.replace), ("replace_sub", self.replace_sub), ("replace_target", self.replace_target),
            ("attendance", self.attendance), ("attendance_toggle", self.attendance_toggle),
            ("birthday", self.birthday), ("birthday_pick", self.birthday_pick),
            ("challenge", self.challenge), ("challenge_toggle", self.challenge_toggle),
            ("next", self.next), ("next_toggle", self.next_toggle), ("cancel", self.cancel), ("close", self.close),
        ]:
            dp.register_callback_query_handler(fn, lambda c, a=action: str(c.data or "").startswith("mgmt:") and c.data.split(":")[2] == a, state="*")
        dp.register_callback_query_handler(lambda c: self.event_delta(c), lambda c: str(c.data or "").startswith("mgmt:") and c.data.split(":")[2] == "event_delta", state="*")
        dp.register_callback_query_handler(self.event_input, lambda c: str(c.data or "").startswith("mgmt:") and c.data.split(":")[2] == "event_input", state="*")
        dp.register_callback_query_handler(lambda c: self.open(c), lambda c: str(c.data or "").startswith("mgmt:") and c.data.split(":")[2] == "open", state="*")
        dp.register_message_handler(self.event_input_value, state=ManagementState.waiting_event_number)
