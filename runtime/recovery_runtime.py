"""Restart recovery orchestration for persisted Mafia games."""
from __future__ import annotations

import time
from typing import Any, Optional

from runtime.game_state import GameState
from runtime.turn_cutover import persistent_countdown


class PersistentRecoveryRuntime:
    """Discover active games/turns and provide restart-safe recovery plans."""

    def __init__(self, state: Optional[GameState] = None):
        self.state = state or GameState()

    def active_games(self):
        return self.state.active_games()

    def plan(self, group_chat_id: int) -> dict[str, Any]:
        game = self.state.active_game(group_chat_id)
        if not game:
            return {"recoverable": False, "reason": "no_active_game"}
        turn = self.state.turns.current(game["id"])
        if not turn:
            return {"recoverable": True, "game": game, "turn": None, "deadline_epoch": None}
        started = turn.get("started_at")
        if hasattr(started, "timestamp"):
            started_epoch = started.timestamp()
        else:
            started_epoch = time.time()
        duration = int(turn.get("duration_seconds") or 0)
        deadline = started_epoch + duration if duration else None
        return {
            "recoverable": True,
            "game": game,
            "turn": turn,
            "deadline_epoch": deadline,
            "expired": bool(deadline is not None and deadline <= time.time()),
        }

    def plans(self):
        return [self.plan(int(game["group_chat_id"])) for game in self.active_games()]

    def recover_expired(self, group_chat_id: int) -> bool:
        plan = self.plan(group_chat_id)
        if not plan.get("turn") or not plan.get("expired"):
            return False
        turn = plan["turn"]
        return bool(self.state.turns.finish(turn["id"], {
            "recovery": True,
            "finish_reason": "timer_expired_after_restart",
        }))
