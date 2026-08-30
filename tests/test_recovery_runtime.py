from runtime.recovery_runtime import PersistentRecoveryRuntime


class FakeTurns:
    def __init__(self, rows):
        self.rows = rows
        self.finished = []

    def current(self, game_id):
        return self.rows.get(game_id)

    def finish(self, turn_id, state):
        self.finished.append((turn_id, state))
        return True


class FakeGames:
    def __init__(self, games):
        self.games = games

    def list_active_games(self):
        return self.games

    def get_active_game(self, group_id):
        return next((g for g in self.games if g["group_chat_id"] == group_id), None)


class FakeState:
    def __init__(self, games, turns):
        self.games = FakeGames(games)
        self.turns = turns

    def active_games(self):
        return self.games.list_active_games()

    def active_game(self, group_id):
        return self.games.get_active_game(group_id)


def test_recovery_plan_without_turn():
    state = FakeState([{"id": "g1", "group_chat_id": 10, "status": "running"}], FakeTurns({}))
    plan = PersistentRecoveryRuntime(state).plan(10)
    assert plan["recoverable"] is True
    assert plan["turn"] is None


def test_recovery_plan_contains_deadline():
    from datetime import datetime, timezone
    started = datetime.now(timezone.utc)
    state = FakeState(
        [{"id": "g1", "group_chat_id": 10, "status": "running"}],
        FakeTurns({"g1": {"id": "t1", "started_at": started, "duration_seconds": 120}}),
    )
    plan = PersistentRecoveryRuntime(state).plan(10)
    assert plan["deadline_epoch"] is not None
    assert plan["expired"] is False


def test_expired_turn_can_be_finished_after_restart():
    from datetime import datetime, timedelta, timezone
    turns = FakeTurns({"g1": {"id": "t1", "started_at": datetime.now(timezone.utc) - timedelta(seconds=130), "duration_seconds": 120}})
    state = FakeState([{"id": "g1", "group_chat_id": 10, "status": "running"}], turns)
    assert PersistentRecoveryRuntime(state).recover_expired(10) is True
    assert turns.finished[0][0] == "t1"
