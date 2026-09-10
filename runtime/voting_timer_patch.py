"""Serverless-safe voting transition compatibility layer.

Deadlines are persisted in game state and processed by the external scheduler
(Supabase pg_cron -> /api/telegram/tick). Do not keep webhook invocations alive
waiting for voting deadlines: Telegram/Vercel request lifetimes are not a
reliable timer mechanism.
"""
from __future__ import annotations

from runtime import voting_runtime


def install(main):
    if getattr(main, "_voting_timer_patch_installed", False):
        return False

    # Keep the original transition logic. The persisted deadline is consumed
    # by api/telegram/tick.py, which runs every 10 seconds.
    voting_runtime._start_target = voting_runtime._start_target

    def day_end_keyboard():
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

        return InlineKeyboardMarkup(row_width=1).add(
            InlineKeyboardButton("🗳 رای‌گیری", callback_data="vote:settings"),
            InlineKeyboardButton("🌙 شروع فاز شب", callback_data="start_night"),
            InlineKeyboardButton("🏁 اتمام بازی", callback_data="end_game"),
        )

    voting_runtime._day_end_kb = day_end_keyboard
    main._voting_timer_patch_installed = True
    return True
