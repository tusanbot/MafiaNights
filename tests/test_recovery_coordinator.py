import asyncio

from runtime.recovery_coordinator import RecoveryCoordinator


class FakeWorker:
    def __init__(self):
        self.running_turn_ids = set()
        self.start_calls = 0
        self.stop_calls = 0

    def plans(self):
        return []

    async def recover(self, callback):
        self.start_calls += 1
        return []

    async def stop(self):
        self.stop_calls += 1


def test_coordinator_starts_once():
    async def run():
        coordinator = RecoveryCoordinator.__new__(RecoveryCoordinator)
        coordinator.worker = FakeWorker()
        coordinator.started = False
        first = await coordinator.start(lambda plan: asyncio.sleep(0))
        second = await coordinator.start(lambda plan: asyncio.sleep(0))
        assert first == []
        assert second == []
        assert coordinator.worker.start_calls == 1
        assert coordinator.started is True

    asyncio.run(run())


def test_coordinator_stops_cleanly():
    async def run():
        coordinator = RecoveryCoordinator.__new__(RecoveryCoordinator)
        coordinator.worker = FakeWorker()
        coordinator.started = True
        await coordinator.stop()
        assert coordinator.worker.stop_calls == 1
        assert coordinator.started is False

    asyncio.run(run())
