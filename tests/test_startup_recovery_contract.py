from runtime.startup_recovery import recover_persisted_games


class Recovery:
    def __init__(self, plans):
        self._plans = plans
        self.finished = []

    def recovery_plans(self):
        return self._plans

    def finish_expired(self, group_id):
        self.finished.append(group_id)
        return True


class Runtime:
    def __init__(self, recovery):
        self.recovery = recovery


class Legacy:
    def __init__(self, runtime):
        self.persistent_runtime = runtime


def test_startup_recovery_finishes_expired_turns():
    recovery = Recovery([{"group_chat_id": 10, "turn_id": "t1", "expired": True}])
    result = __import__("asyncio").run(recover_persisted_games(Legacy(Runtime(recovery))))
    assert recovery.finished == [10]
    assert result == [{"group_chat_id": 10, "action": "expired_turn_finished"}]
