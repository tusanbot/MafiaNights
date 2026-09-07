"""Canonical production lobby for the Vercel webhook runtime.

Flow: new game -> scenario -> moderator -> lobby message.
The database game is prepared silently during selection so callbacks survive
serverless invocations; the public lobby message is created only after both
scenario and moderator are selected.
"""
from __future__ import annotations

import html
import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from aiogram import types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from repositories.scenario_repository import ScenarioRepository


def _remove_handlers(dp, names: set[str]) -> list[str]:
    table = getattr(dp.callback_query_handlers, "handlers", [])
    kept, removed = [], []
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
    dp, bot = app.dp, app.bot
    scenario_repo = ScenarioRepository()
    removed = _remove_handlers(dp, {
        "new_game", "join", "leave", "choose_scenario", "scenario_selected",
        "moderator_selected", "seat", "reserve", "change_scenario",
        "change_moderator", "cancel_game", "management", "event_number_menu",
        "event_number_adjust", "refresh_lobby", "back_lobby",
    })
    app._production_lobby_admin_cache = {}

    def gid(c: types.CallbackQuery) -> int:
        return int(c.message.chat.id)

    def game(group_id: int):
        return app.runtime.state.active_game(int(group_id))

    def scenario_info(value: Any) -> dict[str, Any] | None:
        if value is None:
            return None
        if isinstance(value, int):
            return scenario_repo.get_by_id(value)
        return app.scenarios.get(str(value)) or scenario_repo.get_by_name(str(value))

    def scenario_name(value: Any) -> str:
        row = scenario_info(value)
        return str((row or {}).get("name") or value or "---")

    def capacity(data: dict[str, Any]) -> int:
        row = scenario_info((data.get("game") or {}).get("scenario_id"))
        return len((row or {}).get("roles") or [])

    def pname(row: dict[str, Any]) -> str:
        return str(row.get("nickname") or row.get("first_name") or row.get("username") or row.get("player_id") or "👤")

    def mention(uid: int, label: str | None = None) -> str:
        return f'<a href="tg://user?id={int(uid)}"><b>{html.escape(str(label or uid))}</b></a>'

    def snap(group_id: int) -> dict[str, Any]:
        return app.runtime.lobby_snapshot(int(group_id))

    async def refresh_admins(group_id: int) -> set[int]:
        admins = await bot.get_chat_administrators(group_id)
        ids = {int(a.user.id) for a in admins}
        app._production_lobby_admin_cache[int(group_id)] = ids
        return ids

    async def can_manage(c: types.CallbackQuery) -> bool:
        group_id, uid = gid(c), int(c.from_user.id)
        admins = await refresh_admins(group_id)
        moderator = int((game(group_id) or {}).get("moderator_id") or 0)
        if uid not in admins and uid != moderator:
            await c.answer("⛔ فقط گرداننده یا مدیر گروه مجاز است.", show_alert=True)
            return False
        return True

    def keyboard(data: dict[str, Any]) -> InlineKeyboardMarkup:
        cap = capacity(data)
        rows = data.get("players") or []
        occupied = {int(r["seat"]): r for r in rows if r.get("seat") is not None and str(r.get("status") or "active") not in {"removed", "dead"}}
        kb = InlineKeyboardMarkup(row_width=3)
        for seat_no in range(1, cap + 1):
            row = occupied.get(seat_no)
            label = f"{seat_no:02d} {pname(row)[:10]}" if row else f"{seat_no:02d} ⬜"
            kb.insert(InlineKeyboardButton(label, callback_data=f"prod_seat:{seat_no}"))
        kb.row(InlineKeyboardButton("🚪 ورود / خروج", callback_data="prod_toggle_join"))
        if len(occupied) >= cap > 0:
            kb.row(InlineKeyboardButton("🎟 رزرو / لغو رزرو", callback_data="prod_reserve"))
            kb.row(InlineKeyboardButton("🎭 پخش نقش", callback_data="distribute_roles"))
        kb.row(InlineKeyboardButton("⚙️ مدیریت بازی", callback_data="prod_management"))
        kb.row(InlineKeyboardButton("🚫 لغو بازی", callback_data="prod_cancel"))
        return kb

    def lobby_text(data: dict[str, Any]) -> str:
        g = data.get("game") or {}
        rows = data.get("players") or []
        cap = capacity(data)
        active = [r for r in rows if r.get("seat") is not None and str(r.get("status") or "active") not in {"removed", "dead"}]
        waiting = [r for r in rows if r.get("seat") is None and str(r.get("status") or "waiting") == "waiting"]
        moderator = g.get("moderator_id")
        today = datetime.now(ZoneInfo("Asia/Tehran")).strftime("%Y/%m/%d")
        number = g.get("event_number") or "---"
        lines = [
            "༄ <b>لیست بازی</b>", "",
            f"📅 <b>تاریخ:</b> {today}",
            f"🎭 <b>سناریو:</b> {html.escape(scenario_name(g.get('scenario_id')))}",
            f"🔢 <b>شماره بازی:</b> {number}",
            f"🎩 <b>گرداننده:</b> {mention(int(moderator)) if moderator else '---'}", "",
            "━━━━━━━━━━━━━━━━━━",
            f"👥 <b>بازیکنان:</b> {len(active)}/{cap}", "",
            "🪑 <b>لیست صندلی‌ها</b>",
        ]
        for seat_no in range(1, cap + 1):
            row = next((r for r in active if int(r.get("seat") or 0) == seat_no), None)
            lines.append(f"{seat_no:02d}. {mention(int(row['player_id']), pname(row)) if row else '⬜ آزاد'}")
        if waiting:
            lines += ["", "🎟 <b>لیست رزرو</b>"]
            for i, row in enumerate(waiting, 1):
                lines.append(f"{i}. {mention(int(row['player_id']), pname(row))}")
        lines += ["", "━━━━━━━━━━━━━━━━━━", "༄"]
        return "\n".join(lines)

    async def render(group_id: int):
        data = snap(group_id)
        g = data.get("game") or {}
        if not g.get("scenario_id") or not g.get("moderator_id"):
            return
        body, markup = lobby_text(data), keyboard(data)
        message_id = getattr(app.ui, "lobby_message_id", None)
        try:
            if message_id:
                await bot.edit_message_text(body, group_id, int(message_id), parse_mode="HTML", reply_markup=markup)
            else:
                msg = await bot.send_message(group_id, body, parse_mode="HTML", reply_markup=markup)
                app.ui.lobby_message_id = msg.message_id
            app.ui.group_chat_id = group_id
        except Exception as exc:
            if "message is not modified" in str(exc).lower():
                return
            logging.warning("production lobby render failed: %s", exc)
            try:
                msg = await bot.send_message(group_id, body, parse_mode="HTML", reply_markup=markup)
                app.ui.lobby_message_id = msg.message_id
            except Exception:
                logging.exception("production lobby fallback send failed")

    def scenario_keyboard() -> InlineKeyboardMarkup:
        kb = InlineKeyboardMarkup(row_width=1)
        for name in app.scenarios:
            roles = (app.scenarios.get(name) or {}).get("roles") or []
            kb.add(InlineKeyboardButton(f"📝 {name} ({len(roles)})", callback_data=f"prod_scenario:{name}"))
        return kb

    async def show_scenarios(c: types.CallbackQuery, change: bool = False):
        await c.answer()
        title = "📝 <b>تغییر سناریو</b>" if change else "📝 <b>انتخاب سناریو</b>"
        await c.message.edit_text(title + "\n\nسناریوی بازی را انتخاب کنید:", reply_markup=scenario_keyboard(), parse_mode="HTML")

    async def new_game(c: types.CallbackQuery):
        group_id = gid(c)
        await c.answer("🎮 ابتدا سناریو را انتخاب کنید")
        try:
            await refresh_admins(group_id)
            app.runtime.lobby.ensure(group_id)
            app.ui.group_chat_id = group_id
            app.ui.lobby_message_id = None
            await c.message.edit_text("📝 <b>انتخاب سناریو</b>\n\nسناریوی بازی را انتخاب کنید:", reply_markup=scenario_keyboard(), parse_mode="HTML")
        except Exception:
            logging.exception("production new game failed")
            await c.message.answer("❌ آماده‌سازی بازی انجام نشد.")

    async def scenario_selected(c: types.CallbackQuery):
        group_id = gid(c)
        value = str(c.data).split(":", 1)[1]
        row = scenario_repo.get_by_name(value)
        if not row or not row.get("is_active", True):
            await c.answer("سناریو نامعتبر است.", show_alert=True); return
        try:
            if not app.runtime.lobby.set_scenario(group_id, int(row["id"])):
                await c.answer("❌ انتخاب سناریو انجام نشد.", show_alert=True); return
            await c.answer("✅ سناریو انتخاب شد")
            admins = await bot.get_chat_administrators(group_id)
            app._production_lobby_admin_cache[group_id] = {int(a.user.id): a.user.full_name for a in admins}
            kb = InlineKeyboardMarkup(row_width=1)
            for uid, label in app._production_lobby_admin_cache[group_id].items():
                kb.add(InlineKeyboardButton(label, callback_data=f"prod_moderator:{uid}"))
            await c.message.edit_text("🎩 <b>انتخاب گرداننده</b>\n\nیکی از مدیران گروه را انتخاب کنید:", reply_markup=kb, parse_mode="HTML")
        except Exception:
            logging.exception("production scenario selection failed: group=%s scenario=%s", group_id, value)
            await c.answer("❌ انتخاب سناریو انجام نشد.", show_alert=True)

    async def moderator_selected(c: types.CallbackQuery):
        group_id, uid = gid(c), int(str(c.data).split(":", 1)[1])
        if uid not in await refresh_admins(group_id):
            await c.answer("این کاربر دیگر مدیر گروه نیست.", show_alert=True); return
        if not app.runtime.lobby.set_moderator(group_id, uid):
            await c.answer("❌ انتخاب گرداننده انجام نشد.", show_alert=True); return
        await c.answer("✅ گرداننده انتخاب شد")
        await render(group_id)

    async def toggle_join(c: types.CallbackQuery):
        group_id, uid = gid(c), int(c.from_user.id)
        await c.answer("⏳ در حال ثبت...")
        try:
            await app._ensure_player(c.from_user)
            data = snap(group_id); rows = data.get("players") or []
            current = next((r for r in rows if int(r["player_id"]) == uid), None)
            if current:
                seat = current.get("seat")
                app.runtime.lobby.leave(group_id, uid)
                if seat is not None:
                    app.runtime.lobby.promote_waiting(group_id, int(seat))
            else:
                cap = capacity(data)
                occupied = {int(r["seat"]) for r in rows if r.get("seat") is not None}
                seat = next((s for s in range(1, cap + 1) if s not in occupied), None)
                app.runtime.lobby.join(group_id, uid, seat, is_substitute=seat is None)
            await render(group_id)
        except Exception:
            logging.exception("production lobby toggle join failed")
            await c.message.answer("❌ عملیات ورود/خروج انجام نشد.")

    async def seat(c: types.CallbackQuery):
        group_id, uid = gid(c), int(c.from_user.id)
        target = int(str(c.data).split(":", 1)[1])
        data = snap(group_id); rows = data.get("players") or []
        current = next((r for r in rows if int(r["player_id"]) == uid), None)
        if not current:
            await c.answer("ابتدا وارد بازی شوید.", show_alert=True); return
        occupied = {int(r["seat"]): int(r["player_id"]) for r in rows if r.get("seat") is not None}
        if target in occupied and occupied[target] != uid:
            await c.answer("❌ این صندلی قبلاً گرفته شده است.", show_alert=True); return
        if app.runtime.lobby.assign_seat(group_id, uid, target):
            await c.answer(f"✅ صندلی {target} ثبت شد"); await render(group_id)
        else:
            await c.answer("❌ تغییر صندلی انجام نشد.", show_alert=True)

    async def reserve(c: types.CallbackQuery):
        group_id, uid = gid(c), int(c.from_user.id)
        data = snap(group_id); rows = data.get("players") or []
        cap = capacity(data); occupied = [r for r in rows if r.get("seat") is not None]
        current = next((r for r in rows if int(r["player_id"]) == uid), None)
        if len(occupied) < cap:
            await c.answer("رزرو پس از تکمیل ظرفیت فعال می‌شود.", show_alert=True); return
        if current and current.get("seat") is None:
            app.runtime.lobby.leave(group_id, uid); await c.answer("❌ رزرو لغو شد")
        elif current:
            await c.answer("شما در لیست اصلی هستید.", show_alert=True); return
        else:
            await app._ensure_player(c.from_user)
            app.runtime.lobby.join(group_id, uid, None, is_substitute=True); await c.answer("🎟 به لیست رزرو اضافه شدید")
        await render(group_id)

    async def change_scenario(c: types.CallbackQuery):
        if await can_manage(c): await show_scenarios(c, True)

    async def change_moderator(c: types.CallbackQuery):
        if not await can_manage(c): return
        group_id = gid(c); admins = await bot.get_chat_administrators(group_id)
        kb = InlineKeyboardMarkup(row_width=1)
        for a in admins: kb.add(InlineKeyboardButton(a.user.full_name, callback_data=f"prod_moderator:{int(a.user.id)}"))
        await c.answer(); await c.message.edit_text("🎩 <b>تغییر گرداننده</b>\n\nمدیر جدید را انتخاب کنید:", reply_markup=kb, parse_mode="HTML")

    async def management(c: types.CallbackQuery):
        if not await can_manage(c): return
        await c.answer()
        kb = InlineKeyboardMarkup(row_width=1)
        kb.add(InlineKeyboardButton("🔢 تغییر شماره بازی", callback_data="prod_event_number"))
        kb.add(InlineKeyboardButton("📝 تغییر سناریو", callback_data="prod_change_scenario"))
        kb.add(InlineKeyboardButton("🎩 تغییر گرداننده", callback_data="prod_change_moderator"))
        kb.add(InlineKeyboardButton("🔄 بازسازی پیام لابی", callback_data="prod_refresh_lobby"))
        kb.add(InlineKeyboardButton("↩️ بازگشت", callback_data="prod_back_lobby"))
        await c.message.edit_reply_markup(reply_markup=kb)

    async def event_number_menu(c: types.CallbackQuery):
        if not await can_manage(c): return
        current = int((snap(gid(c)).get("game") or {}).get("event_number") or 1)
        kb = InlineKeyboardMarkup(row_width=3)
        kb.row(InlineKeyboardButton("➖ ۱", callback_data="prod_event:-1"), InlineKeyboardButton(str(current), callback_data="noop"), InlineKeyboardButton("➕ ۱", callback_data="prod_event:1"))
        kb.add(InlineKeyboardButton("↩️ بازگشت به مدیریت", callback_data="prod_management"))
        await c.answer(); await c.message.edit_text(f"🔢 <b>شماره بازی</b>\n\nشماره فعلی: <b>{current}</b>\nبا دکمه‌ها تغییر دهید.", parse_mode="HTML", reply_markup=kb)

    async def event_number_adjust(c: types.CallbackQuery):
        if not await can_manage(c): return
        data = snap(gid(c)); current = int((data.get("game") or {}).get("event_number") or 1)
        new_number = max(1, current + int(str(c.data).split(":", 1)[1]))
        if app.runtime.lobby.set_event_number(gid(c), new_number):
            await c.answer(f"✅ شماره بازی: {new_number}"); await event_number_menu(c)
        else:
            await c.answer("❌ تغییر شماره انجام نشد.", show_alert=True)

    async def refresh_lobby(c: types.CallbackQuery):
        if await can_manage(c): await c.answer("🔄 به‌روزرسانی شد"); await render(gid(c))

    async def back_lobby(c: types.CallbackQuery):
        await c.answer(); await render(gid(c))

    async def cancel_game(c: types.CallbackQuery):
        if not await can_manage(c): return
        active = game(gid(c))
        if active: app.runtime.state.games.update_game(active["id"], status="finished")
        await c.answer("🛑 بازی لغو شد")
        try: await c.message.delete()
        except Exception: pass
        app.ui.lobby_message_id = None

    def register(predicate, fn):
        dp.register_callback_query_handler(fn, predicate)

    register(lambda c: c.data == "new_game", new_game)
    register(lambda c: c.data in {"join", "join_game", "prod_join", "leave", "leave_game", "prod_leave", "prod_toggle_join"}, toggle_join)
    register(lambda c: c.data == "choose_scenario", lambda c: show_scenarios(c))
    register(lambda c: str(c.data).startswith("scenario:") or str(c.data).startswith("prod_scenario:"), scenario_selected)
    register(lambda c: str(c.data).startswith("prod_moderator:"), moderator_selected)
    register(lambda c: str(c.data).startswith("prod_seat:"), seat)
    register(lambda c: c.data == "prod_reserve", reserve)
    register(lambda c: c.data == "prod_change_scenario", change_scenario)
    register(lambda c: c.data == "prod_change_moderator", change_moderator)
    register(lambda c: c.data == "prod_management", management)
    register(lambda c: c.data == "prod_event_number", event_number_menu)
    register(lambda c: str(c.data).startswith("prod_event:"), event_number_adjust)
    register(lambda c: c.data == "prod_refresh_lobby", refresh_lobby)
    register(lambda c: c.data == "prod_back_lobby", back_lobby)
    register(lambda c: c.data in {"cancel_game", "prod_cancel"}, cancel_game)

    app._keyboard_main = lambda: InlineKeyboardMarkup(row_width=1).add(
        InlineKeyboardButton("🎮 بازی جدید", callback_data="new_game"),
        InlineKeyboardButton("📖 راهنما", callback_data="help"),
    )
    logging.info("PRODUCTION_CANONICAL_LOBBY_ACTIVE removed=%s handlers=%d", removed, len(dp.callback_query_handlers.handlers))
    return True
