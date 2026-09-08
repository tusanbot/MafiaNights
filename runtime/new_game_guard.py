"""Fresh New Game entry-point guard.

Owns the ``new_game`` callback dispatch so every new game starts at scenario
selection instead of rendering/reusing an incomplete legacy lobby.
"""
from __future__ import annotations

import logging
from typing import Any

from aiogram import types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def install(app: Any) -> bool:
    dp, bot = app.dp, app.bot

    async def fresh_new_game(c: types.CallbackQuery):
        group_id = int(c.message.chat.id)
        try:
            admins = await bot.get_chat_administrators(group_id)
            admin_ids = {int(a.user.id) for a in admins}
            if int(c.from_user.id) not in admin_ids:
                await c.answer("⛔ فقط مدیر گروه می‌تواند بازی جدید ایجاد کند.", show_alert=True)
                return

            # Always create a fresh draft. Running/paused games are protected
            # by the durable lobby state layer and are never silently replaced.
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

    table = getattr(dp.callback_query_handlers, "handlers", None)
    if table is None:
        logging.error("FRESH_NEW_GAME_GUARD failed: handler table unavailable")
        return False

    # Remove every previously registered callback whose predicate is the exact
    # new-game action, then install one unambiguous owner at index 0. The
    # callback function has a unique name so later priority passes cannot
    # accidentally select the canonical/legacy ``new_game`` by name.
    kept = []
    removed = 0
    for item in table:
        callback = getattr(item, "callback", None)
        if getattr(callback, "__name__", "") in {"new_game", "fresh_new_game"}:
            removed += 1
            continue
        kept.append(item)
    table[:] = kept

    dp.register_callback_query_handler(fresh_new_game, lambda c: c.data == "new_game")
    # register appends; locate this exact function and move it to the front.
    for idx in range(len(table) - 1, -1, -1):
        callback = getattr(table[idx], "callback", None)
        if callback is fresh_new_game:
            table.insert(0, table.pop(idx))
            break

    logging.info("FRESH_NEW_GAME_GUARD_ACTIVE removed=%d total=%d", removed, len(table))
    return True
