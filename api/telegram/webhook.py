"""Vercel-compatible WSGI Telegram webhook entry point for MafiaNights."""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any

_seen_updates: set[int] = set()
_app: Any = None


def _response(body: dict[str, Any], status: str = "200 OK") -> tuple[str, list[tuple[str, str]], bytes]:
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    return status, [("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(payload)))], payload


def _authorized(environ: dict[str, Any]) -> bool:
    expected = os.getenv("TELEGRAM_WEBHOOK_SECRET")
    if not expected:
        return True
    actual = environ.get("HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN")
    return actual == expected


def _get_application() -> Any:
    """Return the staged production entry, not the incomplete refactor target.

    ``main_refactored.py`` is only a migration scaffold and does not define a
    MafiaApplication class. The actual production cut-over is installed by
    ``player_runtime_entry.py`` around the preserved legacy module ``main1``.
    """
    global _app
    if _app is None:
        import player_runtime_entry

        _app = player_runtime_entry.main
    return _app


async def _dispatch(payload: dict[str, Any]) -> None:
    from aiogram import Bot, types

    app = _get_application()
    update = types.Update(**payload)

    # aiogram 2.x resolves message.answer()/bot.send_message() through
    # the current Bot context. A custom WSGI webhook does not establish it.
    Bot.set_current(app.bot)
    try:
        await app.dp.process_update(update)
    finally:
        # aiogram 2.x rejects Bot.set_current(None). reset_current() is the
        # supported way to clear the context and prevents a successful update
        # from ending with a secondary TypeError/500 response.
        Bot.reset_current()


def app(environ: dict[str, Any], start_response: Any) -> list[bytes]:
    """WSGI application accepted by the Vercel Python runtime."""
    method = str(environ.get("REQUEST_METHOD", "GET")).upper()

    if method == "GET":
        status, headers, body = _response({"ok": True, "service": "mafia-nights-telegram"})
        start_response(status, headers)
        return [body]

    if method != "POST":
        status, headers, body = _response({"ok": False, "error": "method_not_allowed"}, "405 Method Not Allowed")
        start_response(status, headers)
        return [body]

    if not _authorized(environ):
        status, headers, body = _response({"ok": False, "error": "unauthorized"}, "401 Unauthorized")
        start_response(status, headers)
        return [body]

    try:
        length = int(environ.get("CONTENT_LENGTH") or "0")
    except (TypeError, ValueError):
        length = 0

    raw = environ.get("wsgi.input").read(length) if environ.get("wsgi.input") else b""
    try:
        payload = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw or "{}")
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError):
        status, headers, body = _response({"ok": False, "error": "invalid_json"}, "400 Bad Request")
        start_response(status, headers)
        return [body]

    if not isinstance(payload, dict):
        status, headers, body = _response({"ok": False, "error": "invalid_update"}, "400 Bad Request")
        start_response(status, headers)
        return [body]

    update_id = payload.get("update_id")
    if isinstance(update_id, int):
        if update_id in _seen_updates:
            status, headers, body = _response({"ok": True, "duplicate": True})
            start_response(status, headers)
            return [body]
        _seen_updates.add(update_id)
        if len(_seen_updates) > 5000:
            _seen_updates.clear()
            _seen_updates.add(update_id)

    asyncio.run(_dispatch(payload))
    status, headers, body = _response({"ok": True})
    start_response(status, headers)
    return [body]


handler = app
