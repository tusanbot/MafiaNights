"""Safe presentation helpers for Telegram keyboards.

This module does not patch aiogram, handlers, dispatchers, or game state.
It only creates individual InlineKeyboardButton objects with Bot API 9.4+
presentation fields when explicitly requested by the caller.
"""
from __future__ import annotations

import os
from aiogram.types import InlineKeyboardButton


def button(
    text: str,
    callback_data: str | None = None,
    *,
    style: str = "primary",
    icon_custom_emoji_id: str | None = None,
    **kwargs,
) -> InlineKeyboardButton:
    """Create one presentation-styled button without changing its behavior.

    callback_data/url/etc. are passed through unchanged. Custom emoji is
    opt-in and only used when a valid Telegram custom-emoji ID is supplied.
    """
    if style not in {"primary", "success", "danger"}:
        style = "primary"
    payload = dict(kwargs)
    if callback_data is not None:
        payload["callback_data"] = callback_data
    payload["style"] = style
    icon = icon_custom_emoji_id or os.getenv("MAFIA_UI_CUSTOM_EMOJI_ID")
    if icon:
        payload["icon_custom_emoji_id"] = icon
    return InlineKeyboardButton(text, **payload)
