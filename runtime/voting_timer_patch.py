"""Serverless-safe completion timer for the persistent voting runtime.

The voting runtime persists each deadline, but its original target transition
only sent the target message and never waited for the target deadline. This
small compatibility layer keeps the existing voting state machine intact and
awaits one target at a time inside the active Vercel invocation.
"""
from __future__ import annotations

import asyncio
import time

from runtime import voting_runtime


def install(main):
    if getattr(main, "_voting_timer_patch_installed", False):
        return False

    original_start_target = voting_runtime._start_target

    async def start_target_with_timer(app):
        await original_start_target(app)
        voting = voting_runtime._v(app)
        if voting.get("phase") != "voting":
            return
        deadline = voting.get("deadline")
        if deadline is None:
            return

        await asyncio.sleep(max(0.0, float(deadline) - time.time()))

        current = voting_runtime._v(app)
        if (
            current.get("phase") == "voting"
            and current.get("deadline") == deadline
        ):
            await voting_runtime._end_target(app)

    voting_runtime._start_target = start_target_with_timer

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
