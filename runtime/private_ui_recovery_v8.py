"""Canonical scenario-management router.

This layer is installed last and gives the actual ScenarioForm manager
priority for every sm2 callback and every ScenarioForm FSM handler. It also
owns final:scenarios so navigation cannot fall into an older handler.
"""
from __future__ import annotations

import logging
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.handler import CancelHandler


def _private(c):
    return bool(getattr(c, "message", None) and getattr(c.message.chat, "type", None) == "private")


def _handler(item):
    return getattr(item, "handler", None) or getattr(item, "callback", None)


def _promote_owned(handlers, manager):
    if handlers is None:
        return 0
    owned, rest = [], []
    for h in list(handlers):
        fn = _handler(h)
        if getattr(fn, "__self__", None) is manager:
            owned.append(h)
        else:
            rest.append(h)
    handlers[:] = owned + rest
    return len(owned)


async def install(app):
    dp = app.dp
    cq = getattr(getattr(dp, "callback_query_handlers", None), "handlers", None)
    mh = getattr(getattr(dp, "message_handlers", None), "handlers", None)
    if cq is None or getattr(app, "_private_ui_recovery_v8", False):
        return False

    manager = getattr(app, "_private_scenario_manager", None)
    if manager is None:
        logging.error("PRIVATE UI V8: scenario manager is missing")
        return False

    async def scenario_root(c, state: FSMContext):
        if not _private(c):
            raise CancelHandler()
        try:
            await state.finish()
        except Exception:
            pass
        try:
            await manager.menu(c)
        except CancelHandler:
            raise
        except Exception:
            logging.exception("PRIVATE UI V8: scenario root failed")
            await c.answer("❌ مدیریت سناریو باز نشد.", show_alert=True)
        raise CancelHandler()

    dp.register_callback_query_handler(scenario_root, lambda c: c.data == "final:scenarios", state="*")

    promoted_cq = _promote_owned(cq, manager)
    promoted_mh = _promote_owned(mh, manager)

    current = list(cq)
    roots = [h for h in current if _handler(h) is scenario_root]
    cq[:] = roots + [h for h in current if h not in roots]

    app._private_ui_recovery_v8 = True
    logging.info("PRIVATE UI RECOVERY V8 ACTIVE scenario_callbacks=%s scenario_messages=%s", promoted_cq, promoted_mh)
    return True
