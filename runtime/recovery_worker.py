from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

from runtime.game_state import GameState


@dataclass(frozen=True)
class RecoveryPlan:
    game_id: str
    group_chat_id: int
    status: str
    turn_id: Optional[str]
    deadline_epoch: Optional[float]
    remaining_seconds: Optional[float]
    recoverable: bool


class RecoveryWorker:
    """Rebuilds ephemeral timer workers from authoritative persisted game state.

    The database remains the source of truth. This worker never stores game
    state itself; its registry only contains asyncio Tasks that can be rebuilt.
    """

    def __init__(self, state: Optional[GameState] = None):
        self.state = state or GameState()
        self._tasks: dict[str, asyncio.Task] = {}

    def plans(self, now: Optional[float] = None) -> list[RecoveryPlan]:
        now = time.time() if now is None else float(now)
        plans: list[RecoveryPlan] = []
        for game in self.state.active_games():
            game_id = str(game["id"])
            group_chat_id = int(game["group_chat_id"])
            status = str(game.get("status") or "running").lower()
            turn = self.state.turns.current_turn(game_id)
            if not turn:
                plans.append(RecoveryPlan(game_id, group_chat_id, status, None, None, None, False))
                continue
            deadline = None
            if turn.get("started_at") and turn.get("duration_seconds") is not None:
                started = turn["started_at"]
                if started.tzinfo is None:
                    from datetime import timezone
                    started = started.replace(tzinfo=timezone.utc)
                deadline = started.timestamp() + int(turn["duration_seconds"])
            remaining = max(0.0, deadline - now) if deadline is not None else None
            plans.append(RecoveryPlan(
                game_id=game_id,
                group_chat_id=group_chat_id,
                status=status,
                turn_id=str(turn["id"]),
                deadline_epoch=deadline,
                remaining_seconds=remaining,
                recoverable=True,
            ))
        return plans

    async def recover(
        self,
        on_turn_expired: Callable[[RecoveryPlan], Awaitable[None]],
    ) -> list[RecoveryPlan]:
        """Schedule one timer per active persisted turn and return recovery plans.

        Expired turns are dispatched immediately. Already-running tasks are not
        duplicated, which makes repeated startup recovery safe.
        """
        plans = self.plans()
        for plan in plans:
            if not plan.recoverable or not plan.turn_id:
                continue
            task = self._tasks.get(plan.turn_id)
            if task and not task.done():
                continue
            self._tasks[plan.turn_id] = asyncio.create_task(
                self._wait_and_dispatch(plan, on_turn_expired)
            )
        return plans

    async def _wait_and_dispatch(
        self,
        plan: RecoveryPlan,
        on_turn_expired: Callable[[RecoveryPlan], Awaitable[None]],
    ) -> None:
        remaining = plan.remaining_seconds or 0.0
        if remaining > 0:
            await asyncio.sleep(remaining)
        # Re-check the persisted turn before dispatching so a manually finished
        # turn cannot be advanced by a stale worker.
        current = self.state.turns.current_turn(plan.game_id)
        if not current or str(current.get("id")) != plan.turn_id:
            return
        await on_turn_expired(plan)

    async def stop(self) -> None:
        tasks = list(self._tasks.values())
        self._tasks.clear()
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    @property
    def running_turn_ids(self) -> set[str]:
        return {turn_id for turn_id, task in self._tasks.items() if not task.done()}
