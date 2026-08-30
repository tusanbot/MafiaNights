"""Telegram-facing turn handler boundary.

All authoritative turn state is delegated to PersistentTurnRuntime. Telegram
message IDs and asyncio tasks must remain outside this class.
"""
from __future__ import annotations

from typing import Any, Optional

from runtime.turn_runtime import PersistentTurnRuntime


class TurnHandler:
    def __init__(self, runtime: Optional[PersistentTurnRuntime] = None):
        self.runtime = runtime or PersistentTurnRuntime()

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

    def finish(self, turn_id: str, state: Optional[dict[str, Any]] = None) -> bool:
        return self.runtime.finish(turn_id, state)

    def current(self, group_chat_id: int):
        return self.runtime.current(group_chat_id)

    def history(self, group_chat_id: int):
        return self.runtime.history(group_chat_id)

    def recover(self, group_chat_id: int) -> dict[str, Any]:
        return self.runtime.recover(group_chat_id)
