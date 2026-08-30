"""Telegram-facing adapter for the persistent game runtime.

The adapter is async at the Telegram boundary, but the current persistence
runtimes are synchronous.  Do not await their return values: this boundary is
where the two execution models are intentionally separated.
"""
from __future__ import annotations

from typing import Any

from runtime.game_runtime import PersistentGameRuntime


class RuntimeAdapter:
    """Small Telegram-compatible facade with no authoritative game state."""

    def __init__(self, runtime: PersistentGameRuntime):
        self.runtime = runtime

    async def snapshot(self, game_id: int) -> dict[str, Any]:
        return self.runtime.snapshot(game_id)

    async def recover(self, game_id: int) -> dict[str, Any]:
        return self.runtime.recover(game_id)

    async def join(self, game_id: int, player_id: int, **player: Any) -> Any:
        return self.runtime.join(game_id, player_id, **player)

    async def leave(self, game_id: int, player_id: int) -> Any:
        return self.runtime.leave(game_id, player_id)

    async def start_turn(self, game_id: int, turn_number: int, **kwargs: Any) -> Any:
        return self.runtime.start_turn(game_id, turn_number, **kwargs)

    async def finish_turn(self, turn_id: str, state: dict[str, Any] | None = None) -> Any:
        return self.runtime.finish_turn(turn_id, state)

    async def create_challenge(
        self,
        game_id: int,
        challenger_id: int,
        target_id: int,
        mode: str,
        **kwargs: Any,
    ) -> Any:
        return self.runtime.create_challenge(
            game_id, challenger_id, target_id, mode, **kwargs
        )

    async def resolve_challenge(
        self,
        game_id: int,
        challenge_id: str,
        status: str,
        **kwargs: Any,
    ) -> Any:
        return self.runtime.resolve_challenge(
            game_id, challenge_id, status, **kwargs
        )
