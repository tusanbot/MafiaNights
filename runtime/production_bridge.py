"""Production bootstrap bridge for the persistent game runtime.

This module lets the migration branch activate persistence without rewriting
main.py in one risky operation. It installs the existing turn/challenge
cut-over wrappers, attaches one shared PersistentGameRuntime to the legacy
module, and runs restart recovery from the production entry point.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from runtime.game_runtime import PersistentGameRuntime
from runtime.migration_adapter import MigrationAdapter
from runtime.startup_recovery import recover_persisted_games
from runtime.turn_cutover import install_legacy_turn_cutover


def install(main_module: Any) -> dict[str, Any]:
    """Attach one persistent runtime and install the safe legacy cut-over."""
    runtime = PersistentGameRuntime()
    adapter = MigrationAdapter(game_runtime=runtime)

    main_module.persistent_runtime = runtime
    main_module._migration_adapter = adapter
    main_module._persistent_challenge_runtime = runtime.challenges

    cutover = install_legacy_turn_cutover(main_module, adapter)
    return {"runtime": runtime, "adapter": adapter, "cutover": cutover}


async def recover_and_hydrate(main_module: Any) -> list[dict[str, Any]]:
    """Recover active games and hydrate only ephemeral legacy handles/state."""
    runtime = getattr(main_module, "persistent_runtime", None)
    if runtime is None:
        runtime = PersistentGameRuntime()
        main_module.persistent_runtime = runtime

    results = await recover_persisted_games(main_module)

    allowed_group = getattr(main_module, "ALLOWED_GROUP_ID", None)
    if allowed_group is None:
        return results

    try:
        snapshot = runtime.snapshot(int(allowed_group))
        game = snapshot.get("game")
        if not game:
            return results

        # These globals are UI/session context, not persistence truth. Hydrate
        # them from DB so the legacy UI can continue rendering after restart.
        main_module.group_chat_id = int(game["group_chat_id"])
        main_module.moderator_id = game.get("moderator_id")
        main_module.game_running = game.get("status") in {"running", "paused"}
        main_module.lobby_active = game.get("status") == "lobby"
        main_module.current_turn_index = int(game.get("current_turn_index") or 0)

        players = snapshot.get("players") or []
        slots = {}
        for row in players:
            player_id = row.get("player_id")
            seat = row.get("seat")
            if player_id is None:
                continue
            if seat is not None:
                slots[int(seat)] = int(player_id)
            try:
                name = row.get("nickname") or row.get("first_name") or row.get("username") or str(player_id)
                main_module.players[int(player_id)] = name
            except Exception:
                pass
        main_module.player_slots = slots

        turn = snapshot.get("turn")
        if turn:
            main_module.current_turn_index = int(turn.get("current_turn_index") or game.get("current_turn_index") or 0)

        pending = snapshot.get("challenge")
        main_module.challenge_mode = bool(pending)
        main_module.pending_challenges = {str(row.get("id")): row for row in (pending or [])}

    except Exception:
        logging.exception("legacy state hydration failed during startup")

    return results


async def startup(main_module: Any, original_startup: Any) -> list[dict[str, Any]]:
    """Run the original Telegram startup and then persistent recovery."""
    if original_startup is not None:
        await original_startup(main_module.dp)
    return await recover_and_hydrate(main_module)
