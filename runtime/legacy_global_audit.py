"""Audit legacy main-module state after the persistence cut-over.

The audit distinguishes compatibility names that may temporarily exist in
``main`` from mutable containers that must never be treated as durable truth.
It is intentionally runtime-safe: it does not mutate the bot state.
"""
from __future__ import annotations

from typing import Any


FORBIDDEN_MUTABLE_CONTAINERS = {
    "players",
    "turn_order",
    "player_slots",
    "pending_challenges",
    "challenge_requests",
    "active_challenger_seats",
    "players_in_game",
    "waiting_list",
    "extra_turns",
}

ALLOWED_EPHEMERAL_NAMES = {
    "game_message_id",
    "lobby_message_id",
    "current_turn_message_id",
    "turn_timer_task",
    "waiting_message_id",
    "last_next_time",
}


def inspect_module(main_module: Any) -> dict[str, Any]:
    """Return an audit report without changing module state."""
    namespace = vars(main_module)
    present = sorted(name for name in FORBIDDEN_MUTABLE_CONTAINERS if name in namespace)
    return {
        "legacy_container_names_present": present,
        "legacy_container_count": len(present),
        "ephemeral_names_present": sorted(name for name in ALLOWED_EPHEMERAL_NAMES if name in namespace),
        "source_of_truth": "persistent_runtime",
        "authoritative": False,
    }


def assert_not_authoritative(main_module: Any) -> None:
    """Fail only if a caller explicitly marks a legacy container authoritative."""
    report = inspect_module(main_module)
    if getattr(main_module, "LEGACY_GLOBALS_ARE_AUTHORITATIVE", False):
        raise AssertionError(
            "Legacy mutable globals must not be marked authoritative; use PersistentGameRuntime."
        )
    main_module.LEGACY_GLOBAL_AUDIT = report
