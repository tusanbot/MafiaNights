"""Canonical post-voting phase transition authority.

Owns the explicit night -> next-day transition after voting. Legacy main1
handlers are removed from the Production callback registry; durable game state
is the authority and compatibility globals are updated only as derived cache.
"""
from __future__ import annotations

import logging
from typing import Any

from aiogram import types
from aiogram.dispatcher.handler import CancelHandler
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def _game(app, gid: int):
    try:
        return app.runtime.state.games.get_game(app.runtime.state.active_game(gid)["id"])
    except Exception:
        return None


def _moderator_allowed(callback: types.CallbackQuery, game: dict[str, Any]) -> bool:
    try:
        return int(callback.from_user.id) == int(game.get("moderator_id") or 0)
    except Exception:
        return False


def _phase(game: dict[str, Any]) -> str:
    return str((game.get("state") or {}).get("round_phase") or "").strip().lower()


def install(app: Any) -> bool:
    if getattr(app, "_phase_transition_authority_installed", False):
        return False
    dp = app.dp
    registry = getattr(getattr(dp, "callback_query_handlers", None), "handlers", [])

    async def start_night(callback: types.CallbackQuery):
        if callback.message and callback.message.chat.type == "private":
            await callback.answer("این عملیات فقط داخل گروه انجام می‌شود.", show_alert=True)
            raise CancelHandler()
        gid = int(callback.message.chat.id)
        game = _game(app, gid)
        if not game or str(game.get("status") or "") not in {"running", "paused", "turn"}:
            await callback.answer("❌ بازی فعال نیست.", show_alert=True)
            raise CancelHandler()
        if not _moderator_allowed(callback, game):
            await callback.answer("⛔ فقط گرداننده می‌تواند فاز شب را شروع کند.", show_alert=True)
            raise CancelHandler()
        state = dict(game.get("state") or {})
        round_phase = _phase(game)
        voting = state.get("voting") or {}
        # A stale "start night" button must never skip the current day.
        # Voting state alone is insufficient because an old Telegram message
        # can survive into a later phase.
        if round_phase not in {"day_finished", "voting", ""}:
            await callback.answer("⚠️ ابتدا فاز روز و رأی‌گیری را به پایان برسانید.", show_alert=True)
            raise CancelHandler()
        if voting and str(voting.get("phase") or "") not in {"round_finished", "finished", ""}:
            await callback.answer("⚠️ ابتدا رأی‌گیری را به پایان برسانید.", show_alert=True)
            raise CancelHandler()
        state["round_phase"] = "night"
        state["night_started"] = True
        state["night_started_at"] = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
        state["stable_day_active"] = False
        state["stable_day_ended"] = True
        # A night transition is a hard lifecycle boundary. Pending/active
        # challenge runtime belongs to the finished day and must never be
        # resurrected by a NEXT callback that lands on a fresh Vercel worker.
        state.pop("challenge_requests", None)
        state.pop("challenge_runtime", None)
        if not app.runtime.state.games.update_game(game["id"], state=state):
            await callback.answer("❌ ثبت فاز شب انجام نشد.", show_alert=True)
            raise CancelHandler()
        try:
            app.turn_round_authority.persist_position(gid, index=0, seat=None, extra_state={"stable_day_active": False, "stable_day_ended": True})
        except Exception:
            logging.exception("phase transition: failed to persist night turn state")
        await callback.message.edit_text(
            "🌙 <b>فاز شب شروع شد.</b>\n\nوقتی آماده بودید، روز جدید را شروع کنید.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(row_width=1).add(
                InlineKeyboardButton("🌞 شروع روز جدید", callback_data="start_new_day")
            ),
        )
        await callback.answer("🌙 فاز شب شروع شد.")
        raise CancelHandler()

    async def start_new_day(callback: types.CallbackQuery):
        if callback.message and callback.message.chat.type == "private":
            await callback.answer("این عملیات فقط داخل گروه انجام می‌شود.", show_alert=True)
            raise CancelHandler()
        gid = int(callback.message.chat.id)
        game = _game(app, gid)
        if not game or str(game.get("status") or "") not in {"running", "paused", "turn"}:
            await callback.answer("❌ بازی فعال نیست.", show_alert=True)
            raise CancelHandler()
        if not _moderator_allowed(callback, game):
            await callback.answer("⛔ فقط گرداننده می‌تواند روز جدید را شروع کند.", show_alert=True)
            raise CancelHandler()
        state = dict(game.get("state") or {})
        phase = _phase(game)
        if phase not in {"night", ""}:
            await callback.answer("⚠️ ابتدا فاز شب را شروع کنید.", show_alert=True)
            raise CancelHandler()
        day_no = max(1, int(state.get("day_number") or state.get("current_day") or 1))
        if phase == "night":
            day_no += 1
        state["day_number"] = day_no
        state["current_day"] = day_no
        state["round_phase"] = "day_setup"
        state["stable_day_active"] = False
        state["stable_day_ended"] = False
        state.pop("head_seat", None)
        state.pop("voting", None)
        # Reset all durable challenge state from the previous day as part of
        # the new-day boundary. Otherwise a stale callback can revive an old
        # challenge/request after the day has been reset.
        state.pop("challenge_requests", None)
        state.pop("challenge_runtime", None)
        state["last_day_started_at"] = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
        if not app.runtime.state.games.update_game(game["id"], state=state):
            await callback.answer("❌ شروع روز جدید ثبت نشد.", show_alert=True)
            raise CancelHandler()
        app.current_turn_index = 0
        app.current_turn_seat = None
        app.turn_order = []
        app._stable_day_active = False
        app._stable_day_ended = False
        app._stable_phase = "normal"
        app.pending_challenges = {}
        app.active_challenger_seats = set()
        try:
            app.turn_round_authority.persist_position(gid, order=[], index=0, seat=None, extra_state={"stable_day_active": False, "stable_day_ended": False})
        except Exception:
            logging.exception("phase transition: failed to persist new-day turn reset")
        await callback.message.edit_text(
            f"🌞 <b>روز {day_no} شروع شد!</b>\n\nسر صحبت را انتخاب کنید:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(row_width=1).add(
                InlineKeyboardButton("🎩 انتخاب سردست", callback_data=f"day:{int(game['id'])}:head"),
                InlineKeyboardButton("⚔ چالش روشن", callback_data="challenge_toggle"),
                InlineKeyboardButton("▶️ شروع دور", callback_data="start_round"),
            ),
        )
        await callback.answer("🌞 روز جدید شروع شد.")
        raise CancelHandler()

    # Remove legacy owners before registering the canonical handlers.
    legacy_names = {"start_night", "start_new_day"}
    registry[:] = [item for item in registry if getattr(getattr(item, "handler", None), "__name__", "") not in legacy_names]
    dp.register_callback_query_handler(start_night, lambda c: str(c.data or "") == "start_night", state="*")
    dp.register_callback_query_handler(start_new_day, lambda c: str(c.data or "") == "start_new_day", state="*")
    ours = [x for x in list(registry) if getattr(getattr(x, "handler", None), "__name__", "") in legacy_names]
    for item in reversed(ours):
        try: registry.remove(item)
        except ValueError: pass
        registry.insert(0, item)
    app._phase_transition_authority_installed = True
    logging.info("PHASE TRANSITION AUTHORITY active: voting->night->next-day")
    return True
