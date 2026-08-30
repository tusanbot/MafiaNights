"""Compatibility adapter used while migrating legacy Telegram handlers.

The adapter is intentionally small: legacy handlers can call this boundary
without becoming authoritative owners of persisted game/turn state.
"""
from __future__ import annotations

from typing import Any, Optional

from runtime.game_runtime import PersistentGameRuntime
from runtime.turn_runtime import PersistentTurnRuntime


class MigrationAdapter:
    """Bridge legacy Telegram callbacks to the persistent runtimes."""

    def __init__(
        self,
        game_runtime: Optional[PersistentGameRuntime] = None,
        turn_runtime: Optional[PersistentTurnRuntime] = None,
    ) -> None:
        self.game_runtime = game_runtime or PersistentGameRuntime()
        self.turn_runtime = turn_runtime or PersistentTurnRuntime()

    def start_first_turn(
        self,
        group_chat_id: int,
        *,
        turn_number: int = 1,
        seat: Optional[int] = None,
        player_id: Optional[int] = None,
        turn_type: str = "main",
        duration_seconds: Optional[int] = None,
        current_turn_index: Optional[int] = None,
        state: Optional[dict[str, Any]] = None,
    ) -> Any:
        """Start the first persisted turn for a running game."""
        return self.game_runtime.start_first_turn(
            group_chat_id,
            turn_number=turn_number,
            seat=seat,
            player_id=player_id,
            turn_type=turn_type,
            duration_seconds=duration_seconds,
            current_turn_index=current_turn_index,
            state=state,
        )

    def current_turn(self, group_chat_id: int) -> Any:
        return self.turn_runtime.current(group_chat_id)

    def recover_turn(self, group_chat_id: int) -> dict[str, Any]:
        return self.turn_runtime.recover(group_chat_id)
