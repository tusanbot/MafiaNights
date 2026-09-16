"""Startup hook helpers for the persistent Mafia runtime."""
from __future__ import annotations

import logging
from typing import Any

from runtime.game_runtime import PersistentGameRuntime


async def recover_persisted_games(legacy: Any) -> list[dict[str, Any]]:
    """Recover persisted games after bot startup without blocking webhook dispatch.

    Recovery is auxiliary state restoration. A malformed/stale persisted game or
    a transient database problem must never prevent Telegram updates from being
    processed, especially on request-driven Vercel deployments.
    """
    runtime = getattr(legacy, "persistent_runtime", None)
    if runtime is None:
        runtime = PersistentGameRuntime()
        legacy.persistent_runtime = runtime
    results: list[dict[str, Any]] = []
    try:
        plans = runtime.recovery.recovery_plans()
    except Exception:
        logging.exception("startup recovery plan discovery failed; continuing without recovery")
        return [{"action": "recovery_skipped", "reason": "plan_discovery_failed"}]

    for plan in plans:
        try:
            group_id = int(plan["group_chat_id"])
            if plan.get("expired") and plan.get("turn_id"):
                runtime.recovery.finish_expired(group_id)
                results.append({"group_chat_id": group_id, "action": "expired_turn_finished"})
            else:
                results.append(plan)
        except Exception:
            logging.exception("startup recovery failed for persisted plan")
            results.append({
                "group_chat_id": plan.get("group_chat_id") if isinstance(plan, dict) else None,
                "action": "error",
            })
    return results
