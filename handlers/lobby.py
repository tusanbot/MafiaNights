"""Persistent lobby handler facade.

Telegram callbacks should use this object for lobby mutations. It contains no
lobby state of its own; Supabase is the source of truth.
"""
from __future__ import annotations

from typing import Optional

from runtime.lobby_runtime import PersistentLobbyRuntime


class LobbyHandler:
    def __init__(self, runtime: Optional[PersistentLobbyRuntime] = None):
        self.runtime = runtime or PersistentLobbyRuntime()

    def open(self, group_id: int, moderator_id: Optional[int] = None,
             scenario_id: Optional[str] = None, event_number: Optional[int] = None):
        return self.runtime.ensure(group_id, moderator_id, scenario_id, event_number)

    def join(self, group_id: int, user_id: int, seat: Optional[int] = None,
             moderator_id: Optional[int] = None, scenario_id: Optional[str] = None,
             event_number: Optional[int] = None, substitute: bool = False):
        return self.runtime.join(group_id, user_id, seat, moderator_id, scenario_id, event_number, substitute)

    def leave(self, group_id: int, user_id: int) -> bool:
        return self.runtime.leave(group_id, user_id)

    def assign_seat(self, group_id: int, user_id: int, seat: int) -> bool:
        return self.runtime.assign_seat(group_id, user_id, seat)

    def clear_seat(self, group_id: int, user_id: int) -> bool:
        return self.runtime.clear_seat(group_id, user_id)

    def promote_waiting(self, group_id: int, seat: int):
        return self.runtime.promote_waiting(group_id, seat)

    def set_status(self, group_id: int, user_id: int, status: str) -> bool:
        return self.runtime.set_status(group_id, user_id, status)

    def set_moderator(self, group_id: int, moderator_id: int) -> bool:
        return self.runtime.set_moderator(group_id, moderator_id)

    def set_scenario(self, group_id: int, scenario_id: str) -> bool:
        return self.runtime.set_scenario(group_id, scenario_id)

    def snapshot(self, group_id: int) -> dict:
        return self.runtime.snapshot(group_id)
