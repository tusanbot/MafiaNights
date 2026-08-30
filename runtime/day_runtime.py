"""Persistence boundary for day/night progression during migration."""
from __future__ import annotations

from typing import Any, Optional

from runtime.game_state import GameState


class PersistentDayRuntime:
    """Keep day/night state and round reset metadata in persisted game state."""

    def __init__(self, state: Optional[GameState] = None):
        self.state = state or GameState()

    def snapshot(self, group_chat_id: int) -> dict[str, Any]:
        game = self.state.active_game(group_chat_id)
        if not game:
            return {"day": 0, "phase": None, "state": {}}
        payload = dict(game.get("state") or {})
        return {
            "day": int(payload.get("day_number") or 0),
            "phase": payload.get("day_phase") or payload.get("phase"),
            "state": payload,
        }

    def _finish_active_turn(self, game: dict[str, Any], reason: str) -> None:
        turn = self.state.turns.current_turn(game["id"])
        if turn:
            self.state.turns.finish_turn(turn["id"], {
                "migration": "persistent_day_runtime",
                "finish_reason": reason,
            })

    def _transition(self, group_chat_id: int, phase: str, *, day_number: Optional[int] = None,
                    extra: Optional[dict[str, Any]] = None, finish_reason: str = "day_transition") -> dict[str, Any]:
        game = self.state.active_game(group_chat_id)
        if not game:
            raise ValueError("بازی فعالی برای این گروه وجود ندارد")

        self._finish_active_turn(game, finish_reason)
        payload = dict(game.get("state") or {})
        payload["day_phase"] = str(phase)
        if day_number is not None:
            payload["day_number"] = int(day_number)
        if extra:
            payload.update(extra)

        self.state.games.update_game(
            game["id"],
            status="running",
            state=payload,
            current_turn_index=0,
            current_turn_seat=None,
        )
        return self.snapshot(group_chat_id)

    def set_phase(self, group_chat_id: int, phase: str, *, day_number: Optional[int] = None,
                  extra: Optional[dict[str, Any]] = None) -> bool:
        game = self.state.active_game(group_chat_id)
        if not game:
            return False
        payload = dict(game.get("state") or {})
        payload["day_phase"] = str(phase)
        if day_number is not None:
            payload["day_number"] = int(day_number)
        if extra:
            payload.update(extra)
        return self.state.games.update_game(game["id"], state=payload)

    def start_new_day(self, group_chat_id: int, *, day_number: Optional[int] = None,
                      extra: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        current = self.snapshot(group_chat_id)
        next_day = int(day_number if day_number is not None else current.get("day", 0) + 1)
        return self._transition(
            group_chat_id,
            "day",
            day_number=next_day,
            extra=extra,
            finish_reason="start_new_day",
        )

    def start_night(self, group_chat_id: int, *, extra: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        current = self.snapshot(group_chat_id)
        day = int(current.get("day") or 1)
        return self._transition(
            group_chat_id,
            "night",
            day_number=day,
            extra=extra,
            finish_reason="start_night",
        )
