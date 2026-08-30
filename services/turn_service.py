class TurnService:
    def __init__(self, turn_repository):
        self.repo = turn_repository

    async def start(self, **data):
        return await self.repo.create_turn(**data)

    async def finish(self, turn_id, **data):
        return await self.repo.finish_turn(turn_id, **data)

    async def history(self, game_id):
        return await self.repo.list_turns(game_id)
