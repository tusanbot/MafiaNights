"""Vercel-compatible WSGI Telegram webhook entry point for MafiaNights."""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any

_seen_updates: set[int] = set()
_runtime_module: Any = None
_startup_complete = False


def _response(body: dict[str, Any], status: str = "200 OK") -> tuple[str, list[tuple[str, str]], bytes]:
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    return status, [("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(payload)))], payload


def _authorized(environ: dict[str, Any]) -> bool:
    expected = os.getenv("TELEGRAM_WEBHOOK_SECRET")
    if not expected:
        return True
    actual = environ.get("HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN")
    return actual == expected


def _get_runtime() -> Any:
    global _runtime_module
    if _runtime_module is None:
        import player_runtime_entry as runtime_entry
        _runtime_module = runtime_entry
    return _runtime_module


async def _ensure_startup() -> None:
    """Run canonical production startup once without poisoning a warm instance."""
    global _startup_complete
    if _startup_complete:
        return
    runtime_entry = _get_runtime()
    try:
        await runtime_entry.on_startup(runtime_entry.main.dp)
    except Exception:
        import logging
        logging.exception("Telegram startup failed; continuing update dispatch")
    finally:
        # Startup is best-effort on webhook workers. Do not retry the entire
        # bootstrap on every Telegram update if an optional recovery component fails.
        _startup_complete = True


async def _dispatch_priority_message(message: Any, runtime_entry: Any) -> bool:
    """Handle the two canonical entry commands before aiogram handler dispatch.

    Telegram webhook traffic reaches this module first. Routing these exact
    entry messages here makes the production owners deterministic even if an
    older message handler was registered later by another compatibility layer.
    """
    text = str(getattr(message, "text", "") or "").strip().replace("\u200c", " ")
    normalized = " ".join(text.split())
    if normalized:
        first = normalized.split(" ", 1)[0].casefold()
        if first.startswith("/start"):
            command = first[1:]
            if command == "start" or command.startswith("start@"):
                handler = getattr(runtime_entry, "_production_start", None)
                if handler is not None:
                    await handler(message)
                    import logging
                    logging.info(
                        "WEBHOOK CANONICAL /START ROUTE chat_type=%s user_id=%s",
                        getattr(getattr(message, "chat", None), "type", None),
                        getattr(getattr(message, "from_user", None), "id", None),
                    )
                    return True
        if normalized == "بازی جدید":
            handler = getattr(runtime_entry.main, "_canonical_new_game_handler", None)
            if handler is not None:
                from types import SimpleNamespace
                callback = SimpleNamespace(
                    message=message,
                    from_user=message.from_user,
                    data="fl_new",
                    answer=message.answer,\n                    _from_text_command=True,
                )
                await handler(callback)
                import logging
                logging.info(
                    "WEBHOOK CANONICAL NEW_GAME ROUTE chat_type=%s user_id=%s",
                    getattr(getattr(message, "chat", None), "type", None),
                    getattr(getattr(message, "from_user", None), "id", None),
                )
                return True
    return False


async def _dispatch(payload: dict[str, Any]) -> None:
    from aiogram import Bot, Dispatcher, types

    runtime_entry = _get_runtime()
    await _ensure_startup()
    update = types.Update(**payload)
    Bot.set_current(runtime_entry.main.bot)
    Dispatcher.set_current(runtime_entry.main.dp)
    if getattr(update, "message", None) is not None:
        if await _dispatch_priority_message(update.message, runtime_entry):
            return
    callback = getattr(update, "callback_query", None)
    if callback is not None and str(getattr(callback, "data", "") or "") in {"fl_new", "new_game"}:
        handler = getattr(runtime_entry.main, "_canonical_new_game_handler", None)
        if handler is not None:
            await handler(callback)
            import logging
            logging.info(
                "WEBHOOK CANONICAL NEW_GAME CALLBACK ROUTE chat_type=%s user_id=%s data=%s",
                getattr(getattr(callback, "message", None).chat, "type", None),
                getattr(getattr(callback, "from_user", None), "id", None),
                getattr(callback, "data", None),
            )
            return
    await runtime_entry.main.dp.process_update(update)


def app(environ: dict[str, Any], start_response: Any) -> list[bytes]:
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

    try:
        asyncio.run(_dispatch(payload))
    except Exception:
        import logging
        logging.exception("Telegram webhook dispatch failed")
        status, headers, body = _response({"ok": False, "error": "dispatch_failed"}, "200 OK")
        start_response(status, headers)
        return [body]

    status, headers, body = _response({"ok": True})
    start_response(status, headers)
    return [body]


handler = app
main = app
