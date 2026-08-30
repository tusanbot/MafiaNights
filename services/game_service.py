from typing import Any


class GameService:
    """Orchestrates game persistence through repository objects.

    Domain rules stay here; Telegram handlers should not perform SQL.
    """

    def __init__(self, game_repository):
        self.repo = game_repository

    async def get_active(self, group_chat_id: int):
        return await self.repo.get_active_game(group_chat_id)

    async def create(self, **data: Any):
        return await self.repo.create_game(**data)

    async def update(self, game_id: int, **data: Any):
        return await self.repo.update_game(game_id, **data)
