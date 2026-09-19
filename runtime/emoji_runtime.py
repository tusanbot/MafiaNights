"""Central, opt-in Telegram Custom Emoji presentation layer.

This module wraps only the current Bot instance. It never patches aiogram
classes, handlers, dispatchers, or game state. When the add-on is disabled,
outgoing text/captions are left byte-for-byte unchanged.
"""
from __future__ import annotations

import types
from typing import Any, Callable

from runtime.tag_display import render_custom_emoji_text, custom_emoji_enabled_for_chat


_TEXT_METHODS = {
    "send_message": ("text",),
    "edit_message_text": ("text",),
    "send_photo": ("caption",),
    "send_video": ("caption",),
    "send_animation": ("caption",),
    "send_document": ("caption",),
    "send_audio": ("caption",),
    "send_voice": ("caption",),
}


def _chat_id_from_call(method_name: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> int | None:
    if "chat_id" in kwargs:
        try:
            return int(kwargs["chat_id"])
        except (TypeError, ValueError):
            return None
    if method_name in {"send_message", "send_photo", "send_video", "send_animation",
                       "send_document", "send_audio", "send_voice"} and args:
        try:
            return int(args[0])
        except (TypeError, ValueError):
            return None
    if method_name == "edit_message_text" and len(args) >= 2:
        try:
            return int(args[1])
        except (TypeError, ValueError):
            return None
    return None


def install(app) -> bool:
    bot = getattr(app, "bot", None)
    if bot is None or getattr(bot, "_mafia_custom_emoji_installed", False):
        return False

    for method_name, text_keys in _TEXT_METHODS.items():
        original = getattr(bot, method_name, None)
        if original is None or getattr(original, "_mafia_custom_emoji_wrapper", False):
            continue

        async def wrapped(*args, __original=original, __method_name=method_name, __keys=text_keys, **kwargs):
            chat_id = _chat_id_from_call(__method_name, args, kwargs)
            enabled = custom_emoji_enabled_for_chat(app, chat_id)
            if enabled:
                for key in __keys:
                    if key in kwargs and isinstance(kwargs[key], str):
                        kwargs[key] = render_custom_emoji_text(kwargs[key], enabled=True)
            return await __original(*args, **kwargs)

        wrapped._mafia_custom_emoji_wrapper = True
        setattr(bot, method_name, types.MethodType(wrapped, bot))

    bot._mafia_custom_emoji_installed = True
    return True
