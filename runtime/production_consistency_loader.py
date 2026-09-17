"""Synchronous loader for the production consistency runtime patch."""
from __future__ import annotations

import asyncio
from typing import Any

from runtime.production_consistency_v4 import install as _install_async


def install(app: Any) -> bool:
    """Run the async registration routine during application initialization."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return bool(asyncio.run(_install_async(app)))

    # main.py is normally imported before polling starts. This fallback keeps
    # the loader safe if a caller initializes the application inside a loop.
    raise RuntimeError("production consistency installer must initialize before the polling event loop")
