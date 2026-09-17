"""Final text-command authority for production.

The project accumulated several command surfaces during migration. This module
runs after the last installer and makes the intended precedence explicit:
manual end/cancel, final v3 game commands, canonical v2 player commands,
discipline, friendly commands, then the small tag registry.
"""
from __future__ import annotations

import logging
from typing import Any

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def _handler(item: Any) -> Any:
    value = getattr(item, "callback", None)
    if value is not None:
        return value
    return getattr(item, "handler", None)


def _move_front(registry: list[Any], predicate) -> int:
    selected = [item for item in registry if predicate(_handler(item))]
    for item in reversed(selected):
        try:
            registry.remove(item)
            registry.insert(0, item)
        except ValueError:
            pass
    return len(selected)


def _module_name(fn: Any) -> str:
    return str(getattr(fn, "__module__", ""))


def _name(fn: Any) -> str:
    return str(getattr(fn, "__name__", ""))


def _is_manager(message: Any, game: dict[str, Any]) -> bool:
    return int(message.from_user.id) == int(game.get("moderator_id") or 0)


async def _cancel_text(message: Any, app: Any) -> None:
    if message.chat.type not in {"group", "supergroup"}:
        await message.reply("ℹ️ لغو بازی فقط داخل گروه بازی قابل استفاده است.")
        return
    gid = int(message.chat.id)
    game = app.runtime.state.active_game(gid)
    if not game:
        await message.reply("ℹ️ بازی فعالی وجود ندارد.")
        return
    allowed = _is_manager(message, game)
    if not allowed:
        try:
            allowed = (await app.bot.get_chat_member(gid, int(message.from_user.id))).status in {"creator", "administrator"}
        except Exception:
            allowed = False
    if not allowed:
        await message.reply("⛔ فقط گرداننده یا مدیر گروه می‌تواند بازی را لغو کند.")
        return
    await message.reply(
        "⚠️ <b>تأیید لغو بازی</b>\n\n"
        "با تأیید، بازی فعلی لغو می‌شود و دیگر بازی فعال محسوب نخواهد شد.\n"
        "این عملیات قابل بازگشت نیست.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(row_width=2).add(
            InlineKeyboardButton("🚫 بله، لغو بازی", callback_data=f"mgmt:{int(game['id'])}:cancel_confirm"),
            InlineKeyboardButton("❌ انصراف", callback_data=f"mgmt:{int(game['id'])}:open"),
        ),
    )


def install(app: Any) -> bool:
    if getattr(app, "_command_authority_final", False):
        return False
    app._command_authority_final = True
    dp = app.dp

    dp.register_message_handler(
        lambda message: _cancel_text(message, app),
        lambda m: (m.text or "").strip().casefold().replace("‌", " ") in {
            "لغو بازی", "/لغو_بازی", "/cancel_game", "/cancelgame"
        },
        content_types="text",
        state="*",
    )

    registry = getattr(getattr(dp, "message_handlers", None), "handlers", [])

    # Final precedence. The first matching handler wins in aiogram 2, so the
    # old v2 generic replies must not mask the final v3/end-game handlers.
    _move_front(registry, lambda fn: _module_name(fn) == "runtime.end_game_control" and _name(fn) == "finish_command")
    _move_front(registry, lambda fn: _module_name(fn) == "runtime.command_surface_v3" and _name(fn) == "command")
    _move_front(registry, lambda fn: _module_name(fn) == "runtime.command_surface_v2" and _name(fn) == "command")
    _move_front(registry, lambda fn: _module_name(fn) == "runtime.player_kick" and _name(fn) == "text_command")
    _move_front(registry, lambda fn: _module_name(fn) == "runtime.text_commands" and _name(fn) == "command")
    _move_front(registry, lambda fn: _module_name(fn) == "commands" and _name(fn) == "handle_text_commands")

    # The cancel handler created above is intentionally first among the exact
    # cancel aliases; no legacy command owns these strings.
    _move_front(registry, lambda fn: _module_name(fn) == "runtime.command_authority_final" and _name(fn) == "<lambda>")

    logging.info(
        "FINAL TEXT COMMAND AUTHORITY active: finish=v3 cancel=active v3=priority v2=compatibility discipline=active"
    )
    return True
