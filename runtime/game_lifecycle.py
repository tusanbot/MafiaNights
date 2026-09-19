"""Canonical lifecycle cleanup for MafiaNights games.

A terminal game (finished or cancelled) must never keep the process-level
running flags alive.  This module centralizes that invariant and keeps
cancellation distinct from normal game completion.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any


TERMINAL_STATUSES = {"finished", "cancelled"}


def _stop_tasks(app: Any) -> None:
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
                logging.exception("failed to cancel lifecycle task %s", attr)


def _clear_runtime_flags(app: Any) -> None:
    # These flags are only process-local UI/runtime state.  The database game
    # status is authoritative and must be terminal before this is called.
    app.game_running = False
    app.round_active = False
    app.lobby_active = False
    app._stable_day_active = False
    app._stable_day_ended = False
    app._stable_phase = "normal"
    app.current_turn_index = 0
    app.current_turn_seat = None
    app.turn_order = []
    app.player_slots = {}
    app.pending_challenges = {}
    app.active_challenger_seats = set()
    _stop_tasks(app)


def install(app: Any, management: Any) -> bool:
    if getattr(app, "_canonical_game_lifecycle_installed", False):
        return False

    # The management panel's cancel action used to write status="finished".
    # Replace that action before GameManagement.install() registers its
    # callback, so cancellation is durably distinct from normal completion.
    async def cancel(callback):
        gid = int(callback.message.chat.id)
        game = management._game(gid)
        if not game or not await management._allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
            return

        status = str(game.get("status") or "")
        if status not in {"lobby", "running", "paused", "turn"}:
            await callback.answer("ℹ️ این بازی دیگر فعال نیست.", show_alert=True)
            return

        state = dict(game.get("state") or {})
        state["cancelled"] = True
        state["cancelled_at"] = datetime.now(timezone.utc).isoformat()
        state["cancelled_from_status"] = status
        state["cancel_reason"] = "management"

        ok = app.runtime.state.games.update_game(
            game["id"],
            status="cancelled",
            state=state,
            finished_at=datetime.now(timezone.utc),
        )
        if not ok:
            await callback.answer("❌ لغو بازی انجام نشد.", show_alert=True)
            return

        lid = state.get("lobby_message_id")
        if lid:
            try:
                await app.bot.edit_message_text(
                    "🚫 <b>این بازی لغو شد.</b>\n\nبازی لغوشده در بایگانی نگهداری شد و دیگر بازی فعال محسوب نمی‌شود.",
                    gid,
                    int(lid),
                    parse_mode="HTML",
                    reply_markup=None,
                )
            except Exception:
                logging.info("cancelled game message could not be edited game=%s", game.get("id"))

        _clear_runtime_flags(app)
        await callback.message.edit_text(
            f"🚫 <b>بازی شماره {int(game.get('event_number') or 1)} لغو شد.</b>\n\n"
            "این بازی دیگر فعال نیست و می‌توانید بازی جدید را شروع کنید.",
            parse_mode="HTML",
        )
        await callback.answer("🚫 بازی لغو شد.")

    management.cancel = cancel.__get__(management, type(management))

    # Any existing completion path (game_end, voting-end, legacy handlers, …)
    # that writes a terminal status automatically clears the process-local
    # flags.  This makes the invariant independent of which UI ended the game.
    games = app.runtime.state.games
    original_update_game = games.update_game

    def update_game(game_id, **changes):
        result = original_update_game(game_id, **changes)
        status = str(changes.get("status") or "").lower()
        if result and status in TERMINAL_STATUSES:
            _clear_runtime_flags(app)
        return result

    games.update_game = update_game

    app._canonical_game_lifecycle_installed = True
    logging.info("CANONICAL_GAME_LIFECYCLE installed: finished/cancelled are terminal")
    return True
