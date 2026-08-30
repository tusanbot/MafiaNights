from __future__ import annotations

from typing import Any, Optional

from runtime.game_state import GameState
from services.challenge_service import ChallengeService


class PersistentChallengeRuntime:
    """Persistence boundary for challenge lifecycle.

    Telegram handlers should use this runtime. Challenge state is stored in the
    database; pause/resume metadata is kept in the game's JSON state so a bot
    restart does not lose the interrupted main-turn context.
    """

    def __init__(self, state: Optional[GameState] = None):
        self.state = state or GameState()
        self.challenges = ChallengeService(self.state.challenges)

    def _game(self, group_chat_id: int) -> dict[str, Any]:
        game = self.state.active_game(group_chat_id)
        if not game:
            raise ValueError("بازی فعالی برای این گروه وجود ندارد")
        return game

    def create(self, group_chat_id: int, challenger_id: int, target_id: int,
               mode: str, *, pause_main_turn: bool = False,
               pause_state: Optional[dict[str, Any]] = None):
        game = self._game(group_chat_id)
        players = self.state.lobby.players(game["id"])
        ids = {int(p["player_id"]) for p in players if p.get("status") in ("active", "substitute")}
        if int(challenger_id) not in ids or int(target_id) not in ids:
            raise ValueError("هر دو بازیکن باید عضو فعال بازی باشند")

        created = self.challenges.create(
            game_id=game["id"], challenger_id=challenger_id,
            target_id=target_id, mode=mode,
        )

        if pause_main_turn:
            payload = dict(game.get("state") or {})
            payload["challenge_pause"] = {
                "active": True,
                "challenge_id": str(created),
                "previous_status": game.get("status"),
                "previous_turn_index": game.get("current_turn_index"),
                "previous_turn_seat": game.get("current_turn_seat"),
                "state": pause_state or {},
            }
            self.state.games.update_game(game["id"], status="paused", state=payload)
        return {"id": created, "game_id": game["id"], "challenger_id": int(challenger_id),
                "target_id": int(target_id), "mode": mode}

    def resolve(self, group_chat_id: int, challenge_id: str, status: str,
                *, resume_main_turn: bool = True) -> bool:
        game = self._game(group_chat_id)
        changed = self.challenges.resolve(challenge_id, status)
        if not changed:
            return False

        if resume_main_turn:
            payload = dict(game.get("state") or {})
            pause = payload.pop("challenge_pause", None)
            if pause and str(pause.get("challenge_id")) == str(challenge_id):
                previous_status = pause.get("previous_status") or "running"
                self.state.games.update_game(
                    game["id"], status=previous_status,
                    state=payload,
                    current_turn_index=pause.get("previous_turn_index"),
                    current_turn_seat=pause.get("previous_turn_seat"),
                )
        return True

    def pending(self, group_chat_id: int):
        game = self._game(group_chat_id)
        return self.challenges.pending(game["id"])

    def history(self, group_chat_id: int):
        game = self._game(group_chat_id)
        return self.challenges.for_game(game["id"])
