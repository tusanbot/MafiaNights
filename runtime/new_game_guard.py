"""Fresh New Game entry-point guard.

The canonical lobby handler intentionally owns scenario/moderator selection,
but an older lobby draft can otherwise be returned by get_or_create(). This
guard runs first and creates a fresh draft before showing scenario selection.
"""
from __future__ import annotations

import logging
from typing import Any

from aiogram import types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def install(app: Any) -> bool:
    dp, bot = app.dp, app.bot

    async def new_game(c: types.CallbackQuery):
        group_id = int(c.message.chat.id)
        try:
            admins = await bot.get_chat_administrators(group_id)
            admin_ids = {int(a.user.id) for a in admins}
            if int(c.from_user.id) not in admin_ids:
                await c.answer("⛔ فقط مدیر گروه می‌تواند بازی جدید ایجاد کند.", show_alert=True)
                return

            app.runtime.state.lobby.start_new(group_id)
            app.ui.group_chat_id = group_id
            app.ui.lobby_message_id = None

            kb = InlineKeyboardMarkup(row_width=1)
            for name in app.scenarios:
                roles = (app.scenarios.get(name) or {}).get("roles") or []
                kb.add(InlineKeyboardButton(
                    f"📝 {name} ({len(roles)})",
                    callback_data=f"prod_scenario:{name}",
                ))

            await c.answer("🎮 ابتدا سناریو را انتخاب کنید")
            await c.message.edit_text(
                "📝 <b>انتخاب سناریو</b>\n\nسناریوی بازی را انتخاب کنید:",
                reply_markup=kb,
                parse_mode="HTML",
            )
        except RuntimeError as exc:
            await c.answer(str(exc), show_alert=True)
        except Exception:
            logging.exception("fresh new-game guard failed: group=%s", group_id)
            await c.answer("❌ آماده‌سازی بازی انجام نشد.", show_alert=True)

    # Put this handler ahead of every callback so the old canonical new_game
    # callback cannot reuse an existing lobby draft.
    table = getattr(dp.callback_query_handlers, "handlers", None)
    if table is None:
        return False
    dp.register_callback_query_handler(new_game, lambda c: c.data == "new_game")
    for idx, item in enumerate(table):
        callback = getattr(item, "callback", None)
        if getattr(callback, "__name__", "") == "new_game":
            table.insert(0, table.pop(idx))
            break
    logging.info("FRESH_NEW_GAME_GUARD_ACTIVE")
    return True
