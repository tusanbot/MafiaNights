"""Synchronous loader for the production consistency runtime patch."""
from __future__ import annotations

import asyncio
from typing import Any

from runtime.production_consistency_v4 import install as _install_async


def _handler(item: Any):
    return getattr(item, "handler", None) or getattr(item, "callback", None)


def _move_module_handlers_front(dp: Any, module_name: str) -> dict[str, int]:
    """Make the canonical runtime handlers win over legacy broad handlers.

    aiogram 2.x dispatches callback/message handlers in registration order. The
    production consistency installer is intentionally loaded after the legacy
    runtime modules, so its exact handlers must be moved ahead of older broad
    handlers; otherwise callbacks such as game_end:*:result are consumed by
    the old game_end:* handler before the consistency handlers can run.
    """
    moved = {"callback": 0, "message": 0}
    for registry_name, key in (("callback_query_handlers", "callback"), ("message_handlers", "message")):
        registry = getattr(getattr(dp, registry_name, None), "handlers", None)
        if registry is None:
            continue
        selected = []
        remaining = []
        for item in registry:
            fn = _handler(item)
            if getattr(fn, "__module__", "") == module_name:
                selected.append(item)
            else:
                remaining.append(item)
        if selected:
            registry[:] = selected + remaining
            moved[key] = len(selected)
    return moved


def install(app: Any) -> bool:
    """Run the async registration routine during application initialization."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        installed = bool(asyncio.run(_install_async(app)))
    else:
        raise RuntimeError("production consistency installer must initialize before the polling event loop")

    # Registration is not enough in aiogram 2.x: handlers are evaluated in
    # list order. The v4 installer is loaded after legacy modules, so promote
    # every handler it owns to the front of both dispatcher registries.
    moved = _move_module_handlers_front(app.dp, "runtime.production_consistency_v4")
    app._production_consistency_handler_priority = moved
    return installed
