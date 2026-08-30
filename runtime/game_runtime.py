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
