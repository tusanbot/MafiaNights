class ChallengeService:
    def __init__(self, challenge_repository):
        self.repo = challenge_repository

    def create(self, **data):
        return self.repo.create_challenge(**data)

    def resolve(self, challenge_id, status):
        return self.repo.resolve_challenge(challenge_id, status)

    def for_game(self, game_id):
        return self.repo.list_challenges(game_id)
