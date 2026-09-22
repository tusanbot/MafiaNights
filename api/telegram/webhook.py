"""Vercel-compatible WSGI Telegram webhook entry point for MafiaNights."""
from __future__ import annotations

import asyncio
import json
import os
import logging
from typing import Any

_seen_updates: set[int] = set()
_runtime_module: Any = None
_startup_complete = False
# Keep one event loop alive for the lifetime of a warm Vercel worker. aiogram v2
# and aiohttp objects created by the production runtime are loop-bound; creating
# a new loop with asyncio.run() for every Telegram update can detach the Bot
# session from the loop that owns it and causes:
# "RuntimeError: Timeout context manager should be used inside a task".
_webhook_loop: asyncio.AbstractEventLoop | None = None


def _run_on_webhook_loop(coro: Any) -> Any:
    global _webhook_loop
    if _webhook_loop is None or _webhook_loop.is_closed():
        _webhook_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_webhook_loop)
    return _webhook_loop.run_until_complete(coro)


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


async def _registration_guard(message: Any, runtime_entry: Any) -> bool:
    from runtime import registration
    uid = getattr(getattr(message, "from_user", None), "id", None)
    if uid is None:
        return False
    text_value = str(getattr(message, "text", "") or "").strip()
    normalized = " ".join(text_value.replace("\\u200c", " ").split())
    if normalized.casefold().startswith("/start"):
        return False
    try:
        dp = runtime_entry.main.dp
        chat_id = getattr(getattr(message, "chat", None), "id", None)
        if chat_id is not None:
            state = dp.current_state(chat=chat_id, user=int(uid))
            if await state.get_state():
                return False
    except Exception:
        logging.exception("registration FSM state check failed")
    if registration.is_registered(int(uid)):
        return False
    await registration.prompt_registration(message, runtime_entry.main, group=getattr(getattr(message, "chat", None), "type", None) in {"group", "supergroup"})
    logging.info("REGISTRATION REQUIRED user_id=%s chat_type=%s", uid, getattr(getattr(message, "chat", None), "type", None))
    return True


async def _dispatch_priority_message(message: Any, runtime_entry: Any) -> bool:
    """Handle the two canonical entry commands before aiogram handler dispatch.

    Telegram webhook traffic reaches this module first. Routing these exact
    entry messages here makes the production owners deterministic even if an
    older message handler was registered later by another compatibility layer.
    """
    text = str(getattr(message, "text", "") or "").strip().replace("\u200c", " ")
    normalized = " ".join(text.split())
    if normalized:
        # /start is an entry-point command, not registration input. It must
        # always win over an active registration FSM, because Telegram deep
        # links can deliver /start while a stale waiting_name state still
        # exists. Previously the FSM guard ran first and save_name could
        # consume "/start" as the user's nickname.
        first = normalized.split(" ", 1)[0].casefold()
        if first.startswith("/start"):
            command = first[1:]
            if command == "start" or command.startswith("start@"):
                handler = getattr(runtime_entry, "_production_start", None)
                if handler is not None:
                    await handler(message)
                    logging.info(
                        "WEBHOOK CANONICAL /START ROUTE chat_type=%s user_id=%s",
                        getattr(getattr(message, "chat", None), "type", None),
                        getattr(getattr(message, "from_user", None), "id", None),
                    )
                    return True

        # An active aiogram FSM owns the next user message. Do not let the
        # global canonical command router consume profile/setup input.
        try:
            dp = runtime_entry.main.dp
            chat_id = getattr(getattr(message, "chat", None), "id", None)
            user_id = getattr(getattr(message, "from_user", None), "id", None)
            if chat_id is not None and user_id is not None:
                fsm_state = dp.current_state(chat=chat_id, user=user_id)
                if await fsm_state.get_state():
                    return False
        except Exception:
            logging.exception("webhook FSM state check failed; continuing canonical routing")

        # Canonical production text-command routing happens here rather than
        # through mutable aiogram handler ordering. Legacy/feature installers
        # register catch-all text handlers, so dispatcher reordering alone is
        # not a reliable authority.
        try:
            from commands import resolve_command, run_command
            command_name = resolve_command(normalized)
        except Exception:
            command_name = None

        if command_name:
            # Preserve speaking-lock enforcement before executing a group
            # command. commands.py remains the sole owner of command behavior.
            if getattr(message, "chat", None) is not None and message.chat.type in {"group", "supergroup"}:
                try:
                    from runtime.chat_locks import _message_guard
                    await _message_guard(message, runtime_entry.main)
                except Exception as exc:
                    from aiogram.dispatcher.handler import CancelHandler
                    if isinstance(exc, CancelHandler):
                        return True
                    raise

            await run_command(command_name, message, runtime_entry.main)
            import logging
            logging.info(
                "WEBHOOK CANONICAL TEXT COMMAND ROUTE command=%s chat_type=%s user_id=%s",
                command_name,
                getattr(getattr(message, "chat", None), "type", None),
                getattr(getattr(message, "from_user", None), "id", None),
            )
            return True
    return False

