"""Telegram-facing turn handler boundary.

All authoritative turn state is delegated to PersistentTurnRuntime. Telegram
message IDs and asyncio tasks must remain outside this class.
"""
from __future__ import annotations

from typing import Any, Optional

from runtime.game_runtime import PersistentGameRuntime
from runtime.turn_runtime import PersistentTurnRuntime


class TurnHandler:
    def __init__(self, runtime: Optional[PersistentTurnRuntime] = None,
                 game_runtime: Optional[PersistentGameRuntime] = None):
        self.runtime = runtime or PersistentTurnRuntime()
        self.game_runtime = game_runtime

    def start(self, group_chat_id: int, turn_number: int, *, seat: Optional[int] = None,
              player_id: Optional[int] = None, turn_type: str = "main",
              duration_seconds: Optional[int] = None,
              current_turn_index: Optional[int] = None,
              state: Optional[dict[str, Any]] = None):
        return self.runtime.start(
            group_chat_id, turn_number, seat=seat, player_id=player_id,
            turn_type=turn_type, duration_seconds=duration_seconds,
            current_turn_index=current_turn_index, state=state,
        )

    def start_first_turn(self, group_chat_id: int, *, seat: int, turn_number: int = 1,
                         duration_seconds: Optional[int] = None,
                         current_turn_index: int = 0,
                         player_id: Optional[int] = None,
                         state: Optional[dict[str, Any]] = None):
        """Start the first persisted turn through the game lifecycle boundary."""
        runtime = self.game_runtime or PersistentGameRuntime(self.runtime.state)
        return runtime.start_first_turn(
            group_chat_id,
            seat=seat,
            turn_number=turn_number,
            duration_seconds=duration_seconds,
            current_turn_index=current_turn_index,
            player_id=player_id,
            state=state,
        )

    def finish(self, turn_id: str, state: Optional[dict[str, Any]] = None) -> bool:
        return self.runtime.finish(turn_id, state)

    def current(self, group_chat_id: int):
        return self.runtime.current(group_chat_id)

    def history(self, group_chat_id: int):
        return self.runtime.history(group_chat_id)

    def recover(self, group_chat_id: int) -> dict[str, Any]:
        return self.runtime.recover(group_chat_id)
