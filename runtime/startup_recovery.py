"""Startup hook helpers for the persistent Mafia runtime."""
from __future__ import annotations

import logging
from typing import Any

from runtime.game_runtime import PersistentGameRuntime


async def recover_persisted_games(legacy: Any) -> list[dict[str, Any]]:
    """Recover persisted games after bot startup and restart expired turns safely."""
    runtime = getattr(legacy, "persistent_runtime", None)
    if runtime is None:
        runtime = PersistentGameRuntime()
        legacy.persistent_runtime = runtime
    results: list[dict[str, Any]] = []
    for plan in runtime.recovery.recovery_plans():
        group_id = int(plan["group_chat_id"])
        try:
            if plan.get("expired") and plan.get("turn_id"):
                runtime.recovery.finish_expired(group_id)
                results.append({"group_chat_id": group_id, "action": "expired_turn_finished"})
                continue
            results.append(plan)
        except Exception:
            logging.exception("startup recovery failed for group %s", group_id)
            results.append({"group_chat_id": group_id, "action": "error"})
    return results
