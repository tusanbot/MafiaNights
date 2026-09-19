"""Production Telegram command menu and slash-command adapters.

Only registers commands that have deterministic handlers in the current
production runtime. This is presentation/entry-point configuration and does
not modify game state.
"""
from __future__ import annotations

import logging
from aiogram import types
from aiogram.dispatcher.handler import CancelHandler


GROUP_COMMANDS = [
    types.BotCommand("start", "نمایش منوی اصلی"),
    types.BotCommand("newgame", "ایجاد بازی جدید (مدیر گروه)"),
    types.BotCommand("stats", "نمایش آمار بازی"),
    types.BotCommand("sub", "افزودن بازیکن جایگزین"),
    types.BotCommand("tagall", "تگ بازیکنان"),
    types.BotCommand("tagadmins", "تگ مدیران گروه"),
]

PRIVATE_COMMANDS = [
    types.BotCommand("start", "نمایش منوی اصلی"),
    types.BotCommand("stats", "نمایش آمار بازی"),
]


def install(app):
    if getattr(app, "_telegram_commands_installed", False):
        return False

    dp = app.dp

    async def new_game(message: types.Message):
        if message.chat.type not in {"group", "supergroup"}:
            await message.reply("⚠️ این دستور فقط داخل گروه قابل استفاده است.")
            raise CancelHandler()
        handler = getattr(app, "_canonical_new_game_handler", None)
        if handler is None:
            await message.reply("⚠️ مسیر ایجاد بازی در دسترس نیست.")
            raise CancelHandler()
        from types import SimpleNamespace
        callback = SimpleNamespace(
            message=message,
            from_user=message.from_user,
            data="fl_new",
            answer=message.answer,
            _from_text_command=True,
        )
        await handler(callback)
        raise CancelHandler()

    dp.register_message_handler(
        new_game,
        commands=["newgame"],
        state="*",
        content_types=[types.ContentTypes.TEXT],
    )

    async def tagall(message: types.Message):
        from commands import cmd_tag_all
        await cmd_tag_all(message, app)
        raise CancelHandler()

    async def tagadmins(message: types.Message):
        from commands import cmd_tag_admins
        await cmd_tag_admins(message, app)
        raise CancelHandler()

    dp.register_message_handler(tagall, commands=["tagall"], state="*")
    dp.register_message_handler(tagadmins, commands=["tagadmins"], state="*")

    async def register_remote_commands():
        try:
            # A chat-specific scope guarantees that Telegram shows the commands
            # when the user types "/" in the configured Mafia group.
            await app.bot.set_my_commands(
                GROUP_COMMANDS,
                scope=types.BotCommandScopeChat(chat_id=int(app.ALLOWED_GROUP_ID)),
            )
            await app.bot.set_my_commands(PRIVATE_COMMANDS)
            logging.info(
                "TELEGRAM COMMAND MENU installed group=%s commands=%s",
                app.ALLOWED_GROUP_ID,
                [c.command for c in GROUP_COMMANDS],
            )
        except Exception:
            logging.exception("TELEGRAM COMMAND MENU installation failed")

    app._telegram_commands_installed = True
    app._register_telegram_commands = register_remote_commands
    logging.info("TELEGRAM COMMAND SURFACE installed")
    return True
