"""Durable automatic-voting tick endpoint.

Supabase Cron calls this endpoint every second. It never sleeps: it only checks
the persisted voting deadline and advances an overdue target.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

_runtime_module: Any = None
_startup_complete = False
_loop: asyncio.AbstractEventLoop | None = None


def _runtime():
    global _runtime_module
    if _runtime_module is None:
        import player_runtime_entry
        _runtime_module = player_runtime_entry
    return _runtime_module


async def _tick() -> bool:
    global _startup_complete
    runtime_entry = _runtime()
    if not _startup_complete:
        await runtime_entry.on_startup(runtime_entry.main.dp)
        _startup_complete = True
    from runtime import voting_runtime
    return bool(await voting_runtime.tick(runtime_entry.main))


def _run(coro):
    global _loop
    if _loop is None or _loop.is_closed():
        _loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_loop)
    return _loop.run_until_complete(coro)


def app(environ: dict[str, Any], start_response: Any) -> list[bytes]:
    method = str(environ.get("REQUEST_METHOD", "GET")).upper()
    if method not in {"GET", "POST"}:
        body = b'{"ok":false,"error":"method_not_allowed"}'
        start_response("405 Method Not Allowed", [("Content-Type", "application/json"), ("Content-Length", str(len(body)))])
        return [body]
    try:
        changed = _run(_tick())
        payload = json.dumps({"ok": True, "changed": changed}, ensure_ascii=False).encode("utf-8")
        start_response("200 OK", [("Content-Type", "application/json"), ("Content-Length", str(len(payload)))])
        return [payload]
    except Exception:
        logging.exception("VOTING TICK FAILED")
        body = b'{"ok":false,"error":"tick_failed"}'
        start_response("200 OK", [("Content-Type", "application/json"), ("Content-Length", str(len(body)))])
        return [body]


handler = app
main = app
