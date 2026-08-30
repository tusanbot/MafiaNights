from runtime.day_runtime import PersistentDayRuntime


class Turns:
    def __init__(self):
        self.current = None
        self.finished = []

    def current_turn(self, game_id):
        return self.current

    def finish_turn(self, turn_id, state):
        self.finished.append((turn_id, state))
        self.current = None
        return True


class Games:
    def __init__(self):
        self.game = {"id": "g1", "group_chat_id": 1, "status": "running", "state": {"day_number": 2}}
        self.updated = []

    def get_active_game(self, group_id):
        return self.game

    def update_game(self, game_id, **fields):
        self.game.update(fields)
        self.updated.append(fields)
        return True


class State:
    def __init__(self):
        self.games = Games()
        self.turns = Turns()

    def active_game(self, group_id):
        return self.games.get_active_game(group_id)


def test_start_new_day_is_persisted_and_resets_pointer():
    state = State()
    runtime = PersistentDayRuntime(state)
    result = runtime.start_new_day(1)
    assert result["day"] == 3
    assert result["phase"] == "day"
    assert state.games.updated[-1]["current_turn_index"] == 0
    assert state.games.updated[-1]["current_turn_seat"] is None


def test_start_night_preserves_day_number():
    runtime = PersistentDayRuntime(State())
    result = runtime.start_night(1)
    assert result["day"] == 2
    assert result["phase"] == "night"


def test_day_transition_finishes_active_persisted_turn():
    state = State()
    state.turns.current = {"id": "t1"}
    runtime = PersistentDayRuntime(state)
    runtime.start_new_day(1)
    assert state.turns.finished == [("t1", {"migration": "persistent_day_runtime", "finish_reason": "start_new_day"})]
