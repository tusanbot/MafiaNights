"""Durable scheduler tick for MafiaNights voting deadlines."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any

from sqlalchemy import text
from repositories.base import DatabaseRepository
from urllib.request import Request, urlopen

_PRODUCTION_WEBHOOK_HOST = "mafia-nights-tusanbots-projects.vercel.app"
_WEBHOOK_REPAIR_INTERVAL = 60.0
_last_webhook_check = 0.0
_runtime_module: Any = None
_startup_complete = False
_loop: asyncio.AbstractEventLoop | None = None
_last_tick_at = 0.0
_MIN_TICK_INTERVAL = float(os.getenv("TICK_MIN_INTERVAL", "4"))


def _response(body, status="200 OK"):
    raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
    return status, [("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(raw)))], raw


def _telegram_request(token: str, method: str, payload: dict | None = None) -> dict:
    request = Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=json.dumps(payload or {}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _repair_webhook_if_needed() -> dict:
    global _last_webhook_check
    now = time.time()
    if now - _last_webhook_check < _WEBHOOK_REPAIR_INTERVAL:
        return {"checked": False}
    _last_webhook_check = now
    token = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("API_TOKEN")
    if not token:
        return {"checked": False, "reason": "telegram_token_missing"}
    target = f"https://{_PRODUCTION_WEBHOOK_HOST}/api/telegram/webhook"
    info = _telegram_request(token, "getWebhookInfo")
    current = str((info.get("result") or {}).get("url") or "")
    if current == target:
        return {"checked": True, "changed": False}
    result = _telegram_request(
        token,
        "setWebhook",
        {"url": target, **({"secret_token": os.getenv("TELEGRAM_WEBHOOK_SECRET")} if os.getenv("TELEGRAM_WEBHOOK_SECRET") else {})},
    )
    return {"checked": True, "changed": bool(result.get("ok")), "target": target}


def _has_due_vote() -> bool:
    """Cheap database gate: avoid booting the full bot for idle cron ticks."""
    repo = DatabaseRepository()
    with repo.engine.begin() as conn:
        row = conn.execute(text("""
            select 1
            from public.mafia_games
            where coalesce(state->'voting'->>'phase', '') in ('waiting', 'voting')
              and nullif(state->'voting'->>'deadline', '') is not null
              and (state->'voting'->>'deadline')::double precision <= extract(epoch from now())
            limit 1
        """)).first()
        return row is not None


def _runtime():
    global _runtime_module
    if _runtime_module is None:
        import player_runtime_entry
        _runtime_module = player_runtime_entry
    return _runtime_module


async def _tick():
    global _startup_complete
    runtime_entry = _runtime()
    if not _startup_complete:
        try:
            await runtime_entry.on_startup(runtime_entry.main.dp)
        except Exception:
            # Startup helpers are best-effort for the scheduler. Do not retry
            # the entire production bootstrap on every 5-second tick.
            logging.exception("VOTING TICK STARTUP FAILED; continuing")
        finally:
            _startup_complete = True
    from runtime import voting_runtime
    return bool(await voting_runtime.tick(runtime_entry.main))


def _run(coro):
    global _loop
    if _loop is None or _loop.is_closed():
        _loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_loop)
    return _loop.run_until_complete(coro)


def app(environ, start_response):
    global _last_tick_at
    result = {}
    now = time.monotonic()
    if now - _last_tick_at < _MIN_TICK_INTERVAL:
        result.update({"ok": True, "processed": False, "skipped": "rate_limited"})
        status, headers, body = _response(result)
        start_response(status, headers)
        return [body]
    _last_tick_at = now
    try:
        result["webhook_repair"] = _repair_webhook_if_needed()
    except Exception as exc:
        result["webhook_repair"] = {"checked": False, "error": f"{type(exc).__name__}: {exc}"}

    try:
        if not _has_due_vote():
            result.update({"ok": True, "processed": False, "skipped": "no_due_vote"})
            status, headers, body = _response(result)
            start_response(status, headers)
            return [body]
        changed = _run(_tick())
        result.update({"ok": True, "processed": changed})
    except Exception as exc:
        logging.exception("VOTING TICK FAILED")
        result.update({"ok": False, "error": f"{type(exc).__name__}: {exc}"})

    status, headers, body = _response(result)
    start_response(status, headers)
    return [body]


handler = app
