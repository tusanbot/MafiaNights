import asyncio
from types import SimpleNamespace

from runtime.ephemeral_recovery import EphemeralRecoveryManager
from runtime.recovery_worker import RecoveryPlan


class FakeTurns:
    def __init__(self, current):
        self.current_value = current
        self.finished = []

    def current(self, group_id):
        return self.current_value

    def finish(self, turn_id, state):
        self.finished.append((turn_id, state))
        self.current_value = None
        return True


class FakeRuntime:
    def __init__(self, current=None):
        self.turns = FakeTurns(current)
        self.state = SimpleNamespace()

    def finish_turn(self, turn_id, state=None):
        return self.turns.finish(turn_id, state)


def make_manager(current):
    main = SimpleNamespace(turn_timer_task="stale", current_turn_message_id=123,
                           waiting_message_id=456, last_next_time=99)
    runtime = FakeRuntime(current)
    manager = EphemeralRecoveryManager(runtime, main)
    return manager, main, runtime


def test_prepare_legacy_ui_clears_stale_handles():
    manager, main, _ = make_manager({"id": "t1"})
    plan = RecoveryPlan("g1", 10, "turn", "t1", 110.0, 10.0, True)
    manager.prepare_legacy_ui([plan])
    assert main.turn_timer_task is None
    assert main.current_turn_message_id is None
    assert main.waiting_message_id is None
    assert main.last_next_time == 0
    assert main.recovered_turn_plans[10]["remaining_seconds"] == 10.0


def test_expiry_is_ignored_when_persisted_turn_changed():
    async def run():
        manager, _, runtime = make_manager({"id": "other"})
        await manager.on_turn_expired(RecoveryPlan("g1", 10, "turn", "t1", 100.0, 0.0, True))
        assert runtime.turns.finished == []
    asyncio.run(run())


def test_expiry_is_deduplicated():
    async def run():
        manager, main, runtime = make_manager({"id": "t1"})
        await manager.on_turn_expired(RecoveryPlan("g1", 10, "turn", "t1", 100.0, 0.0, True))
        runtime.turns.current_value = {"id": "t1"}
        await manager.on_turn_expired(RecoveryPlan("g1", 10, "turn", "t1", 100.0, 0.0, True))
        assert len(runtime.turns.finished) == 1
        assert main.turn_timer_task is None
    asyncio.run(run())


def test_recovered_expiry_uses_application_hook():
    async def run():
        manager, main, runtime = make_manager({"id": "t1"})
        events = []

        async def hook(plan):
            events.append(plan.turn_id)
            runtime.turns.current_value = None

        main.on_recovered_turn_expired = hook
        await manager.on_turn_expired(RecoveryPlan("g1", 10, "turn", "t1", 100.0, 0.0, True))
        assert events == ["t1"]
        assert runtime.turns.finished == []
    asyncio.run(run())
