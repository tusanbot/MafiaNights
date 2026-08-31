"""Vercel-compatible Telegram webhook entry point for MafiaNights."""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any

_seen_updates: set[int] = set()
_app: Any = None


def _json_response(body: dict[str, Any], status: int = 200) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json; charset=utf-8"},
        "body": json.dumps(body, ensure_ascii=False),
    }


def _header(headers: Any, name: str) -> str | None:
    if hasattr(headers, "get"):
        return headers.get(name) or headers.get(name.lower())
    return None


def _authorized(headers: Any) -> bool:
    expected = os.getenv("TELEGRAM_WEBHOOK_SECRET")
    if not expected:
        return True
    return _header(headers, "x-telegram-bot-api-secret-token") == expected


def _request_value(request: Any, name: str, default: Any = None) -> Any:
    value = getattr(request, name, None)
    if value is not None:
        return value
    if isinstance(request, dict):
        return request.get(name, default)
    return default


def _get_application() -> Any:
    global _app
    if _app is None:
        from main_refactored_v4 import MafiaApplicationV4

        token = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("API_TOKEN")
        if not token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")
        _app = MafiaApplicationV4(token)
    return _app


async def _dispatch(payload: dict[str, Any]) -> None:
    from aiogram import types

    app = _get_application()
    update = types.Update(**payload)
    await app.dp.process_update(update)


def handler(request: Any) -> Any:
    """Accept one Telegram Update and dispatch it through aiogram."""
    method = str(_request_value(request, "method", "GET")).upper()
    if method == "GET":
        return _json_response({"ok": True, "service": "mafia-nights-telegram"})
    if method != "POST":
        return _json_response({"ok": False, "error": "method_not_allowed"}, 405)

    headers = _request_value(request, "headers", {})
    if not _authorized(headers):
        return _json_response({"ok": False, "error": "unauthorized"}, 401)

    raw = _request_value(request, "body", "")
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    try:
        payload = json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError):
        return _json_response({"ok": False, "error": "invalid_json"}, 400)
    if not isinstance(payload, dict):
        return _json_response({"ok": False, "error": "invalid_update"}, 400)

    update_id = payload.get("update_id")
    if isinstance(update_id, int):
        if update_id in _seen_updates:
            return _json_response({"ok": True, "duplicate": True})
        _seen_updates.add(update_id)
        if len(_seen_updates) > 5000:
            _seen_updates.clear()
            _seen_updates.add(update_id)

    asyncio.run(_dispatch(payload))
    return _json_response({"ok": True})


main = handler
