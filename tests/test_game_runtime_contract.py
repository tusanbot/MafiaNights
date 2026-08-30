from runtime.game_runtime import PersistentGameRuntime
from runtime.game_state_machine import Phase


class FakeMachine:
    def snapshot(self, group_id):
        return {"phase": "lobby", "group_id": group_id}

    def recover(self, group_id):
        return {"snapshot": self.snapshot(group_id)}

    def transition(self, group_id, phase):
        return (group_id, phase)


class FakeLobby:
    def join(self, *args, **kwargs):
        return "joined"

    def leave(self, *args, **kwargs):
        return True

    def snapshot(self, group_id):
        return []


class FakeTurns:
    def start(self, *args, **kwargs):
        return "turn"

    def finish(self, *args, **kwargs):
        return True

    def current(self, group_id):
        return None


class FakeChallenges:
    def create(self, *args, **kwargs):
        return {"id": "challenge"}

    def resolve(self, *args, **kwargs):
        return True

    def pending(self, group_id):
        return []


def test_runtime_is_single_facade():
    runtime = PersistentGameRuntime.__new__(PersistentGameRuntime)
    runtime.machine = FakeMachine()
    runtime.lobby = FakeLobby()
    runtime.turns = FakeTurns()
    runtime.challenges = FakeChallenges()

    assert runtime.snapshot(10)["phase"] == "lobby"
    assert runtime.join(10, 20) == "joined"
    assert runtime.leave(10, 20) is True
    assert runtime.start_turn(10, 1) == "turn"
    assert runtime.create_challenge(10, 20, 21, "before")["id"] == "challenge"
    assert runtime.resolve_challenge(10, "challenge", "accepted") is True
    assert runtime.transition(10, Phase.RUNNING) == (10, Phase.RUNNING)
