from __future__ import annotations

from typing import Any, Optional

from runtime.game_state import GameState


class PersistentLobbyRuntime:
    """Adapter for migrating the legacy lobby dictionaries to persistent state.

    This class is intentionally UI-agnostic. Telegram handlers can keep their
    existing rendering code while all authoritative lobby mutations go through
    this boundary during the migration.
    """

    def __init__(self, state: Optional[GameState] = None):
        self.state = state or GameState()

    def ensure(self, group_chat_id: int, moderator_id: Optional[int] = None,
               scenario_id: Optional[str] = None, event_number: Optional[int] = None):
        return self.state.ensure_lobby(
            group_chat_id=group_chat_id,
            moderator_id=moderator_id,
            scenario_id=scenario_id,
            event_number=event_number,
        )

    def join(self, group_chat_id: int, player_id: int, seat: Optional[int] = None,
             moderator_id: Optional[int] = None, scenario_id: Optional[str] = None,
             event_number: Optional[int] = None, is_substitute: bool = False) -> dict[str, Any]:
        game = self.ensure(group_chat_id, moderator_id, scenario_id, event_number)
        game_id = game["id"]
        row_id = self.state.add_player(game_id, player_id, seat, is_substitute)
        return {
            "game_id": game_id,
            "game_player_id": row_id,
            "player_id": int(player_id),
            "seat": seat,
            "is_substitute": is_substitute,
        }

    def snapshot(self, group_chat_id: int) -> dict[str, Any]:
        game = self.state.active_game(group_chat_id)
        if not game:
            return {"game": None, "players": [], "seats": {}, "waiting": []}
        snap = self.state.public_players(game["id"])
        return {
            "game": {
                "id": game["id"],
                "group_chat_id": game["group_chat_id"],
                "moderator_id": game.get("moderator_id"),
                "scenario_id": game.get("scenario_id"),
                "status": game.get("status"),
            },
            **self.state.lobby.snapshot(game["id"]),
        }

    def set_moderator(self, group_chat_id: int, moderator_id: int) -> bool:
        game = self.ensure(group_chat_id)
        return self.state.lobby.set_moderator(game["id"], moderator_id)

    def set_scenario(self, group_chat_id: int, scenario_id: str) -> bool:
        game = self.ensure(group_chat_id)
        return self.state.lobby.set_scenario(game["id"], scenario_id)

    def persist_legacy_state(self, group_chat_id: int, *, state: Optional[dict[str, Any]] = None,
                             current_turn_index: Optional[int] = None,
                             current_turn_seat: Optional[int] = None) -> bool:
        game = self.state.active_game(group_chat_id)
        if not game:
            return False
        return self.state.persist_lobby(
            game["id"],
            state=state,
            current_turn_index=current_turn_index,
            current_turn_seat=current_turn_seat,
        )
