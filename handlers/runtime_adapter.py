"""Telegram-facing adapter for the persistent game runtime.

This module intentionally contains no authoritative game state.  Telegram
handlers can use it as a narrow compatibility boundary while the legacy
handlers are migrated out of main.py.
"""
from __future__ import annotations

from typing import Any

from runtime.game_runtime import PersistentGameRuntime


class RuntimeAdapter:
    """Small facade intended to replace direct global-state mutations."""

    def __init__(self, runtime: PersistentGameRuntime):
        self.runtime = runtime

    async def snapshot(self, game_id: str) -> dict[str, Any]:
        return await self.runtime.snapshot(game_id)

    async def recover(self, game_id: str) -> dict[str, Any]:
        return await self.runtime.recover(game_id)

    async def join(self, game_id: str, player_id: str, **player: Any) -> Any:
        return await self.runtime.join(game_id, player_id, **player)

    async def leave(self, game_id: str, player_id: str) -> Any:
        return await self.runtime.leave(game_id, player_id)

    async def start_turn(self, game_id: str, seat: int, duration_seconds: int) -> Any:
        return await self.runtime.start_turn(game_id, seat, duration_seconds)

    async def finish_turn(self, game_id: str, turn_id: str) -> Any:
        return await self.runtime.finish_turn(game_id, turn_id)

    async def create_challenge(self, game_id: str, challenger_id: str, target_id: str, mode: str) -> Any:
        return await self.runtime.create_challenge(game_id, challenger_id, target_id, mode)

    async def resolve_challenge(self, game_id: str, challenge_id: str, status: str) -> Any:
        return await self.runtime.resolve_challenge(game_id, challenge_id, status)
