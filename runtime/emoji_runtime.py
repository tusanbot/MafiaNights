"""Central, opt-in Telegram Custom Emoji presentation layer.

Wraps only the current Bot instance. It never patches aiogram classes,
handlers, dispatchers, or game state.
"""
from __future__ import annotations

from typing import Any

from runtime.tag_display import render_custom_emoji_text, custom_emoji_enabled_for_chat


_METHODS = {
    "send_message": {"chat": 0, "text": 1},
    "edit_message_text": {"chat": 1, "text": 0},
    "send_photo": {"chat": 0, "text": 2},
    "send_video": {"chat": 0, "text": 2},
    "send_animation": {"chat": 0, "text": 2},
    "send_document": {"chat": 0, "text": 2},
    "send_audio": {"chat": 0, "text": 2},
    "send_voice": {"chat": 0, "text": 2},
}


def _chat_id(spec: dict[str, int], args: tuple[Any, ...], kwargs: dict[str, Any]) -> int | None:
    try:
        value = kwargs.get("chat_id")
        if value is None and spec["chat"] < len(args):
            value = args[spec["chat"]]
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _transform(spec: dict[str, int], args: tuple[Any, ...], kwargs: dict[str, Any], enabled: bool):
    if not enabled:
        return args, kwargs

    out_args = list(args)
    text_index = spec["text"]
    if text_index < len(out_args) and isinstance(out_args[text_index], str):
        out_args[text_index] = render_custom_emoji_text(out_args[text_index], enabled=True)

    for key in ("text", "caption"):
        if key in kwargs and isinstance(kwargs[key], str):
            kwargs[key] = render_custom_emoji_text(kwargs[key], enabled=True)

    return tuple(out_args), kwargs


def install(app) -> bool:
    bot = getattr(app, "bot", None)
    if bot is None or getattr(bot, "_mafia_custom_emoji_installed", False):
        return False

    for method_name, spec in _METHODS.items():
        original = getattr(bot, method_name, None)
        if original is None:
            continue

        async def wrapped(*args, __original=original, __spec=spec, **kwargs):
            chat_id = _chat_id(__spec, args, kwargs)
            enabled = custom_emoji_enabled_for_chat(app, chat_id)
            args, kwargs = _transform(__spec, args, kwargs, enabled)
            return await __original(*args, **kwargs)

        wrapped._mafia_custom_emoji_wrapper = True
        setattr(bot, method_name, wrapped)

    bot._mafia_custom_emoji_installed = True
    return True
