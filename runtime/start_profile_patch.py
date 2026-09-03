"""Patch the legacy /start private menu to expose the user profile.

The legacy start handler builds its own keyboard instead of using
main_panel_keyboard(), so the unified user panel cannot add its button there.
This small runtime patch replaces only the private branch of start_cmd and
leaves the group start behavior untouched.
"""
from __future__ import annotations

from aiogram import types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def install(app):
    dp = app.dp

    # Find the legacy /start handler by function name and replace its handler
    # in-place. This keeps its original registration order and avoids adding a
    # competing /start handler behind the legacy one.
    for handler_obj in getattr(dp.message_handlers, "handlers", []):
        original = getattr(handler_obj, "handler", None)
        if getattr(original, "__name__", "") != "start_cmd":
            continue

        async def start_with_profile(message: types.Message, _original=original):
            if message.chat.type != "private":
                # Preserve the existing group behavior exactly.
                return await _original(message)

            kb = InlineKeyboardMarkup(row_width=1)
            kb.add(InlineKeyboardButton("🛠 مدیریت بازی", callback_data="manage_game"))
            kb.add(InlineKeyboardButton("⚙ مدیریت سناریو", callback_data="manage_scenarios"))
            kb.add(InlineKeyboardButton("⚙ امکانات اضافه", callback_data="addons_menu"))

            # Preserve the legacy moderator-only duplication/behavior.
            if message.from_user.id == getattr(app, "moderator_id", None):
                kb.add(InlineKeyboardButton("🛠 مدیریت بازی", callback_data="manage_game"))
                kb.add(InlineKeyboardButton("⚙ مدیریت سناریو", callback_data="manage_scenarios"))
                kb.add(InlineKeyboardButton("⚙ امکانات اضافه", callback_data="addons_menu"))

            # New personal dashboard entry. It is intentionally independent
            # from game-management permissions.
            kb.add(InlineKeyboardButton("👤 پروفایل", callback_data="up:profile"))
            kb.add(InlineKeyboardButton("📚 راهنما", callback_data="help"))

            await message.reply("📋 منوی ربات:", reply_markup=kb)

        handler_obj.handler = start_with_profile
        return start_with_profile

    return None
