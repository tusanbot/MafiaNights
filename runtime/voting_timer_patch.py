"""Serverless-safe voting transition compatibility layer.

Voting deadlines are persisted in game state and processed by the external
scheduler (Supabase pg_cron -> /api/telegram/tick). Webhook requests must not
sleep while waiting for a deadline.
"""
from __future__ import annotations

import html
import time

from runtime import voting_runtime


async def _durable_start_wait(main):
    v = voting_runtime._v(main)
    deadline = time.time() + int(v["wait_seconds"])
    v.update(
        phase="waiting",
        started_at=time.time(),
        deadline=deadline,
        target_index=0,
        votes={},
    )
    voting_runtime._put(main, v)

    blocked = voting_runtime._active_rights(v)
    names = [
        voting_runtime._row_name(main, row)
        for row in voting_runtime._players(main)
        if int(row["player_id"]) in blocked
    ]
    blocked_text = "\n".join(
        f"• {html.escape(name)}" for name in names
    ) if names else "• هیچ‌کس"

    await main.bot.send_message(
        voting_runtime._gid(main),
        f"🗳 <b>رای‌گیری پس از {int(v['wait_seconds'])} ثانیه شروع می‌شود.</b>\n"
        f"برای رای به هر بازیکن {int(v['vote_seconds'])} ثانیه فرصت دارید.\n\n"
        f"🚫 <b>بازیکنانی که حق رای ندارند:</b>\n{blocked_text}",
        parse_mode="HTML",
    )
    main._voting_task = None


def install(main):
    if getattr(main, "_voting_timer_patch_installed", False):
        return False

    # Persist the waiting deadline and return immediately. The scheduler will
    # call _start_target once the deadline has passed.
    voting_runtime._start_wait = _durable_start_wait

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
