"""Management navigation compatibility helpers.

Keeps the management panel reusable while making the close action restore the
canonical lobby instead of deleting the lobby message. Also exposes a small
text command for rebuilding the lobby message when an inline message gets
lost or needs to be restored.
"""
from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

from aiogram import types
from aiogram.types import InlineKeyboardButton

from runtime.game_management import GameManagement


async def _answer(_: Any, *args: Any, **kwargs: Any) -> None:
    return None


def _callback_like(message: types.Message, game_id: int) -> Any:
    return SimpleNamespace(
        message=message,
        from_user=message.from_user,
        data=f"mgmt:{int(game_id)}:refresh",
        answer=_answer,
    )


def install(app: Any, management: GameManagement) -> bool:
    """Patch management navigation before handlers are registered."""
    original_close = getattr(GameManagement, "close", None)
    original_panel = GameManagement.panel
    original_install = getattr(management, "install", None)

    if original_close is None:
        logging.warning("MANAGEMENT_NAVIGATION: close handler not found")
        return False

    async def close_to_previous_or_lobby(self: GameManagement, callback: Any):
        """Close management by restoring the canonical lobby in-place."""
        gid = int(callback.message.chat.id)
        game = self._game(gid)
        if not game or not await self._allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید یا بازی فعال نیست.", show_alert=True)
            return

        refresh = getattr(self, "refresh", None)
        if callable(refresh):
            # The existing refresh implementation owns the canonical lobby
            # rendering, so do not duplicate its markup/text here.
            callback.data = f"mgmt:{int(game['id'])}:refresh"
            await refresh(callback)
            return

        # Defensive fallback: retain the old behavior only if the current
        # management implementation has no lobby refresh handler.
        await original_close(self, callback)

    def panel_with_navigation(self: GameManagement, game_id: int):
        kb = original_panel(self, game_id)
        # Keep "بستن" and add an explicit previous-menu action. The latter
        # returns to the management root; submenus already use the same action.
        kb.row(InlineKeyboardButton("⬅️ منوی قبل", callback_data=f"mgmt:{game_id}:open"))
        return kb

    GameManagement.close = close_to_previous_or_lobby
    GameManagement.panel = panel_with_navigation

    async def restore_lobby(message: types.Message):
        gid = int(message.chat.id)
        game = management._game(gid)
        if not game:
            await message.reply("❌ بازی فعالی وجود ندارد.")
            return
        if not await management._allowed(message, gid, game):
            await message.reply("⛔ فقط گرداننده یا مدیر گروه می‌تواند لابی را بازسازی کند.")
            return
        refresh = getattr(management, "refresh", None)
        if not callable(refresh):
            await message.reply("❌ امکان بازسازی لابی در این نسخه فعال نیست.")
            return
        try:
            await refresh(_callback_like(message, int(game["id"])))
        except Exception:
            logging.exception("MANAGEMENT_NAVIGATION: failed to restore lobby")
            await message.reply("❌ بازسازی لابی انجام نشد؛ لاگ سرور را بررسی کنید.")

    # aiogram v2: exact text commands plus /lobby aliases.
    app.dp.register_message_handler(
        restore_lobby,
        lambda message: (message.text or "").strip().lower() in {
            "بازسازی لابی", "بازگردانی لابی", "برگرداندن لابی", "لابی", "/لابی", "/lobby"
        },
        content_types=types.ContentTypes.TEXT,
        state="*",
    )

    logging.info("MANAGEMENT_NAVIGATION installed: close->lobby, text lobby restore enabled")
    return True
