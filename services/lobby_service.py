from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

from repositories.game_repository import GameRepository


class LobbyService:
    """Authoritative lobby facade.

    Handler code should use this service instead of writing directly to the
    in-memory lobby dictionaries.  The returned records are safe to use for
    public lobby rendering; private role data must not be exposed by this
    service.
    """

    def __init__(self, repository: Optional[GameRepository] = None):
        self.repository = repository or GameRepository()

    def get_or_create(self, group_chat_id: int, moderator_id: Optional[int] = None,
                      scenario_id: Optional[str] = None, event_number: Optional[int] = None) -> Dict[str, Any]:
        game = self.repository.get_active_game(group_chat_id)
        if game:
            return game
        game_id = self.repository.create_game(
            group_chat_id=group_chat_id,
            moderator_id=moderator_id,
            scenario_id=scenario_id,
            event_number=event_number,
            state={"phase": "lobby", "waiting": [], "seat_count": 0},
        )
        return self.repository.get_active_game(group_chat_id) or {"id": game_id, "group_chat_id": group_chat_id}

    def set_scenario(self, game_id: str, scenario_id: str) -> bool:
        return self.repository.update_game(game_id, scenario_id=scenario_id)

    def set_moderator(self, game_id: str, moderator_id: int) -> bool:
        return self.repository.update_game(game_id, moderator_id=int(moderator_id))

    def join(self, game_id: str, player_id: int, seat: Optional[int] = None,
             is_substitute: bool = False) -> int:
        return self.repository.add_player(
            game_id=game_id,
            player_id=player_id,
            seat=seat,
            status="waiting" if seat is None else "active",
            is_substitute=is_substitute,
        )

    def players(self, game_id: str) -> list[dict[str, Any]]:
        rows = self.repository.list_players(game_id)
        # Never return role to the public lobby consumer.
        return [
            {
                "id": row.get("id"),
                "player_id": row.get("player_id"),
                "seat": row.get("seat"),
                "status": row.get("status"),
                "is_substitute": row.get("is_substitute", False),
                "username": row.get("username"),
                "first_name": row.get("first_name"),
                "last_name": row.get("last_name"),
                "nickname": row.get("nickname"),
            }
            for row in rows
        ]

    def snapshot(self, game_id: str) -> Dict[str, Any]:
        rows = self.players(game_id)
        return {
            "players": rows,
            "seats": {str(row["seat"]): row["player_id"] for row in rows if row.get("seat") is not None},
            "waiting": [row["player_id"] for row in rows if row.get("seat") is None],
        }
