class TurnService:
    def __init__(self, turn_repository):
        self.repo = turn_repository

    def start(self, **data):
        return self.repo.create_turn(**data)

    def finish(self, turn_id, state=None):
        return self.repo.finish_turn(turn_id, state=state)

    def history(self, game_id):
        return self.repo.list_turns(game_id)
