"""Patch the legacy /start private menu to expose the user dashboard."""
from __future__ import annotations

from aiogram import types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def install(app):
    dp = app.dp

    for handler_obj in getattr(dp.message_handlers, "handlers", []):
        original = getattr(handler_obj, "handler", None)
        if getattr(original, "__name__", "") != "start_cmd":
            continue

        async def start_with_profile(message: types.Message, _original=original):
            if message.chat.type != "private":
                return await _original(message)

            kb = InlineKeyboardMarkup(row_width=1)
            kb.add(InlineKeyboardButton("🛠 مدیریت بازی", callback_data="manage_game"))
            kb.add(InlineKeyboardButton("⚙ مدیریت سناریو", callback_data="manage_scenarios"))
            kb.add(InlineKeyboardButton("⚙ امکانات اضافه", callback_data="addons_menu"))

            if message.from_user.id == getattr(app, "moderator_id", None):
                kb.add(InlineKeyboardButton("🛠 مدیریت بازی", callback_data="manage_game"))
                kb.add(InlineKeyboardButton("⚙ مدیریت سناریو", callback_data="manage_scenarios"))
                kb.add(InlineKeyboardButton("⚙ امکانات اضافه", callback_data="addons_menu"))

            # Use the user-panel's existing menu callback. The previous
            # up:profile callback could be intercepted by a legacy profile
            # handler in some runtime combinations.
            kb.add(InlineKeyboardButton("👤 پروفایل", callback_data="up:menu"))
            kb.add(InlineKeyboardButton("📚 راهنما", callback_data="help"))
            await message.reply("📋 منوی ربات:", reply_markup=kb)

        handler_obj.handler = start_with_profile
        return start_with_profile

    return None
