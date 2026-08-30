"""Compatibility cut-over for legacy day/night callbacks.

The legacy callbacks remain responsible for Telegram presentation and role
logic. This boundary makes the day/night transition durable first, then lets
the existing callback continue. Day counters, phase and turn-reset metadata
therefore survive process restarts without copying Telegram message/task state
into persistence.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from runtime.game_runtime import PersistentGameRuntime


def _group_id(legacy: Any) -> int | None:
    value = getattr(legacy, "group_chat_id", None)
    return int(value) if value else None


def _sync_legacy_day(legacy: Any, runtime: PersistentGameRuntime, group_id: int) -> dict[str, Any]:
    snapshot = runtime.day_snapshot(group_id)
    legacy.day_number = int(snapshot.get("day") or 0)
    legacy.day_phase = snapshot.get("phase")
    legacy.current_turn_index = 0
    legacy.turn_order = []
    return snapshot


def persist_day_transition(legacy: Any, *, phase: str) -> dict[str, Any] | None:
    group_id = _group_id(legacy)
    runtime = getattr(legacy, "persistent_runtime", None)
    if not group_id or runtime is None:
        return None

    if phase == "day":
        result = runtime.start_new_day(group_id, extra={
            "turn_order": [],
            "current_turn_index": 0,
            "challenge_requests": {},
            "pending_challenges": {},
            "challenge_mode": False,
            "post_challenge_advance": False,
            "migration_day_transition": True,
        })
    else:
        result = runtime.start_night(group_id, extra={
            "challenge_requests": {},
            "pending_challenges": {},
            "challenge_mode": False,
            "post_challenge_advance": False,
            "migration_day_transition": True,
        })
    _sync_legacy_day(legacy, runtime, group_id)
    return result


def _replace_callback(dp: Any, function_names: tuple[str, ...], replacement_factory: Callable[[Any, Any], Any]) -> bool:
    handlers = getattr(getattr(dp, "callback_query_handlers", None), "handlers", None)
    if handlers is None:
        return False
    replaced = False
    for item in handlers:
        callback = getattr(item, "callback", None)
        if callback is None and isinstance(item, dict):
            callback = item.get("callback")
        if getattr(callback, "__name__", None) not in function_names:
            continue
        if getattr(callback, "_persistent_day_bridge", False):
            replaced = True
            continue
        wrapper = replacement_factory(callback, item)
        if hasattr(item, "callback"):
            item.callback = wrapper
        elif isinstance(item, dict):
            item["callback"] = wrapper
        replaced = True
    return replaced


def install_legacy_day_cutover(legacy: Any, runtime: PersistentGameRuntime) -> dict[str, Any]:
    """Install persistent day/night transition wrappers exactly once."""
    existing = getattr(legacy, "_persistent_day_cutover", None)
    if existing is not None:
        return existing

    result = {"start_new_day": False, "start_night": False, "reset_round_data": False}
    dp = getattr(legacy, "dp", None)

    def make_transition(function_name: str, phase: str):
        original = getattr(legacy, function_name, None)
        if original is None:
            return False
        if getattr(original, "_persistent_day_bridge", False):
            return True

        async def wrapper(*args, **kwargs):
            try:
                persist_day_transition(legacy, phase=phase)
            except Exception:
                logging.exception("persistent %s transition failed", phase)
                raise
            return await original(*args, **kwargs)

        wrapper.__name__ = function_name
        wrapper._persistent_day_bridge = True
        wrapper._legacy_original = original
        setattr(legacy, function_name, wrapper)

        if dp is not None:
            _replace_callback(dp, (function_name,), lambda _callback, _item: wrapper)
        return True

    result["start_new_day"] = make_transition("start_new_day", "day")
    result["start_night"] = make_transition("start_night", "night")

    original_reset = getattr(legacy, "reset_round_data", None)
    if original_reset is not None and not getattr(original_reset, "_persistent_day_bridge", False):
        def reset_round_data(*args, **kwargs):
            return original_reset(*args, **kwargs)
        reset_round_data._persistent_day_bridge = True
        reset_round_data._legacy_original = original_reset
        legacy.reset_round_data = reset_round_data
        result["reset_round_data"] = True

    legacy._persistent_day_cutover = {"runtime": runtime, "cutover": result}
    return legacy._persistent_day_cutover