async def _dispatch_registration_message(message: Any, runtime_entry: Any) -> bool:
    """Own the registration name message before generic dispatcher handlers.

    Registration runs across separate Vercel webhook invocations, so the name
    step must not depend on handler ordering or an in-memory FSM surviving the
    previous request. Prefer the persisted FSM state; if it is missing, an
    unregistered private user may recover by sending a valid Persian name.
    """
    from runtime import registration
    if getattr(getattr(message, "chat", None), "type", None) != "private":
        return False
    uid = getattr(getattr(message, "from_user", None), "id", None)
    if uid is None or registration.is_registered(int(uid)):
        return False
    text_value = str(getattr(message, "text", "") or "").strip()
    if not text_value or text_value.startswith("/"):
        return False

    try:
        dp = runtime_entry.main.dp
        state = dp.current_state(chat=message.chat.id, user=int(uid))
        current = await state.get_state()
        waiting = getattr(registration.RegistrationStates.waiting_name, "state", None)
        if current == waiting:
            await registration.save_name(message, state)
            logging.info("WEBHOOK CANONICAL REGISTRATION NAME ROUTE user_id=%s mode=fsm db=mafia_players", uid)
            return True
    except Exception:
        logging.exception("registration FSM name route failed for %s", uid)

    if registration.valid_persian_name(text_value):
        state = runtime_entry.main.dp.current_state(chat=message.chat.id, user=int(uid))
        await registration.save_name(message, state)
        logging.info("WEBHOOK CANONICAL REGISTRATION NAME ROUTE user_id=%s mode=recovery", uid)
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
        if await _dispatch_registration_message(update.message, runtime_entry):
            return
        if await _registration_guard(update.message, runtime_entry):
            return
        if await _dispatch_priority_message(update.message, runtime_entry):
            return
    callback = getattr(update, "callback_query", None)
    if callback is not None:
        data = str(getattr(callback, "data", "") or "")

        # Registration is a protected entry route. It must be handled directly
        # here, before aiogram's callback registry, because several compatibility
        # layers can register/promote broad callback handlers during startup.
        # The private registration button uses exactly this callback_data.
        if data == "registration:start":
            from runtime import registration
            uid = getattr(getattr(callback, "from_user", None), "id", None)
            if uid is not None and not registration.is_registered(int(uid)):
                dp = runtime_entry.main.dp
                state = dp.current_state(
                    chat=callback.message.chat.id,
                    user=int(uid),
                )
                await registration.begin(callback, state)
                logging.info("WEBHOOK CANONICAL REGISTRATION START user_id=%s", uid)
                return
            await callback.answer("✅ حساب شما قبلاً ثبت شده است.", show_alert=True)
            return

        from runtime import registration
        uid = getattr(getattr(callback, "from_user", None), "id", None)
        if uid is not None and not registration.is_registered(int(uid)):
            await registration.prompt_registration(
                callback.message,
                runtime_entry.main,
                group=getattr(getattr(callback.message, "chat", None), "type", None)
                in {"group", "supergroup"},
            )
            await callback.answer("🔐 ابتدا ثبت‌نام کنید.", show_alert=True)
            return
    # Voting has its own canonical callback router. Route it before the
    # aiogram dispatcher so generic callback handlers cannot consume a vote,
    # and so the voting callback path stays independent of unrelated startup
    # handlers.
    if callback is not None and str(getattr(callback, "data", "") or "").startswith("vote:"):
        from runtime import voting_runtime
        handled = await voting_runtime.handle_callback(runtime_entry.main, callback)
        if handled:
            logging.info(
                "WEBHOOK CANONICAL VOTE CALLBACK ROUTE user_id=%s data=%s",
                getattr(getattr(callback, "from_user", None), "id", None),
                getattr(callback, "data", None),
            )
            return

    if callback is not None and str(getattr(callback, "data", "") or "") in {"fl_new", "new_game"}:
        handler = getattr(runtime_entry.main, "_canonical_new_game_handler", None)
        if handler is not None:
            await handler(callback)
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
        # Do not use asyncio.run() here. The production aiogram Bot/Dispatcher
        # and their aiohttp session must stay attached to the same event loop
        # across warm webhook invocations.
        _run_on_webhook_loop(_dispatch(payload))
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
