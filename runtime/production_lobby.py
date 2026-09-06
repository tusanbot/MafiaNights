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
    removed = _remove_handlers(dp, {
        "new_game", "join", "leave", "choose_scenario", "scenario_selected",
        "set_event_number", "cancel_game",
    })

    app._production_lobby_admin_cache = {}

    def gid(callback: types.CallbackQuery) -> int:
        return int(callback.message.chat.id)

    def capacity(snapshot: dict[str, Any]) -> int:
        game = snapshot.get("game") or {}
        scenario = game.get("scenario_id")
        if isinstance(scenario, int):
            row = scenario_repo.get_by_name(str(scenario))
            return len((row or {}).get("roles") or [])
        return len((app.scenarios.get(scenario) or {}).get("roles") or [])

    def name(row: dict[str, Any]) -> str:
        return str(row.get("nickname") or row.get("first_name") or row.get("username") or row.get("player_id") or "👤")

    def mention(uid: int, label: str | None = None) -> str:
        return f'<a href="tg://user?id={int(uid)}"><b>{html.escape(str(label or uid))}</b></a>'

    def snapshot(group_id: int) -> dict[str, Any]:
        return app.runtime.lobby_snapshot(int(group_id))

    def keyboard(snapshot_data: dict[str, Any]) -> InlineKeyboardMarkup:
        game = snapshot_data.get("game") or {}
        scenario = game.get("scenario_id")
        cap = len((app.scenarios.get(scenario) or {}).get("roles") or [])
        rows = snapshot_data.get("players") or []
        occupied = {
            int(r["seat"]): r for r in rows
            if r.get("seat") is not None and str(r.get("status") or "active") not in {"removed", "dead"}
        }
        kb = InlineKeyboardMarkup(row_width=3)
        for seat in range(1, cap + 1):
            row = occupied.get(seat)
            label = f"{seat:02d} {name(row)[:10]}" if row else f"{seat:02d} ⬜"
            kb.insert(InlineKeyboardButton(label, callback_data=f"prod_seat:{seat}"))
        kb.row(
            InlineKeyboardButton("✅ ورود", callback_data="prod_join"),
            InlineKeyboardButton("❌ خروج", callback_data="prod_leave"),
        )
        if len(occupied) >= cap > 0:
            kb.add(InlineKeyboardButton("🎟 رزرو / لغو رزرو", callback_data="prod_reserve"))
            kb.add(InlineKeyboardButton("🎭 پخش نقش", callback_data="distribute_roles"))
        kb.row(
            InlineKeyboardButton("📝 تغییر سناریو", callback_data="prod_change_scenario"),
            InlineKeyboardButton("🎩 تغییر گرداننده", callback_data="prod_change_moderator"),
        )
        kb.add(InlineKeyboardButton("🚫 لغو بازی", callback_data="prod_cancel"))
        return kb

    def text(snapshot_data: dict[str, Any]) -> str:
        game = snapshot_data.get("game") or {}
        scenario = game.get("scenario_id") or "---"
        scenario_label = scenario
        cap = len((app.scenarios.get(scenario) or {}).get("roles") or [])
        if isinstance(scenario, int):
            row = scenario_repo.get_by_name(str(scenario))
            scenario_label = (row or {}).get("name") or scenario
            cap = len((row or {}).get("roles") or [])
        rows = snapshot_data.get("players") or []
        active = [r for r in rows if r.get("seat") is not None and str(r.get("status") or "active") not in {"removed", "dead"}]
        waiting = [r for r in rows if r.get("seat") is None and str(r.get("status") or "waiting") == "waiting"]
        moderator = game.get("moderator_id")
        lines = [
            "༄",
            "<b>🎭 MAFIA NIGHTS</b>",
            "",
            f"📝 <b>سناریو:</b> {html.escape(str(scenario_label))}",
            f"🎩 <b>گرداننده:</b> {mention(int(moderator)) if moderator else '---'}",
            f"👥 <b>بازیکنان:</b> {len(active)}/{cap}",
            "",
            "◤◢◣◥◤◢◣◥◤◢◣◥",
            "      <b>صندلی‌های بازی</b>",
            "◤◢◣◥◤◢◣◥◤◢◣◥",
            "",
        ]
        if active:
            for row in sorted(active, key=lambda r: int(r.get("seat") or 999)):
                lines.append(f"{int(row['seat']):02d}. {mention(int(row['player_id']), name(row))}")
        else:
            lines.append("— هنوز بازیکنی وارد نشده است.")
        if waiting:
            lines += ["", "🎟 <b>لیست رزرو</b>"]
            for i, row in enumerate(waiting, 1):
                lines.append(f"{i}. {mention(int(row['player_id']), name(row))}")
        lines += ["", "◤◢◣◥◤◢◣◥◤◢◣◥", "༄"]
        return "\n".join(lines)

    async def render(group_id: int, message: types.Message | None = None):
        snap = snapshot(group_id)
        body = text(snap)
        markup = keyboard(snap)
        try:
            message_id = getattr(message, "message_id", None) or getattr(app.ui, "lobby_message_id", None)
            if message_id:
                await bot.edit_message_text(body, group_id, int(message_id), parse_mode="HTML", reply_markup=markup)
                app.ui.lobby_message_id = int(message_id)
            else:
                msg = await bot.send_message(group_id, body, parse_mode="HTML", reply_markup=markup)
                app.ui.lobby_message_id = msg.message_id
        except Exception as exc:
            if "message is not modified" not in str(exc).lower():
                logging.warning("production lobby render failed: %s", exc)
                try:
                    msg = await bot.send_message(group_id, body, parse_mode="HTML", reply_markup=markup)
                    app.ui.lobby_message_id = msg.message_id
                except Exception:
                    logging.exception("production lobby fallback send failed")

    def scenario_keyboard() -> InlineKeyboardMarkup:
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
        if scenario_name not in app.scenarios:
            await callback.answer("سناریو نامعتبر است.", show_alert=True)
            return
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
            try:
                await callback.message.answer("❌ ورود به بازی انجام نشد.")
            except Exception:
                logging.exception("failed to send lobby join error")

    async def leave(callback):
        group_id = gid(callback); uid = int(callback.from_user.id)
        await callback.answer("⏳ خروج...")
        try:
            snap = snapshot(group_id)
            current = next((r for r in snap.get("players", []) if int(r["player_id"]) == uid), None)
            seat = current.get("seat") if current else None
            app.runtime.lobby.leave(group_id, uid)
            if seat is not None:
                app.runtime.lobby.promote_waiting(group_id, int(seat))
            await render(group_id, callback.message)
        except Exception:
            logging.exception("production lobby leave failed")

    async def seat(callback):
        group_id = gid(callback); uid = int(callback.from_user.id)
        target = int(str(callback.data).split(":", 1)[1])
        snap = snapshot(group_id)
        rows = snap.get("players") or []
        current = next((r for r in rows if int(r["player_id"]) == uid), None)
        if not current:
            await callback.answer("ابتدا با دکمه ورود وارد بازی شوید.", show_alert=True)
            return
        occupied = {int(r["seat"]): int(r["player_id"]) for r in rows if r.get("seat") is not None}
        if target in occupied and occupied[target] != uid:
            await callback.answer("❌ این صندلی قبلاً گرفته شده است.", show_alert=True)
            return
        app.runtime.lobby.assign_seat(group_id, uid, target)
        await callback.answer(f"✅ صندلی {target} ثبت شد")
        await render(group_id, callback.message)

    async def reserve(callback):
        group_id = gid(callback); uid = int(callback.from_user.id)
        snap = snapshot(group_id); rows = snap.get("players") or []
        cap = capacity(snap); occupied = [r for r in rows if r.get("seat") is not None]
        current = next((r for r in rows if int(r["player_id"]) == uid), None)
        if len(occupied) < cap:
            await callback.answer("رزرو پس از تکمیل ظرفیت فعال می‌شود.", show_alert=True); return
        if current and current.get("seat") is None:
            app.runtime.lobby.leave(group_id, uid)
            await callback.answer("❌ رزرو لغو شد")
        elif current:
            await callback.answer("شما در لیست اصلی هستید.", show_alert=True); return
        else:
            await app._ensure_player(callback.from_user)
            app.runtime.lobby.join(group_id, uid, None, is_substitute=True)
            await callback.answer("🎟 به لیست رزرو اضافه شدید")
        await render(group_id, callback.message)

    async def change_scenario(callback):
        await show_scenarios(callback, change=True)

    async def change_moderator(callback):
        group_id = gid(callback)
        admins = await bot.get_chat_administrators(group_id)
        kb = InlineKeyboardMarkup(row_width=1)
        for admin in admins:
            kb.add(InlineKeyboardButton(admin.user.full_name, callback_data=f"prod_moderator:{int(admin.user.id)}"))
        await callback.answer()
        await callback.message.edit_text("🎩 <b>تغییر گرداننده</b>\n\nمدیر جدید را انتخاب کنید:", reply_markup=kb, parse_mode="HTML")

    async def cancel_game(callback):
        group_id = gid(callback)
        active = app.runtime.state.active_game(group_id)
        if active:
            app.runtime.state.games.update_game(active["id"], status="finished")
        await callback.answer("🛑 بازی لغو شد")
        try:
            await callback.message.delete()
        except Exception:
            pass

    async def start_game(callback):
        await callback.answer("⏳ شروع بازی...")
        await callback.message.answer("🎲 شروع بازی در حال آماده‌سازی است...")

    def register(filter_fn, fn):
        dp.register_callback_query_handler(fn, filter_fn)

    register(lambda c: c.data == "new_game", new_game)
    register(lambda c: c.data in {"join", "join_game", "prod_join"}, join)
    register(lambda c: c.data in {"leave", "leave_game", "prod_leave"}, leave)
    register(lambda c: c.data in {"choose_scenario"}, choose_scenario)
    register(lambda c: str(c.data).startswith("scenario:"), scenario_selected)
    register(lambda c: str(c.data).startswith("prod_scenario:"), scenario_selected)
    register(lambda c: str(c.data).startswith("prod_moderator:"), moderator_selected)
    register(lambda c: str(c.data).startswith("prod_seat:"), seat)
    register(lambda c: c.data == "prod_reserve", reserve)
    register(lambda c: c.data == "prod_change_scenario", change_scenario)
    register(lambda c: c.data == "prod_change_moderator", change_moderator)
    register(lambda c: c.data in {"cancel_game", "prod_cancel"}, cancel_game)

    app._keyboard_main = lambda: InlineKeyboardMarkup(row_width=1).add(
        InlineKeyboardButton("🎮 بازی جدید", callback_data="new_game"),
        InlineKeyboardButton("📖 راهنما", callback_data="help"),
    )
    logging.info("PRODUCTION_CANONICAL_LOBBY_ACTIVE removed=%s handlers=%d", removed, len(dp.callback_query_handlers.handlers))
    return True
