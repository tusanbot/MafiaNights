"""Persistent lobby handlers.

This module is the migration seam for lobby state. It deliberately delegates
state changes to the persistent runtime instead of maintaining a second lobby
state in module globals.
"""
from __future__ import annotations

from typing import Optional

from runtime.lobby_runtime import PersistentLobbyRuntime


class LobbyHandler:
    def __init__(self, runtime: Optional[PersistentLobbyRuntime] = None):
        self.runtime = runtime or PersistentLobbyRuntime()

    def join(self, group_id: int, user_id: int, seat: Optional[int] = None,
             moderator_id: Optional[int] = None,
             scenario_id: Optional[str] = None,
             event_number: Optional[int] = None):
        return self.runtime.join(
            group_chat_id=group_id,
            player_id=user_id,
            seat=seat,
            moderator_id=moderator_id,
            scenario_id=scenario_id,
            event_number=event_number,
        )

    def snapshot(self, group_id: int):
        return self.runtime.snapshot(group_id)

    def set_moderator(self, group_id: int, moderator_id: int):
        return self.runtime.set_moderator(group_id, moderator_id)

    def set_scenario(self, group_id: int, scenario_id: str):
        return self.runtime.set_scenario(group_id, scenario_id)
