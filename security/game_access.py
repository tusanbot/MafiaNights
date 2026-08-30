"""Authorization helpers for sensitive mafia game state.

These checks are server-side only. They must be called before any operation that
returns roles, challenge internals, or other private game state.
"""
from repositories.game_repository import GameRepository


class GameAccessError(PermissionError):
    pass


class GameAccess:
    def __init__(self, game_repository=None):
        self.repo = game_repository or GameRepository()

    def active_game(self, group_id):
        return self.repo.get_active_game(group_id)

    def require_moderator(self, group_id, actor_id):
        game = self.active_game(group_id)
        if not game:
            raise GameAccessError("بازی فعالی وجود ندارد")
        if int(game.get("moderator_id") or 0) != int(actor_id):
            raise GameAccessError("فقط گرداننده اجازه این عملیات را دارد")
        return game

    def require_member(self, group_id, actor_id):
        game = self.active_game(group_id)
        if not game:
            raise GameAccessError("بازی فعالی وجود ندارد")
        players = self.repo.list_players(game["id"])
        if not any(int(p["player_id"]) == int(actor_id) and p.get("status") != "removed" for p in players):
            raise GameAccessError("کاربر عضو بازی نیست")
        return game

    def private_role(self, group_id, actor_id):
        """Return a role only to the authenticated player owning that role."""
        game = self.require_member(group_id, actor_id)
        for player in self.repo.list_players(game["id"]):
            if int(player["player_id"]) == int(actor_id):
                return player.get("role")
        raise GameAccessError("نقش بازیکن پیدا نشد")

    def moderator_players(self, group_id, actor_id):
        """Return full player rows, including roles, only to the moderator."""
        game = self.require_moderator(group_id, actor_id)
        return self.repo.list_players(game["id"])
