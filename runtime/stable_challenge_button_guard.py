"""Prevent stale challenge buttons after a player has already challenged."""
from __future__ import annotations

import logging


def install(app):
    if getattr(app, "_stable_challenge_button_guard_installed", False):
        return False
    handlers = getattr(getattr(app.dp, "callback_query_handlers", None), "handlers", None)
    if handlers is None:
        return False
    for item in handlers:
        fn = getattr(item, "handler", None)
        if getattr(fn, "__name__", "") != "challenge_request":
            continue
        original = fn
        if getattr(original, "_stable_wrapped", False):
            app._stable_challenge_button_guard_installed = True
            return True

        async def guarded(callback):
            try:
                data = str(callback.data or "")
                target_seat = int(data.split("_", 2)[2])
                challenger_uid = int(callback.from_user.id)
                slots = getattr(app, "player_slots", {}) or {}
                challenger_seat = next((int(s) for s, uid in slots.items() if int(uid) == challenger_uid), None)
                used = getattr(app, "_stable_challenge_used", set())
                locked = getattr(app, "_stable_challenge_locked", set())
                if challenger_uid in used or (challenger_seat is not None and challenger_seat in locked):
                    await callback.answer("❌ شما در این دور قبلاً چالش داده‌اید.", show_alert=True)
                    return
                # Lock immediately, before the original handler renders any
                # subsequent turn keyboard. This prevents stale challenge UI.
                used.add(challenger_uid)
                if challenger_seat is not None:
                    locked.add(challenger_seat)
                return await original(callback)
            except Exception:
                raise

        guarded.__name__ = "challenge_request"
        guarded._stable_wrapped = True
        item.handler = guarded
        logging.info("Stable challenge button guard installed")
        app._stable_challenge_button_guard_installed = True
        return True
    logging.warning("Stable challenge button guard: challenge handler not found")
    return False
