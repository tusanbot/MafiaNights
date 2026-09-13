"""Canonical private /start handler.

Private /start must stop dispatcher propagation after rendering the inline menu;
otherwise a later group/lobby start handler can also process the same message.
"""
from __future__ import annotations

from aiogram import types
from aiogram.dispatcher.handler import CancelHandler
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def _private_keyboard():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("🛠 مدیریت بازی", callback_data="manage_game"),
        InlineKeyboardButton("⚙️ مدیریت سناریو", callback_data="final:scenarios"),
        InlineKeyboardButton("➕ امکانات اضافه", callback_data="addons_menu"),
        InlineKeyboardButton("👤 پروفایل", callback_data="up:menu"),
        InlineKeyboardButton("📚 راهنما", callback_data="final:help"),
    )
    return kb


def install(app):
    dp = app.dp
    handlers = getattr(dp.message_handlers, "handlers", [])
    for handler_obj in handlers:
        original = getattr(handler_obj, "handler", None)
        if getattr(original, "__name__", "") != "start_cmd":
            continue

        async def start_with_profile(message: types.Message, _original=original):
            if message.chat.type != "private":
                return await _original(message)
            await message.answer(
                "🎭 <b>Mafia Nights</b>\n\nیک گزینه را انتخاب کنید:",
                reply_markup=_private_keyboard(),
                parse_mode="HTML",
            )
            # Critical: do not allow any group/lobby /start handler to continue.
            raise CancelHandler()

        handler_obj.handler = start_with_profile
        # Make the canonical /start wrapper the first matching handler.
        try:
            handlers.remove(handler_obj)
            handlers.insert(0, handler_obj)
        except ValueError:
            pass
        return start_with_profile

    return None
