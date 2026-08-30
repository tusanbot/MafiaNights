"""Final compatibility aliases for legacy lobby/seat callbacks."""
from __future__ import annotations

import html

from aiogram import types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from runtime.feature_parity_v3 import FeatureParityV3


class FeatureParityV4(FeatureParityV3):
    async def legacy_join(self, callback: types.CallbackQuery):
        # Reuse the authoritative clean join implementation.
        await self.app.join(callback)

    async def legacy_leave(self, callback: types.CallbackQuery):
        await self.app.leave(callback)

    async def slot(self, callback: types.CallbackQuery):
        group_id = callback.message.chat.id
        seat = int(callback.data.rsplit("_", 1)[1])
        game = self._game(group_id)
        if not game or game.get("status") != "lobby":
            await callback.answer("⚠️ لابی فعال نیست.", show_alert=True)
            return
        rows = self.app._players_by_seat(group_id)
        uid = int(callback.from_user.id)
        current = next((s for s, row in rows.items() if int(row["player_id"]) == uid), None)
        if current == seat:
            self.app.runtime.lobby.leave(group_id, uid)
            await callback.answer("جایگاه آزاد شد.")
        elif seat in rows:
            await callback.answer("❌ این صندلی قبلاً رزرو شده است.", show_alert=True)
            return
        else:
            if current is not None:
                self.app.runtime.lobby.leave(group_id, uid)
            self.app.runtime.lobby.join(group_id, uid, seat)
            await callback.answer(f"✅ صندلی {seat} برای شما رزرو شد.")
        await self.app._render_lobby(group_id)

    async def waiting_join(self, callback: types.CallbackQuery):
        group_id = callback.message.chat.id
        uid = int(callback.from_user.id)
        rows = self.app._players_by_seat(group_id)
        if any(int(row["player_id"]) == uid for row in rows.values()):
            await callback.answer("❌ شما در لیست اصلی هستید.", show_alert=True)
            return
        subs = self._substitutes(group_id)
        if str(uid) not in subs:
            subs[str(uid)] = {"id": uid, "name": callback.from_user.full_name}
            await self._save_state(group_id, substitutes=subs)
            await callback.answer("📌 شما به لیست رزرو اضافه شدید.")
        else:
            await callback.answer("⚠️ شما قبلاً در لیست رزرو هستید.", show_alert=True)

    async def waiting_leave(self, callback: types.CallbackQuery):
        group_id = callback.message.chat.id
        uid = str(callback.from_user.id)
        subs = self._substitutes(group_id)
        if subs.pop(uid, None):
            await self._save_state(group_id, substitutes=subs)
            await callback.answer("✅ از لیست رزرو خارج شدید.")
        else:
            await callback.answer("⚠️ شما در لیست رزرو نیستید.", show_alert=True)

    async def toggle_challenge_legacy(self, callback: types.CallbackQuery):
        await self.app.toggle_challenge(callback)

    def register(self):
        super().register()
        dp = self.app.dp
        dp.register_callback_query_handler(self.legacy_join, lambda c: c.data == "join_game")
        dp.register_callback_query_handler(self.legacy_leave, lambda c: c.data == "leave_game")
        dp.register_callback_query_handler(self.slot, lambda c: c.data.startswith("slot_"))
        dp.register_callback_query_handler(self.waiting_join, lambda c: c.data in {"join_waiting", "reserve_waiting"})
        dp.register_callback_query_handler(self.waiting_leave, lambda c: c.data in {"leave_waiting", "cancel_waiting"})
        dp.register_callback_query_handler(self.toggle_challenge_legacy, lambda c: c.data == "challenge_toggle")
