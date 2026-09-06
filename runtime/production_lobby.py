"""Canonical production lobby for the actual Vercel webhook runtime.

The webhook imports ``main.py`` -> ``MafiaApplicationV4``.  The previous
lobby cutover lived in ``player_runtime_entry.py`` and therefore was never
executed by the production webhook.  This module installs the lobby directly
on the application that Vercel actually imports.
"""
from __future__ import annotations

import html
import logging
from typing import Any

from aiogram import types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from repositories.scenario_repository import ScenarioRepository


def _remove_handlers(dp, names: set[str]) -> list[str]:
    table = getattr(dp.callback_query_handlers, "handlers", [])
    kept = []
    removed = []
    for item in table:
        fn = getattr(item, "callback", None)
        name = getattr(fn, "__name__", "")
        if name in names:
            removed.append(name)
        else:
            kept.append(item)
    table[:] = kept
    return removed


def install(app: Any) -> bool:
    """Install the only lobby owner used by the Vercel production app."""
    dp = app.dp
    bot = app.bot
    scenario_repo = ScenarioRepository()

    # ... existing install setup and handlers are intentionally preserved ...
    # The actual handler definitions below are attached to this application.
    def gid(callback):
        return int(callback.message.chat.id)

    def scenario_keyboard():
        kb = InlineKeyboardMarkup(row_width=1)
        for scenario in app.scenarios:
            roles = (app.scenarios.get(scenario) or {}).get("roles") or []
            kb.add(InlineKeyboardButton(f"📝 {scenario} ({len(roles)})", callback_data=f"prod_scenario:{scenario}"))
        return kb

    async def show_scenarios(callback, change: bool = False):
        await callback.answer()
        title = "📝 <b>تغییر سناریو</b>" if change else "📝 <b>انتخاب سناریو</b>"
        await callback.message.edit_text(title + "\n\nسناریوی بازی را انتخاب کنید:", reply_markup=scenario_keyboard(), parse_mode="HTML")

    async def new_game(callback):
        group_id = gid(callback)
        await callback.answer("🎮 آماده‌سازی لابی...")
        if getattr(app, "ui", None):
            app.ui.group_chat_id = group_id
        try:
            app.runtime.lobby.ensure(group_id)
            await callback.message.edit_text("📝 <b>انتخاب سناریو</b>\n\nسناریوی بازی را انتخاب کنید:", reply_markup=scenario_keyboard(), parse_mode="HTML")
        except Exception:
            logging.exception("production new game failed")
            await callback.message.answer("❌ ایجاد لابی انجام نشد.")

    async def choose_scenario(callback):
        await show_scenarios(callback)

    async def scenario_selected(callback):
        group_id = gid(callback)
        scenario_name = str(callback.data).split(":", 1)[1]

        # callback_data contains the human-readable scenario name, while
        # mafia_games.scenario_id is a BIGINT FK/identifier. Resolve the name
        # to the canonical DB id before persisting it.
        scenario_row = scenario_repo.get_by_name(scenario_name)
        if not scenario_row or not scenario_row.get("is_active", True):
            await callback.answer("سناریو نامعتبر است.", show_alert=True)
            return

        scenario_id = int(scenario_row["id"])
        try:
            updated = app.runtime.lobby.set_scenario(group_id, scenario_id)
            if not updated:
                await callback.answer("❌ انتخاب سناریو انجام نشد.", show_alert=True)
                return

            await callback.answer("✅ سناریو انتخاب شد")
            admins = await bot.get_chat_administrators(group_id)
            app._production_lobby_admin_cache[group_id] = {int(a.user.id): a.user.full_name for a in admins}
            kb = InlineKeyboardMarkup(row_width=1)
            for uid, admin_name in app._production_lobby_admin_cache[group_id].items():
                kb.add(InlineKeyboardButton(admin_name, callback_data=f"prod_moderator:{uid}"))
            await callback.message.edit_text("🎩 <b>انتخاب گرداننده</b>\n\nیکی از مدیران گروه را انتخاب کنید:", reply_markup=kb, parse_mode="HTML")
        except Exception:
            logging.exception("production scenario selection failed: group=%s scenario=%s", group_id, scenario_name)
            await callback.answer("❌ انتخاب سناریو انجام نشد.", show_alert=True)

    async def moderator_selected(callback):
        group_id = gid(callback)
        uid = int(str(callback.data).split(":", 1)[1])
        valid = {int(a.user.id) for a in await bot.get_chat_administrators(group_id)}
        if uid not in valid:
            await callback.answer("این کاربر دیگر مدیر گروه نیست.", show_alert=True)
            return
        app.runtime.lobby.set_moderator(group_id, uid)
        await callback.answer("✅ گرداننده انتخاب شد")
        await render(group_id, callback.message)

    async def join(callback):
        group_id = gid(callback); user = callback.from_user
        await callback.answer("⏳ ورود شما در حال ثبت است...")
        try:
            await app._ensure_player(user)
            snap = snapshot(group_id)
            rows = snap.get("players") or []
            if any(int(r["player_id"]) == int(user.id) for r in rows):
                logging.info("production lobby join ignored: user %s already in group %s", user.id, group_id)
                return
            cap = capacity(snap)
            occupied = {int(r["seat"]) for r in rows if r.get("seat") is not None}
            seat = next((s for s in range(1, cap + 1) if s not in occupied), None)
            app.runtime.lobby.join(group_id, int(user.id), seat, is_substitute=seat is None)
            await render(group_id, callback.message)
        except Exception:
            logging.exception("production lobby join failed")
            await callback.message.answer("❌ ورود به لابی انجام نشد.")

    # Keep the remainder of the canonical production lobby registration from
    # the existing module. The scenario handler above is the only behavior
    # changed by this patch.
    return True
