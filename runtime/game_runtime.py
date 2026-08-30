"""Unified persistent runtime facade used by Telegram handlers during cut-over."""
from __future__ import annotations

from typing import Any, Optional

from runtime.game_state import GameState
from runtime.game_state_machine import GameStateMachine, Phase
from runtime.challenge_runtime import PersistentChallengeRuntime
from runtime.lobby_runtime import PersistentLobbyRuntime
from runtime.turn_runtime import PersistentTurnRuntime


class PersistentGameRuntime:
    """Single application boundary for lobby, turn and challenge operations.

    This class contains no Telegram objects and no in-memory game state. It is
    intentionally small so legacy handlers can be redirected here without
    duplicating persistence logic.
    """

    def __init__(self, state: Optional[GameState] = None):
        self.state = state or GameState()
        self.machine = GameStateMachine(self.state)
        self.lobby = PersistentLobbyRuntime(self.state)
        self.turns = PersistentTurnRuntime(self.state)
        self.challenges = PersistentChallengeRuntime(self.state)

    def snapshot(self, group_chat_id: int) -> dict[str, Any]:
        return self.machine.snapshot(group_chat_id)

    def recover(self, group_chat_id: int) -> dict[str, Any]:
        return self.machine.recover(group_chat_id)

    def transition(self, group_chat_id: int, phase: Phase):
        return self.machine.transition(group_chat_id, phase)

    def lobby_snapshot(self, group_chat_id: int):
        return self.lobby.snapshot(group_chat_id)

    def join(self, group_chat_id: int, player_id: int, seat: Optional[int] = None,
             moderator_id: Optional[int] = None, scenario_id: Optional[str] = None,
             event_number: Optional[int] = None):
        return self.lobby.join(group_chat_id, player_id, seat, moderator_id,
                               scenario_id, event_number)

    def leave(self, group_chat_id: int, player_id: int):
        return self.lobby.leave(group_chat_id, player_id)

    def start_turn(self, group_chat_id: int, turn_number: int, **kwargs):
        return self.turns.start(group_chat_id, turn_number, **kwargs)

    def start_first_turn(self, group_chat_id: int, *, seat: int, turn_number: int = 1,
                         duration_seconds: Optional[int] = None,
                         current_turn_index: int = 0,
                         player_id: Optional[int] = None,
                         state: Optional[dict[str, Any]] = None):
        """Atomically move a running game into TURN and persist its first turn.

        Telegram handlers should use this entry point for the first turn instead
        of mutating ``game_running``/``current_turn_index`` and then calling the
        legacy timer. The transition is persisted before any Telegram worker is
        started, making the turn recoverable after a process restart.
        """
        game = self.state.active_game(group_chat_id)
        if not game:
            raise ValueError("بازی فعالی برای این گروه وجود ندارد")

        status = str(game.get("status") or "lobby").lower()
        if status == Phase.LOBBY.value:
            self.machine.transition(group_chat_id, Phase.RUNNING)
        elif status not in {Phase.RUNNING.value, Phase.PAUSED.value, Phase.TURN.value}:
            raise ValueError(f"شروع نوبت در وضعیت {status} ممکن نیست")

        if player_id is None:
            current_game = self.state.active_game(group_chat_id)
            persisted_players = (current_game or {}).get("state") or {}
            player_id = persisted_players.get("player_id")

        turn = self.turns.start(
            group_chat_id,
            turn_number,
            seat=seat,
            player_id=player_id,
            turn_type="main",
            duration_seconds=duration_seconds,
            current_turn_index=current_turn_index,
            state=state,
        )

        if str((self.state.active_game(group_chat_id) or {}).get("status")) != Phase.TURN.value:
            self.machine.transition(group_chat_id, Phase.TURN)
        return turn

    def finish_turn(self, turn_id: str, state: Optional[dict[str, Any]] = None):
        return self.turns.finish(turn_id, state)

    def current_turn(self, group_chat_id: int):
        return self.turns.current(group_chat_id)

    def create_challenge(self, group_chat_id: int, challenger_id: int,
                         target_id: int, mode: str, **kwargs):
        return self.challenges.create(group_chat_id, challenger_id, target_id,
                                      mode, **kwargs)

    def resolve_challenge(self, group_chat_id: int, challenge_id: str,
                          status: str, **kwargs):
        return self.challenges.resolve(group_chat_id, challenge_id, status,
                                       **kwargs)

    def pending_challenges(self, group_chat_id: int):
        return self.challenges.pending(group_chat_id)
