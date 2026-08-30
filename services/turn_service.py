from __future__ import annotations

from typing import Any, Optional


class TurnService:
    """Application boundary for persistent turn state.

    Telegram handlers should call this service instead of mutating turn globals.
    The database is authoritative; in-memory timer tasks are only workers.
    """

    def __init__(self, turn_repository):
        self.repo = turn_repository

    def start(self, game_id: str, turn_number: int, *, seat: Optional[int] = None,
              player_id: Optional[int] = None, turn_type: str = "main",
              duration_seconds: Optional[int] = None, state: Optional[dict[str, Any]] = None,
              current_turn_index: Optional[int] = None):
        if turn_number < 1:
            raise ValueError("turn_number باید حداقل 1 باشد")
        if duration_seconds is not None and duration_seconds <= 0:
            raise ValueError("duration_seconds باید مثبت باشد")
        return self.repo.start_turn(
            game_id=game_id,
            turn_number=turn_number,
            seat=seat,
            player_id=player_id,
            turn_type=turn_type,
            duration_seconds=duration_seconds,
            state=state,
            current_turn_index=current_turn_index,
        )

    def finish(self, turn_id: str, state: Optional[dict[str, Any]] = None) -> bool:
        return bool(self.repo.finish_turn(turn_id, state=state))

    def current(self, game_id: str):
        return self.repo.current_turn(game_id)

    def history(self, game_id: str):
        return self.repo.list_turns(game_id)
