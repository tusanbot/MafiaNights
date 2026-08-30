from __future__ import annotations

from typing import Any, Optional

from runtime.lobby_runtime import PersistentLobbyRuntime


class LobbyMigration:
    """Compatibility boundary for moving the legacy lobby to persistent state.

    The legacy UI can continue to keep presentation-only values in memory, but
    all authoritative lobby mutations should pass through this object.  It is
    deliberately small so the final main.py integration can be done without
    duplicating game rules in handlers.
    """

    def __init__(self, runtime: Optional[PersistentLobbyRuntime] = None):
        self.runtime = runtime or PersistentLobbyRuntime()

    def open(self, group_id: int, moderator_id: Optional[int] = None,
             scenario_id: Optional[str] = None, event_number: Optional[int] = None):
        return self.runtime.ensure(group_id, moderator_id, scenario_id, event_number)

    def join(self, group_id: int, user_id: int, seat: Optional[int] = None,
             moderator_id: Optional[int] = None, scenario_id: Optional[str] = None,
             event_number: Optional[int] = None, substitute: bool = False):
        return self.runtime.join(
            group_chat_id=group_id,
            player_id=user_id,
            seat=seat,
            moderator_id=moderator_id,
            scenario_id=scenario_id,
            event_number=event_number,
            is_substitute=substitute,
        )

    def set_moderator(self, group_id: int, moderator_id: int) -> bool:
        return self.runtime.set_moderator(group_id, moderator_id)

    def set_scenario(self, group_id: int, scenario_id: str) -> bool:
        return self.runtime.set_scenario(group_id, scenario_id)

    def snapshot(self, group_id: int) -> dict[str, Any]:
        return self.runtime.snapshot(group_id)

    def persist_legacy(self, group_id: int, *, legacy_state: Optional[dict[str, Any]] = None,
                       turn_index: Optional[int] = None,
                       turn_seat: Optional[int] = None) -> bool:
        """Persist a controlled subset of legacy state during cut-over.

        This is intentionally not a generic ``globals()`` dump: only state
        explicitly selected by the migration caller is persisted.
        """
        return self.runtime.persist_legacy_state(
            group_id,
            state=legacy_state,
            current_turn_index=turn_index,
            current_turn_seat=turn_seat,
        )
