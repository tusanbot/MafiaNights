"""Canonical callbacks for the private panel menu.

The text command in commands.py owns rendering of the PV menu. This module
owns only the callbacks emitted by that menu so they cannot be swallowed by
older generic callback handlers.
"""
from __future__ import annotations

import html
import logging
from typing import Any

from aiogram import types
from aiogram.dispatcher.handler import CancelHandler
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def _private(callback: types.CallbackQuery) -> bool:
    return bool(callback.message and getattr(callback.message.chat, "type", None) == "private")


def _pv_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(row_width=2).add(
        InlineKeyboardButton("🎭 نقش من", callback_data="pv:role"),
        InlineKeyboardButton("📊 آمار", callback_data="pv:stats"),
        InlineKeyboardButton("📚 دستورات", callback_data="pv:commands"),
        InlineKeyboardButton("🤖 پنل دستیار", callback_data="aip:menu"),
    )


async def _show_pv(callback: types.CallbackQuery) -> None:
    await callback.message.edit_text(
        "👤 <b>پنل پیوی Mafia Nights</b>\n\nیکی از گزینه‌ها را انتخاب کنید:",
        parse_mode="HTML",
        reply_markup=_pv_keyboard(),
    )


async def _role(callback: types.CallbackQuery, app: Any) -> None:
    gid = int(getattr(app, "ALLOWED_GROUP_ID", 0) or 0)
    game = app.runtime.state.active_game(gid) if gid else None
    if not game:
        await callback.message.edit_text(
            "ℹ️ در حال حاضر بازی فعالی پیدا نشد.",
            reply_markup=InlineKeyboardMarkup().add(
                InlineKeyboardButton("⬅️ پنل پیوی", callback_data="pv:back")
            ),
        )
        return

    rows = app.runtime.state.games.list_players(game["id"])
    uid = int(callback.from_user.id)
    row = next((r for r in rows if int(r.get("player_id") or 0) == uid), None)
    if not row or not row.get("role"):
        await callback.message.edit_text(
            "ℹ️ هنوز نقشی برای شما در بازی فعال ثبت نشده است.",
            reply_markup=InlineKeyboardMarkup().add(
                InlineKeyboardButton("⬅️ پنل پیوی", callback_data="pv:back")
            ),
        )
        return

    seat = row.get("seat")
    seat_text = f"{int(seat):02d}" if seat is not None else "—"
    await callback.message.edit_text(
        "🎭 <b>نقش شما</b>\n\n"
        f"💺 صندلی: <b>{seat_text}</b>\n"
        f"🎭 نقش: <b>{html.escape(str(row.get('role')))}</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup().add(
            InlineKeyboardButton("⬅️ پنل پیوی", callback_data="pv:back")
        ),
    )


async def _stats(callback: types.CallbackQuery, app: Any) -> None:
    stats = getattr(app, "_user_stats_instance", None)
    if stats is None:
        await callback.message.edit_text(
            "⚠️ بخش آمار در دسترس نیست.",
            reply_markup=InlineKeyboardMarkup().add(
                InlineKeyboardButton("⬅️ پنل پیوی", callback_data="pv:back")
            ),
        )
        return
    await stats.show_stats(callback.message, int(callback.from_user.id), None, edit=True)


async def _commands(callback: types.CallbackQuery) -> None:
    from commands import COMMAND_REFERENCE

    lines = ["📖 <b>دستورات متنی Mafia Nights</b>", ""]
    for title, commands in COMMAND_REFERENCE:
        lines.append(f"<b>{html.escape(title)}</b>")
        lines.extend(
            f"<code>{html.escape(command)}</code> — {html.escape(label)}"
            for command, label in commands
        )
        lines.append("")

    await callback.message.edit_text(
        "\n".join(lines).rstrip(),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup().add(
            InlineKeyboardButton("⬅️ پنل پیوی", callback_data="pv:back")
        ),
    )


async def install(app: Any) -> bool:
    if getattr(app, "_canonical_pv_menu_callbacks_installed", False):
        return False

    dp = app.dp

    async def dispatch(callback: types.CallbackQuery):
        if not _private(callback):
            raise CancelHandler()

        data = str(callback.data or "")
        try:
            if data == "pv:role":
                await _role(callback, app)
            elif data == "pv:stats":
                await _stats(callback, app)
            elif data == "pv:commands":
                await _commands(callback)
            elif data == "pv:back":
                await _show_pv(callback)
            elif data == "aip:menu":
                panel = getattr(app, "assistant_admin_panel", None)
                if panel is None:
                    await callback.answer("⚠️ پنل دستیار در دسترس نیست.", show_alert=True)
                else:
                    await panel.menu(callback)
                    return
            else:
                return
            await callback.answer()
        except CancelHandler:
            raise
        except Exception:
            logging.exception("private panel callback failed: %s", data)
            await callback.answer("❌ اجرای این گزینه انجام نشد.", show_alert=True)
        raise CancelHandler()

    dp.register_callback_query_handler(
        dispatch,
        lambda c: str(c.data or "") in {"pv:role", "pv:stats", "pv:commands", "pv:back", "aip:menu"},
        state="*",
    )

    handlers = getattr(dp.callback_query_handlers, "handlers", [])
    mine = []
    rest = []
    for item in list(handlers):
        fn = getattr(item, "handler", None) or getattr(item, "callback", None)
        if fn is dispatch:
            mine.append(item)
        else:
            rest.append(item)
    handlers[:] = mine + rest

    app._canonical_pv_menu_callbacks_installed = True
    logging.info("CANONICAL PV MENU CALLBACKS ACTIVE")
    return True
