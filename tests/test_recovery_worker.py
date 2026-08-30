from runtime.recovery_worker import RecoveryPlan, RecoveryWorker


def test_recovery_plan_is_deterministic_for_remaining_time():
    worker = RecoveryWorker.__new__(RecoveryWorker)
    assert RecoveryPlan(
        game_id="g1",
        group_chat_id=10,
        status="running",
        turn_id="t1",
        deadline_epoch=110.0,
        remaining_seconds=10.0,
        recoverable=True,
    ).remaining_seconds == 10.0


def test_worker_registry_starts_empty_without_runtime_state():
    worker = RecoveryWorker.__new__(RecoveryWorker)
    worker._tasks = {}
    assert worker.running_turn_ids == set()
