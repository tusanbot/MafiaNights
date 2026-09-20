"""Deterministic top-level router for assistant-admin callbacks.

Aiogram 2.x dispatches callback handlers in registration order. Mafia Nights
has several legacy/private callback routers, so the assistant panel must have
one explicit owner for every aip:* callback.
"""
from __future__ import annotations

import logging
from typing import Any

from aiogram import types
from aiogram.dispatcher.handler import CancelHandler


async def dispatch_assistant_callback(
    callback: types.CallbackQuery,
    state: Any,
    panel: Any,
) -> None:
    data = str(callback.data or "")
    if not data.startswith("aip:"):
        return

    action = data.split(":", 2)[1]
    handlers = {
        "select": panel.select_group,
        "menu": panel.menu,
        "kb": panel.kb,
        "doc": panel.doc,
        "publish": panel.publish,
        "disable": panel.disable,
        "add": panel.add_start,
        "guide": panel.guide,
        "scope": panel.scope,
        "status": panel.status,
        "ai": panel.ai,
        "toggle_group": panel.toggle_group,
        "pv": panel.pv,
        "groupkey": panel.group_key,
        "pvtoggle": panel.pv_toggle,
    }
    handler = handlers.get(action)
    if handler is None:
        await callback.answer("❌ گزینه پنل دستیار ناشناخته است.", show_alert=True)
        raise CancelHandler()

    try:
        # scope/add/groupkey need FSMContext; all other panel callbacks accept only callback.
        if action in {"scope", "add", "groupkey"}:
            await handler(callback, state)
        else:
            await handler(callback)
    except CancelHandler:
        raise
    except Exception:
        logging.exception("assistant callback failed: %s", data)
        try:
            await callback.answer("❌ اجرای این گزینه انجام نشد.", show_alert=True)
        except Exception:
            pass
    raise CancelHandler()


def install(app: Any) -> bool:
    if getattr(app, "_assistant_callback_router_installed", False):
        return False

    panel = getattr(app, "assistant_admin_panel", None)
    if panel is None:
        raise RuntimeError("assistant admin panel must be installed before callback router")

    dp = app.dp

    async def router(callback: types.CallbackQuery, state: Any):
        await dispatch_assistant_callback(callback, state, panel)

    dp.register_callback_query_handler(
        router,
        lambda c: str(c.data or "").startswith("aip:"),
        state="*",
    )

    # This is intentionally the first callback handler. Do not rely on moving
    # bound-method HandlerObjects around: other routers may be installed later.
    handlers = getattr(dp.callback_query_handlers, "handlers", [])
    for item in list(handlers):
        fn = getattr(item, "handler", None) or getattr(item, "callback", None)
        if fn is router:
            try:
                handlers.remove(item)
            except ValueError:
                pass
            handlers.insert(0, item)
            break

    app._assistant_callback_router_installed = True
    logging.info("ASSISTANT CALLBACK ROUTER ACTIVE: aip:* owns all assistant callbacks")
    return True
