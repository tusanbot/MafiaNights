"""Presentation-only Telegram UI theme for Mafia Nights.

This module changes only the serialized appearance of InlineKeyboardButton
objects. Callback data, handlers, state, database access, and game flow are
left untouched.

It is intentionally compatible with aiogram 2.25.1: TelegramObject accepts
unknown keyword fields and serializes them, which lets us forward Bot API 9.4
button style fields without upgrading aiogram.
"""
from __future__ import annotations

import os
from typing import Any


_INSTALLED = False
_ORIGINAL_INIT: Any = None


def _style_for(text: Any, callback_data: Any) -> str:
    value = f"{text or ''} {callback_data or ''}".casefold()

    # Destructive actions are red.
    danger_tokens = (
        "لغو", "حذف", "اخراج", "kick", "remove", "delete", "cancel",
        "finish", "end_game", "endgame", "reset",
    )
    if any(token in value for token in danger_tokens):
        return "danger"

    # Positive/confirmatory actions are green.
    success_tokens = (
        "ورود", "آماده", "تأیید", "تایید", "ثبت", "پخش نقش", "شروع",
        "join", "ready", "confirm", "distribute", "start",
    )
    if any(token in value for token in success_tokens):
        return "success"

    # Everything else gets Telegram's primary blue treatment.
    return "primary"


def _custom_emoji_id() -> str | None:
    # Optional: the bot owner can provide a verified custom emoji ID without
    # changing code. Never send a guessed/invalid ID by default.
    value = str(os.getenv("MAFIA_UI_CUSTOM_EMOJI_ID") or "").strip()
    return value or None


def install() -> bool:
    """Install the presentation-only button styling once per worker."""
    global _INSTALLED, _ORIGINAL_INIT
    if _INSTALLED:
        return False

    from aiogram.types import InlineKeyboardButton

    _ORIGINAL_INIT = InlineKeyboardButton.__init__

    def themed_init(self, text, url=None, login_url=None, callback_data=None,
                    switch_inline_query=None, switch_inline_query_current_chat=None,
                    callback_game=None, pay=None, web_app=None, **kwargs):
        # Never override an explicitly selected style.
        kwargs.setdefault("style", _style_for(text, callback_data))

        # Custom emoji on buttons is opt-in. This prevents an invalid ID or
        # missing Premium capability from breaking any existing keyboard.
        custom_id = _custom_emoji_id()
        if custom_id:
            kwargs.setdefault("icon_custom_emoji_id", custom_id)

        return _ORIGINAL_INIT(
            self,
            text=text,
            url=url,
            login_url=login_url,
            callback_data=callback_data,
            switch_inline_query=switch_inline_query,
            switch_inline_query_current_chat=switch_inline_query_current_chat,
            callback_game=callback_game,
            pay=pay,
            web_app=web_app,
            **kwargs,
        )

    InlineKeyboardButton.__init__ = themed_init
    _INSTALLED = True
    return True


def custom_emoji(text: str, emoji_id: str | None = None) -> str:
    """Return safe HTML for an optional Telegram custom emoji.

    If no verified ID is supplied, the original Unicode emoji is returned.
    This helper is deliberately opt-in so existing messages cannot break.
    """
    eid = str(emoji_id or _custom_emoji_id() or "").strip()
    if not eid:
        return text
    return f'<tg-emoji emoji-id="{eid}">{text}</tg-emoji>'
