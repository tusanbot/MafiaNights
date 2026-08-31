"""Vercel-compatible Telegram webhook entry point.

Designed for aiogram 2.25.1. The endpoint is intentionally thin: Telegram
updates are authenticated, de-duplicated, and handed to the application.
"""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from main_refactored_v4 import MafiaApplicationV4


_app: MafiaApplicationV4 | None = None
_seen_updates: set[int] = set()


def _get_application() -> MafiaApplicationV4:
    global _app
    if _app is None:
        token = os.getenv("API_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
        if not token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")
        _app = MafiaApplicationV4(token)
    return _app


def _authorized(headers: Any) -> bool:
    expected = os.getenv("TELEGRAM_WEBHOOK_SECRET")
    if not expected:
        return True
    supplied = headers.get("x-telegram-bot-api-secret-token")
    return supplied == expected


def _response(body: dict[str, Any], status: int = 200) -> dict[str, Any]:
    return {"statusCode": status, "headers": {"content-type": "application/json"}, "body": json.dumps(body)}


async def _dispatch(payload: dict[str, Any]) -> None:
    app = _get_application()
    await app.handle_telegram_update(payload)


def handler(request: Any) -> Any:
    """Vercel Python-style handler entry point.

    A small synchronous wrapper is used so the project can later swap this
    transport for another Vercel-compatible adapter without changing the core.
    """
    method = getattr(request, "method", None) or request.get("method", "GET")
    if method != "POST":
        return _response({"ok": True, "service": "mafia-nights-telegram"})
    headers = getattr(request, "headers", None) or request.get("headers", {})
    if not _authorized(headers):
        return _response({"ok": False, "error": "unauthorized"}, 401)
    raw = getattr(request, "body", None)
    if raw is None and isinstance(request, dict):
        raw = request.get("body", "")
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    try:
        payload = json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError):
        return _response({"ok": False, "error": "invalid_json"}, 400)
    update_id = payload.get("update_id")
    if isinstance(update_id, int):
        if update_id in _seen_updates:
            return _response({"ok": True, "duplicate": True})
        _seen_updates.add(update_id)
        if len(_seen_updates) > 5000:
            _seen_updates.clear()
            _seen_updates.add(update_id)
    asyncio.run(_dispatch(payload))
    return _response({"ok": True})


# Common Vercel export spelling.
main = handler
