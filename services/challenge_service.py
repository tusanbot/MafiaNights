class ChallengeService:
    def __init__(self, challenge_repository):
        self.repo = challenge_repository

    async def create(self, **data):
        return await self.repo.create_challenge(**data)

    async def resolve(self, challenge_id, **data):
        return await self.repo.resolve_challenge(challenge_id, **data)

    async def for_game(self, game_id):
        return await self.repo.list_challenges(game_id)
