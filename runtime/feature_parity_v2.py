"""Hardened feature-parity layer.

Builds on ``runtime.feature_parity`` while fixing callback parsing and adding
an explicit challenge-status view. No new module-level game state is added.
"""
from __future__ import annotations

import html
from typing import Any

from aiogram import types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from runtime.feature_parity import FeatureParity as BaseFeatureParity
from runtime.feature_parity import AddScenarioParity


class FeatureParityV2(BaseFeatureParity):
    async def challenge_status(self, callback: types.CallbackQuery):
        group_id = self.app.ui.group_chat_id
        if not group_id or not await self._is_admin(callback, group_id):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
            return
        state = self._state(group_id)
        pending = state.get("challenge_requests") or {}
        after = state.get("pending_challenges") or {}
        active = self.app.runtime.challenges.active(group_id)
        lines = ["⚔ <b>وضعیت چالش</b>", ""]
        lines.append(f"درخواست‌های در انتظار: {sum(len(v or {}) for v in pending.values())}")
        lines.append(f"چالش‌های بعد از صحبت: {len(after)}")
        lines.append(f"چالش فعال: {len(active)}")
        await callback.message.answer("\n".join(lines), parse_mode="HTML")
        await callback.answer()

    async def challenge_response(self, callback: types.CallbackQuery):
        """Accept both new fp:* callbacks and legacy accept_* callbacks."""
        group_id = callback.message.chat.id
        data = callback.data or ""
        if data.startswith("fp:accept:"):
            parts = data.split(":")
            if len(parts) != 5:
                await callback.answer("⚠️ داده چالش نامعتبر.", show_alert=True)
                return
            _, _, timing, challenger_text, target_text = parts
            action = "accept"
            challenger = int(challenger_text)
            target = int(target_text)
        elif data.startswith("fp:reject:"):
            parts = data.split(":")
            if len(parts) != 4:
                await callback.answer("⚠️ داده چالش نامعتبر.", show_alert=True)
                return
            _, _, challenger_text, target_text = parts
            action = "reject"
            timing = None
            challenger = int(challenger_text)
            target = int(target_text)
        else:
            parts = data.split("_")
            if parts[0] == "reject" and len(parts) == 3:
                action, timing = "reject", None
                challenger, target = int(parts[1]), int(parts[2])
            elif parts[0] == "accept" and len(parts) == 4 and parts[1] in {"before", "after"}:
                action, timing = "accept", parts[1]
                challenger, target = int(parts[2]), int(parts[3])
            else:
                await callback.answer("⚠️ داده چالش نامعتبر.", show_alert=True)
                return

        if int(callback.from_user.id) not in {target, self._moderator_id(group_id)}:
            await callback.answer("⛔ فقط صاحب نوبت یا گرداننده.", show_alert=True)
            return

        rows = self.app._players_by_seat(group_id)
        target_seat = next((seat for seat, row in rows.items() if int(row["player_id"]) == target), None)
        challenger_seat = next((seat for seat, row in rows.items() if int(row["player_id"]) == challenger), None)
        if target_seat is None:
            await callback.answer("⚠️ صندلی هدف پیدا نشد.", show_alert=True)
            return

        state = self._state(group_id)
        pending = dict(state.get("challenge_requests") or {})
        bucket = dict(pending.get(str(target_seat)) or {})
        bucket.pop(str(challenger), None)
        pending[str(target_seat)] = bucket

        if action == "reject":
            await self._save_state(group_id, challenge_requests=pending)
            await callback.message.edit_reply_markup(reply_markup=None)
            await self.app.bot.send_message(group_id, f"🚫 {html.escape(self.app._name(target))} درخواست چالش را رد کرد.")
            await callback.answer()
            return

        if timing == "after":
            after = dict(state.get("pending_challenges") or {})
            after[str(target_seat)] = challenger
            await self._save_state(group_id, challenge_requests=pending, pending_challenges=after)
            await callback.message.edit_reply_markup(reply_markup=None)
            await self.app.bot.send_message(group_id, f"⚔ چالش بعد از صحبت برای {html.escape(self.app._name(target))} ثبت شد.")
            await callback.answer()
            return

        if timing != "before" or challenger_seat is None:
            await callback.answer("⚠️ چالش‌کننده صندلی ندارد.", show_alert=True)
            return

        current = self.app.runtime.current_turn(group_id)
        paused = dict(state.get("paused_turn") or {})
        if current:
            paused = {
                "turn_id": str(current["id"]),
                "seat": int(current.get("seat") or target_seat),
                "duration": int(current.get("duration_seconds") or 120),
            }
            self.app.runtime.finish_turn(str(current["id"]), {"finish_reason": "challenge_before"})
            if self.app.ui.turn_timer_task and not self.app.ui.turn_timer_task.done():
                self.app.ui.turn_timer_task.cancel()

        await self._save_state(group_id, challenge_requests=pending, paused_turn=paused, challenge_mode=True)
        await callback.message.edit_reply_markup(reply_markup=None)
        await self.app.start_turn(group_id, challenger_seat, self.app._current_index(group_id), challenge=True)
        await callback.answer("⚔ چالش قبل از صحبت شروع شد.")

    def register(self):
        # Reuse the complete base registration, but intentionally register our
        # corrected challenge handlers after it with distinct fp: callbacks.
        super().register()
        dp = self.app.dp
        dp.register_callback_query_handler(self.challenge_status, lambda c: c.data == "fp:challenge_status")
        dp.register_callback_query_handler(self.challenge_status, lambda c: c.data == "challenge_status")
        dp.register_callback_query_handler(self.challenge_response, lambda c: c.data.startswith("fp:accept:") or c.data.startswith("fp:reject:") or c.data.startswith("accept_before_") or c.data.startswith("accept_after_") or c.data.startswith("reject_"))
