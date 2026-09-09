"""Management navigation helpers.

The management implementation owns its callbacks. This module only exposes
text aliases for restoring the lobby; it no longer monkey-patches management
buttons or duplicates the previous-menu row.
"""
from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

from aiogram import types

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
    """Install text aliases for the canonical management refresh action."""
    async def restore_lobby(message: types.Message):
        gid = int(message.chat.id)
        game = management._game(gid)
        if not game:
            await message.reply("❌ بازی فعالی وجود ندارد.")
            return
        if not await management._allowed(message, gid, game):
            await message.reply("⛔ فقط گرداننده یا مدیر گروه می‌تواند لابی را بازسازی کند.")
            return
        try:
            await management.refresh(_callback_like(message, int(game["id"])))
        except Exception:
            logging.exception("MANAGEMENT_NAVIGATION: failed to restore lobby")
            await message.reply("❌ بازسازی لابی انجام نشد؛ لاگ سرور را بررسی کنید.")

    app.dp.register_message_handler(
        restore_lobby,
        lambda message: (message.text or "").strip().lower() in {
            "بازسازی لابی", "بازگردانی لابی", "برگرداندن لابی", "لابی", "/لابی", "/lobby"
        },
        content_types=types.ContentTypes.TEXT,
        state="*",
    )
    logging.info("MANAGEMENT_NAVIGATION installed: text lobby restore enabled")
    return True
