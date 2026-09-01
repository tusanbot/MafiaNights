"""MafiaNights production compatibility wrapper (v5).

Loads the migration class definitions without executing the module-level app
instances in the legacy migration files. This is required for Vercel's
serverless webhook path, where importing v4 otherwise imports main_refactored
and constructs an application before the compatibility shim can run.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def _load_base_class() -> type:
    source = Path(__file__).with_name("main_refactored.py").read_text(encoding="utf-8")
    marker = "\nTOKEN = os.getenv(\"API_TOKEN\")"
    source = source.split(marker, 1)[0]
    namespace: dict[str, Any] = {"__name__": "mafia_nights_base_runtime"}
    exec(compile(source, "main_refactored.py", "exec"), namespace)
    return namespace["MafiaApplication"]


MafiaApplication = _load_base_class()


class MafiaApplicationV5(MafiaApplication):
    """Compatibility application with the roles handler/store collision fixed."""

    def _register_handlers(self) -> None:
        role_store: Any = getattr(self, "roles", None)
        if isinstance(role_store, dict):
            delattr(self, "roles")
        try:
            super()._register_handlers()
        finally:
            self.roles = role_store if isinstance(role_store, dict) else {}


TOKEN = os.getenv("API_TOKEN")
if not TOKEN:
    raise ValueError("API_TOKEN environment variable is not set!")

app = MafiaApplicationV5(TOKEN)
bot = app.bot
dp = app.dp


async def on_startup(dp):
    await app.startup()


async def on_shutdown(dp):
    await app.shutdown()
