"""Persistent challenge handler facade.

Challenge state is persisted by the runtime. Telegram UI and callback routing
remain outside this module.
"""
from __future__ import annotations

from typing import Any, Optional

from runtime.challenge_runtime import PersistentChallengeRuntime


class ChallengeHandler:
    def __init__(self, runtime: Optional[PersistentChallengeRuntime] = None):
        self.runtime = runtime or PersistentChallengeRuntime()

    def create(self, group_chat_id: int, challenger_id: int, target_id: int,
               mode: str, *, pause_main_turn: bool = False,
               pause_state: Optional[dict[str, Any]] = None):
        return self.runtime.create(
            group_chat_id, challenger_id, target_id, mode,
            pause_main_turn=pause_main_turn, pause_state=pause_state,
        )

    def resolve(self, group_chat_id: int, challenge_id: str, status: str,
                *, resume_main_turn: bool = True) -> bool:
        return self.runtime.resolve(
            group_chat_id, challenge_id, status,
            resume_main_turn=resume_main_turn,
        )

    def pending(self, group_chat_id: int):
        return self.runtime.pending(group_chat_id)

    def history(self, group_chat_id: int):
        return self.runtime.history(group_chat_id)
