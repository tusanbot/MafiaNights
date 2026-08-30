from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from runtime.game_state import GameState
from services.turn_service import TurnService


class PersistentTurnRuntime:
    """Crash-safe turn runtime. DB state is authoritative; asyncio timers are not."""

    def __init__(self, state: Optional[GameState] = None):
        self.state = state or GameState()
        self.turns = TurnService(self.state.turns)

    def start(self, group_chat_id: int, turn_number: int, *, seat: Optional[int] = None,
              player_id: Optional[int] = None, turn_type: str = "main",
              duration_seconds: Optional[int] = None, current_turn_index: Optional[int] = None,
              state: Optional[dict[str, Any]] = None):
        game = self.state.active_game(group_chat_id)
        if not game:
            raise ValueError("بازی فعالی برای این گروه وجود ندارد")
        return self.turns.start(
            game_id=game["id"], turn_number=turn_number, seat=seat,
            player_id=player_id, turn_type=turn_type,
            duration_seconds=duration_seconds, current_turn_index=current_turn_index,
            state=state,
        )

    def finish(self, turn_id: str, state: Optional[dict[str, Any]] = None) -> bool:
        return self.turns.finish(turn_id, state)

    def current(self, group_chat_id: int):
        game = self.state.active_game(group_chat_id)
        return self.turns.current(game["id"]) if game else None

    def history(self, group_chat_id: int):
        game = self.state.active_game(group_chat_id)
        return self.turns.history(game["id"]) if game else []

    def recover(self, group_chat_id: int) -> dict[str, Any]:
        """Return enough persisted state for a restarted bot to resume a turn worker."""
        game = self.state.active_game(group_chat_id)
        if not game:
            return {"game": None, "turn": None, "recoverable": False}
        turn = self.turns.current(game["id"])
        deadline = None
        if turn and turn.get("started_at") and turn.get("duration_seconds"):
            started = turn["started_at"]
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            deadline = started.timestamp() + int(turn["duration_seconds"])
        return {
            "game": {
                "id": game["id"],
                "group_chat_id": game["group_chat_id"],
                "status": game.get("status"),
                "current_turn_index": game.get("current_turn_index", 0),
                "current_turn_seat": game.get("current_turn_seat"),
            },
            "turn": turn,
            "deadline_epoch": deadline,
            "recoverable": bool(turn),
        }
