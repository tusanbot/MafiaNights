"""MafiaNights production compatibility wrapper (v5)."""
from __future__ import annotations

import os
import sys
import types
from pathlib import Path
from typing import Any

# Temporary single-group test configuration.
# Keep this explicit until multi-group registration/approval is implemented.
TEST_ACTIVE_GROUP_ID = -1002356353761


def _load_base_class() -> type:
    source = Path(__file__).with_name("main_refactored.py").read_text(encoding="utf-8")
    marker = "\nTOKEN = os.getenv(\"API_TOKEN\")"
    source = source.split(marker, 1)[0]
    module_name = "mafia_nights_base_runtime"
    module = types.ModuleType(module_name)
    module.__file__ = str(Path(__file__).with_name("main_refactored.py"))
    module.__package__ = ""
    sys.modules[module_name] = module
    try:
        exec(compile(source, "main_refactored.py", "exec"), module.__dict__)
        # The current migration target still uses a single hardcoded allowed
        # group. Override it in the dynamically loaded module so the test
        # group is active without modifying the legacy/reference file.
        module.__dict__["ALLOWED_GROUP_ID"] = TEST_ACTIVE_GROUP_ID
        return module.__dict__["MafiaApplication"]
    except Exception:
        sys.modules.pop(module_name, None)
        raise


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
