from typing import Any


class GameService:
    """Application orchestration for persisted games.

    Repository methods are synchronous today; async Telegram handlers can
    later wrap these calls in an executor without moving SQL into handlers.
    """

    def __init__(self, game_repository):
        self.repo = game_repository

    def get_active(self, group_chat_id: int):
        return self.repo.get_active_game(group_chat_id)

    def create(self, **data: Any):
        return self.repo.create_game(**data)

    def update(self, game_id: int, **data: Any):
        return self.repo.update_game(game_id, **data)

    def add_player(self, **data: Any):
        return self.repo.add_player(**data)

    def players(self, game_id: int):
        return self.repo.list_players(game_id)
