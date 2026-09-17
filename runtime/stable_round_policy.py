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


def _hydrate_persisted_controls(main):
    """Load management selections from DB before a new day starts.

    Vercel may recreate the Python process between Telegram updates, so the
    in-memory sets used by StableRoundEngine cannot be the only source.
    """
    try:
        gid = int(getattr(main, "group_chat_id", 0) or 0)
        game = main.runtime.state.active_game(gid)
        if not game:
            return
        state = dict(game.get("state") or {})
        main._gm_muted_next_round = set(int(x) for x in (state.get("muted_next_round_seats") or []))
        main._gm_extra_next_round = set(int(x) for x in (state.get("extra_turn_seats") or []))
    except Exception:
        logging.exception("stable round policy: persisted management controls could not be loaded")


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
        main.group_chat_id = int(callback.message.chat.id)
        _hydrate_persisted_controls(main)
        if (
            callback.message
            and callback.message.chat.type in {"group", "supergroup"}
            and int(callback.from_user.id) == int(getattr(main, "moderator_id", -1) or -1)
            and getattr(main, "game_running", False)
            and not getattr(main, "_stable_day_active", False)
        ):
            main._gm_muted_active = set(main._gm_muted_next_round)
            main._gm_muted_next_round.clear()
        return await start_fn(callback)

    start_round_with_policy.__name__ = "start_round"
    start_round_with_policy._stable_round_policy = True
    start_round_with_policy._original = start_fn

    async def challenge_request_with_policy(callback):
        _ensure_state(main)
        try:
            requester_seat = next(
                int(seat) for seat, uid in (getattr(main, "player_slots", {}) or {}).items()
                if int(uid) == int(callback.from_user.id)
            )
        except StopIteration:
            requester_seat = None
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

    try:
        from runtime.voting_runtime import install as install_voting_runtime
        install_voting_runtime(main)
    except Exception:
        logging.exception("stable round policy: failed to install voting runtime")
        raise

    logging.info("Stable round policy installed: persisted mute/extra controls + day policy")
    return True
