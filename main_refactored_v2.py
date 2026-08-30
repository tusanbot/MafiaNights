"""MafiaNights clean application with legacy feature parity.

This is a migration target. ``main.py`` remains untouched as the rollback
reference and ``main_refactored.py`` remains the previous clean baseline.
"""
from __future__ import annotations

import os

from main_refactored import MafiaApplication
from runtime.feature_parity import FeatureParity


class MafiaApplicationV2(MafiaApplication):
    """Clean application plus compatibility feature-parity surface."""

    def __init__(self, token: str):
        super().__init__(token)
        self.feature_parity = FeatureParity(self)
        self.feature_parity.register()

        # The clean base uses ``join``/``leave`` and the new callbacks. The
        # parity surface additionally accepts the legacy callback names so
        # existing Telegram messages/buttons remain usable during cut-over.
        self.dp.register_callback_query_handler(
            self.feature_parity.open_panel,
            lambda c: c.data == "manage_game",
        )
        self.dp.register_callback_query_handler(
            self.feature_parity.scenario_menu,
            lambda c: c.data == "manage_scenarios",
        )
        self.dp.register_callback_query_handler(
            self.feature_parity.resend_roles,
            lambda c: c.data == "resend_roles",
        )
        self.dp.register_callback_query_handler(
            self.feature_parity.remove_player,
            lambda c: c.data == "remove_player",
        )
        self.dp.register_callback_query_handler(
            self.feature_parity.replace_player,
            lambda c: c.data == "replace_player",
        )
        self.dp.register_callback_query_handler(
            self.feature_parity.revive_player,
            lambda c: c.data == "player_birthday",
        )
        self.dp.register_callback_query_handler(
            self.feature_parity.challenge_request,
            lambda c: c.data.startswith("challenge_request_"),
        )
        self.dp.register_callback_query_handler(
            self.feature_parity.challenge_response,
            lambda c: c.data.startswith("accept_before_")
            or c.data.startswith("accept_after_")
            or c.data.startswith("reject_"),
        )


TOKEN = os.getenv("API_TOKEN")
if not TOKEN:
    raise ValueError("API_TOKEN environment variable is not set!")

app = MafiaApplicationV2(TOKEN)
bot = app.bot
dp = app.dp


async def on_startup(dp):
    await app.startup()


async def on_shutdown(dp):
    await app.shutdown()


if __name__ == "__main__":
    from aiogram.utils import executor

    executor.start_polling(dp, skip_updates=True, on_startup=on_startup, on_shutdown=on_shutdown)
