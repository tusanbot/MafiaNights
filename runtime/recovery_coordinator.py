"""Application-level startup/shutdown lifecycle for persisted game recovery."""
from __future__ import annotations

from typing import Awaitable, Callable, Optional

from runtime.game_state import GameState
from runtime.recovery_worker import RecoveryPlan, RecoveryWorker


TurnExpiredCallback = Callable[[RecoveryPlan], Awaitable[None]]


class RecoveryCoordinator:
    """Owns one RecoveryWorker for the bot process.

    The coordinator deliberately does not implement game advancement. The
    callback is supplied by the Telegram/application layer, while recovery
    itself remains persistence-driven and Telegram-independent.
    """

    def __init__(self, state: Optional[GameState] = None):
        self.state = state or GameState()
        self.worker = RecoveryWorker(self.state)
        self.started = False

    async def start(self, on_turn_expired: TurnExpiredCallback) -> list[RecoveryPlan]:
        if self.started:
            return self.worker.plans()
        plans = await self.worker.recover(on_turn_expired)
        self.started = True
        return plans

    async def stop(self) -> None:
        if not self.started and not self.worker.running_turn_ids:
            return
        await self.worker.stop()
        self.started = False

    @property
    def running_turn_ids(self) -> set[str]:
        return self.worker.running_turn_ids
