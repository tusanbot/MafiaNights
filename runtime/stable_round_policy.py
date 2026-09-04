"""Policy hooks for the single StableRoundEngine.

This module does not implement a second round engine. It only enforces two
state rules at the StableRoundEngine boundary:
1. pending mute selections become active before a new day builds its order;
2. a muted player cannot request a challenge during that day.
"""
from __future__ import annotations

import logging

from aiogram.dispatcher.handler import CancelHandler


def _handler(item):
    return getattr(item, "handler", None)


def _ensure_state(main):
    for key in ("_gm_muted_next_round", "_gm_muted_active", "_gm_extra_next_round"):
        value = getattr(main, key, None)
        if not isinstance(value, set):
            setattr(main, key, set(value or []))


def _find(registry, name):
    for item in list(registry or []):
        fn = _handler(item)
        if getattr(fn, "__name__", "") == name:
            return item, fn
    return None, None


def install(main):
    if getattr(main, "_stable_round_policy_installed", False):
        return False
    registry = getattr(getattr(main.dp, "callback_query_handlers", None), "handlers", None)
    if registry is None:
        return False

    _ensure_state(main)
    start_item, start_fn = _find(registry, "start_round")
    challenge_item, challenge_fn = _find(registry, "challenge_request")
    if start_fn is None or challenge_fn is None:
        logging.warning("stable round policy: authoritative handlers not found")
        return False

    async def start_round_with_policy(callback):
        _ensure_state(main)
        # Mute selected during the previous day is consumed exactly at the
        # beginning of this day, before StableRoundEngine freezes the order.
        main._gm_muted_active = set(main._gm_muted_next_round)
        main._gm_muted_next_round.clear()
        return await start_fn(callback)

    start_round_with_policy.__name__ = "start_round"
    start_round_with_policy._stable_round_policy = True
    start_round_with_policy._original = start_fn

    async def challenge_request_with_policy(callback):
        _ensure_state(main)
        try:
            target = int(str(callback.data).split("_", 2)[2])
        except Exception:
            return await challenge_fn(callback)
        requester_seat = None
        for seat, uid in (getattr(main, "player_slots", {}) or {}).items():
            if int(uid) == int(callback.from_user.id):
                requester_seat = int(seat)
                break
        if requester_seat in main._gm_muted_active:
            await callback.answer("⛔ بازیکن ساکت نمی‌تواند درخواست چالش بدهد.", show_alert=True)
            raise CancelHandler()
        return await challenge_fn(callback)

    challenge_request_with_policy.__name__ = "challenge_request"
    challenge_request_with_policy._stable_round_policy = True
    challenge_request_with_policy._original = challenge_fn

    start_item.handler = start_round_with_policy
    challenge_item.handler = challenge_request_with_policy
    main._stable_round_policy_installed = True
    logging.info("Stable round policy installed: pending mute -> active day state; muted challenge blocked")
    return True
