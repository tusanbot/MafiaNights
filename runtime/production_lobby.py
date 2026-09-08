"""Canonical production lobby.

There is exactly one Telegram Lobby owner. The lobby is a small state machine:
new game -> scenario -> moderator -> public lobby -> gameplay.

All mutating callbacks carry the durable game id. This makes old Telegram
buttons harmless after a new game is created in the same group.
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


LEGACY_HANDLER_NAMES = {
    "new_game", "join", "leave", "choose_scenario", "scenario_selected",
    "moderator_selected", "slot", "seat", "reserve", "change_scenario",
    "change_moderator", "cancel_game", "management", "event_number_menu",
    "event_number_adjust", "refresh_lobby", "back_lobby", "legacy_join",
    "legacy_leave", "waiting_join", "waiting_leave", "toggle_join",
}


def _remove_legacy_handlers(dp) -> int:
    """Remove known legacy Lobby callbacks before installing the sole owner."""
    table = getattr(dp.callback_query_handlers, "handlers", [])
    kept = []
    removed = 0
    for item in table:
        fn = getattr(item, "callback", None)
        name = getattr(fn, "__name__", "")
        if name in LEGACY_HANDLER_NAMES:
            removed += 1
        else:
            kept.append(item)
    table[:] = kept
    return removed


def install(app: Any) -> bool:
    dp, bot = app.dp, app.bot
    scenario_repo = ScenarioRepository()
    removed = _remove_legacy_handlers(dp)
    logging.info("CANONICAL_LOBBY_INSTALL removed_legacy_handlers=%d", removed)

    # TelegramRuntime is retained for gameplay compatibility. Lobby message
    # identity is durable and per-game instead of being stored globally in it.
    if not hasattr(app, "_lobby_render_locks"):
        app._lobby_render_locks = {}

    def group_id(callback: types.CallbackQuery) -> int:
        return int(callback.message.chat.id)

    def current_game(gid: int) -> dict[str, Any] | None:
        return app.runtime.state.active_game(int(gid))

    def snapshot(gid: int) -> dict[str, Any]:
        return app.runtime.lobby_snapshot(int(gid))

    def scenario_info(scenario_id: Any) -> dict[str, Any] | None:
        if scenario_id is None:
            return None
        try:
            return scenario_repo.get_by_id(int(scenario_id))
        except (TypeError, ValueError):
            return scenario_repo.get_by_name(str(scenario_id))

    def scenario_name(scenario_id: Any) -> str:
        row = scenario_info(scenario_id)
        return str((row or {}).get("name") or scenario_id or "---")

    def capacity(game: dict[str, Any]) -> int:
        row = scenario_info(game.get("scenario_id"))
        roles = (row or {}).get("roles") or []
        return len(roles)

    def player_name(row: dict[str, Any]) -> str:
        return str(row.get("nickname") or row.get("first_name") or row.get("username") or row.get("player_id") or "👤")

    def mention(uid: int, label: str | None = None) -> str:
        return f'<a href="tg://user?id={int(uid)}"><b>{html.escape(str(label or uid))}</b></a>'

    async def is_manager(callback: types.CallbackQuery, game: dict[str, Any] | None = None) -> bool:
        gid = group_id(callback)
        uid = int(callback.from_user.id)
        game = game or current_game(gid)
        moderator = int((game or {}).get("moderator_id") or 0)
        if uid == moderator:
            return True
        try:
            member = await bot.get_chat_member(gid, uid)
            return member.status in {"creator", "administrator"}
        except Exception:
            return False

    def require_game(callback: types.CallbackQuery, expected_id: int | None = None, *, lobby_only: bool = True):
        gid = group_id(callback)
        game = current_game(gid)
        if not game:
            return None, "❌ بازی فعالی وجود ندارد."
        if expected_id is not None and int(game.get("id")) != int(expected_id):
            return None, "⚠️ این دکمه مربوط به بازی قبلی است."
        if lobby_only and str(game.get("status") or "") != "lobby":
            return None, "❌ لابی فعال نیست."
        return game, None

    def parse_callback(callback: types.CallbackQuery, prefix: str, parts: int) -> list[str] | None:
        data = str(callback.data or "")
        values = data.split(":")
        if len(values) != parts or values[0] != prefix:
            return None
        return values

    def lobby_state(game: dict[str, Any]) -> dict[str, Any]:
        return dict(game.get("state") or {})

    def save_lobby_state(game: dict[str, Any], **changes: Any) -> bool:
        state = lobby_state(game)
        state.update(changes)
        return bool(app.runtime.state.games.update_game(game["id"], state=state))

    def scenario_keyboard(game_id: int) -> InlineKeyboardMarkup:
        kb = InlineKeyboardMarkup(row_width=1)
        for row in scenario_repo.list_active():
            sid = int(row["id"])
            name = str(row.get("name") or sid)
            roles = row.get("roles") or []
            kb.add(InlineKeyboardButton(f"📝 {name} ({len(roles)})", callback_data=f"lobby:{game_id}:scenario:{sid}"))
        return kb

    async def render(gid: int, game: dict[str, Any] | None = None) -> bool:
        game = game or current_game(gid)
        if not game or str(game.get("status") or "") != "lobby":
            return False
        if not game.get("scenario_id") or not game.get("moderator_id"):
            return False

        data = snapshot(gid)
        game = data.get("game") or game
        cap = capacity(game)
        rows = data.get("players") or []
        active = [
            r for r in rows
            if r.get("seat") is not None and str(r.get("status") or "active") not in {"removed", "dead"}
        ]
        waiting = [
            r for r in rows
            if r.get("seat") is None and str(r.get("status") or "waiting") == "waiting"
        ]
        active.sort(key=lambda r: int(r.get("seat") or 999))
        occupied = {int(r["seat"]): r for r in active}

        lines = [
            "༄ <b>لیست بازی Mafia Nights</b>", "",
            f"📅 <b>تاریخ:</b> {datetime.now(ZoneInfo('Asia/Tehran')).strftime('%Y/%m/%d')}",
            f"🎭 <b>سناریو:</b> {html.escape(scenario_name(game.get('scenario_id')))}",
            f"🔢 <b>شماره بازی:</b> {int(game.get('event_number') or 1)}",
            f"🎩 <b>گرداننده:</b> {mention(int(game['moderator_id']))}",
            "",
            "━━━━━━━━━━━━━━━━━━",
            f"👥 <b>بازیکنان:</b> {len(active)}/{cap}",
            "",
            "🪑 <b>لیست صندلی‌ها</b>",
        ]
        for seat_no in range(1, cap + 1):
            row = occupied.get(seat_no)
            lines.append(f"{seat_no:02d}. {mention(int(row['player_id']), player_name(row)) if row else '⬜ آزاد'}")
        if waiting:
            lines.extend(["", "🎟 <b>لیست رزرو</b>"])
            for idx, row in enumerate(waiting, 1):
                lines.append(f"{idx}. {mention(int(row['player_id']), player_name(row))}")
        lines.extend(["", "━━━━━━━━━━━━━━━━━━", "༄"])

        kb = InlineKeyboardMarkup(row_width=3)
        for seat_no in range(1, cap + 1):
            row = occupied.get(seat_no)
            label = f"{seat_no:02d} {player_name(row)[:10]}" if row else f"{seat_no:02d} ⬜"
            kb.insert(InlineKeyboardButton(label, callback_data=f"lobby:{int(game['id'])}:seat:{seat_no}"))
        kb.row(InlineKeyboardButton("🚪 ورود / خروج", callback_data=f"lobby:{int(game['id'])}:toggle"))
        if len(active) >= cap > 0:
            kb.row(InlineKeyboardButton("🎟 رزرو / لغو رزرو", callback_data=f"lobby:{int(game['id'])}:reserve"))
            kb.row(InlineKeyboardButton("🎭 پخش نقش", callback_data=f"lobby:{int(game['id'])}:distribute"))
        kb.row(InlineKeyboardButton("⚙️ مدیریت بازی", callback_data=f"lobby:{int(game['id'])}:management"))
        kb.row(InlineKeyboardButton("🚫 لغو بازی", callback_data=f"lobby:{int(game['id'])}:cancel"))

        state = lobby_state(game)
        message_id = state.get("lobby_message_id")
        try:
            if message_id:
                await bot.edit_message_text(
                    "\n".join(lines), gid, int(message_id), parse_mode="HTML", reply_markup=kb
                )
            else:
                msg = await bot.send_message(
                    gid, "\n".join(lines), parse_mode="HTML", reply_markup=kb
                )
                save_lobby_state(game, lobby_message_id=int(msg.message_id))
            return True
        except Exception as exc:
            if "message is not modified" in str(exc).lower():
                return True
            # Only a missing/uneditable stored message is allowed to create a
            # replacement. The new id is persisted immediately, preventing a
            # repeated fallback from creating an unbounded message chain.
            logging.warning("lobby render failed game=%s group=%s: %s", game.get("id"), gid, exc)
            try:
                msg = await bot.send_message(
                    gid, "\n".join(lines), parse_mode="HTML", reply_markup=kb
                )
                save_lobby_state(game, lobby_message_id=int(msg.message_id))
                return True
            except Exception:
                logging.exception("lobby replacement send failed game=%s group=%s", game.get("id"), gid)
                return False

    async def new_game(callback: types.CallbackQuery):
        gid = group_id(callback)
        if not await is_manager(callback):
            await callback.answer("⛔ فقط گرداننده یا مدیر گروه می‌تواند بازی جدید ایجاد کند.", show_alert=True)
            return
        try:
            game = app.runtime.lobby.start_new(gid)
            # The selection screen itself belongs to this durable game.
            msg = callback.message
            await msg.edit_text(
                "📝 <b>انتخاب سناریو</b>\n\nسناریوی بازی را انتخاب کنید:",
                parse_mode="HTML", reply_markup=scenario_keyboard(int(game["id"])),
            )
            save_lobby_state(game, selection_message_id=int(msg.message_id), lobby_message_id=int(msg.message_id))
            app.ui.group_chat_id = gid
            await callback.answer("🎮 بازی جدید ایجاد شد؛ سناریو را انتخاب کنید.")
        except RuntimeError as exc:
            await callback.answer(str(exc), show_alert=True)
        except Exception:
            logging.exception("new game failed group=%s", gid)
            await callback.answer("❌ ایجاد بازی انجام نشد.", show_alert=True)

    async def scenario_selected(callback: types.CallbackQuery):
        parts = parse_callback(callback, "lobby", 4)
        if not parts or parts[2] != "scenario":
            await callback.answer("⚠️ درخواست نامعتبر.", show_alert=True)
            return
        gid = group_id(callback); game_id = int(parts[1]); scenario_id = int(parts[3])
        game, error = require_game(callback, game_id)
        if error:
            await callback.answer(error, show_alert=True); return
        if not await is_manager(callback, game):
            await callback.answer("⛔ فقط گرداننده یا مدیر گروه.", show_alert=True); return
        row = scenario_info(scenario_id)
        if not row or not row.get("is_active", True):
            await callback.answer("❌ سناریو معتبر نیست.", show_alert=True); return
        if not app.runtime.state.lobby.set_scenario(game_id, str(scenario_id)):
            await callback.answer("❌ ذخیره سناریو انجام نشد.", show_alert=True); return
        await callback.answer("✅ سناریو انتخاب شد؛ گرداننده را انتخاب کنید.")
        admins = await bot.get_chat_administrators(gid)
        kb = InlineKeyboardMarkup(row_width=1)
        for admin in admins:
            uid = int(admin.user.id)
            kb.add(InlineKeyboardButton(admin.user.full_name, callback_data=f"lobby:{game_id}:moderator:{uid}"))
        await callback.message.edit_text(
            "🎩 <b>انتخاب گرداننده</b>\n\nیکی از مدیران گروه را انتخاب کنید:",
            parse_mode="HTML", reply_markup=kb,
        )

    async def moderator_selected(callback: types.CallbackQuery):
        parts = parse_callback(callback, "lobby", 4)
        if not parts or parts[2] != "moderator":
            await callback.answer("⚠️ درخواست نامعتبر.", show_alert=True); return
        gid = group_id(callback); game_id = int(parts[1]); moderator_id = int(parts[3])
        game, error = require_game(callback, game_id)
        if error:
            await callback.answer(error, show_alert=True); return
        if not await is_manager(callback, game):
            await callback.answer("⛔ فقط مدیر گروه می‌تواند گرداننده را تعیین کند.", show_alert=True); return
        admins = await bot.get_chat_administrators(gid)
        admin_ids = {int(a.user.id) for a in admins}
        if moderator_id not in admin_ids:
            await callback.answer("❌ این کاربر دیگر مدیر گروه نیست.", show_alert=True); return
        if not app.runtime.state.lobby.set_moderator(game_id, moderator_id):
            await callback.answer("❌ ذخیره گرداننده انجام نشد.", show_alert=True); return
        await callback.answer("✅ گرداننده ثبت شد.")
        await render(gid, current_game(gid))

    async def toggle_join(callback: types.CallbackQuery):
        parts = parse_callback(callback, "lobby", 3)
        if not parts or parts[2] != "toggle":
            await callback.answer("⚠️ درخواست نامعتبر.", show_alert=True); return
        gid = group_id(callback); game_id = int(parts[1])
        game, error = require_game(callback, game_id)
        if error:
            await callback.answer(error, show_alert=True); return
        uid = int(callback.from_user.id)
        await app._ensure_player(callback.from_user)
        data = snapshot(gid); rows = data.get("players") or []
        current = next((r for r in rows if int(r["player_id"]) == uid and str(r.get("status") or "") not in {"removed", "finished"}), None)
        cap = capacity(game)
        occupied = {int(r["seat"]) for r in rows if r.get("seat") is not None and str(r.get("status") or "") not in {"removed", "dead", "finished"}}
        if current:
            old_seat = current.get("seat")
            if not app.runtime.state.lobby.leave(game_id, uid):
                await callback.answer("❌ خروج انجام نشد.", show_alert=True); return
            if old_seat is not None:
                app.runtime.state.lobby.promote_waiting(game_id, int(old_seat))
            await callback.answer("✅ از بازی خارج شدید.")
        else:
            seat = next((n for n in range(1, cap + 1) if n not in occupied), None)
            try:
                app.runtime.state.lobby.join(game_id, uid, seat, is_substitute=seat is None)
            except Exception as exc:
                logging.warning("lobby join rejected game=%s user=%s: %s", game_id, uid, exc)
                await callback.answer("❌ ورود به بازی انجام نشد؛ احتمالاً ظرفیت تغییر کرده است.", show_alert=True); return
            await callback.answer(f"✅ صندلی {seat} برای شما ثبت شد." if seat else "🎟 به لیست رزرو اضافه شدید.")
        await render(gid, current_game(gid))

    async def seat(callback: types.CallbackQuery):
        parts = parse_callback(callback, "lobby", 4)
        if not parts or parts[2] != "seat":
            await callback.answer("⚠️ درخواست نامعتبر.", show_alert=True); return
        gid = group_id(callback); game_id = int(parts[1]); target = int(parts[3])
        game, error = require_game(callback, game_id)
        if error:
            await callback.answer(error, show_alert=True); return
        cap = capacity(game)
        if target < 1 or target > cap:
            await callback.answer("❌ شماره صندلی نامعتبر است.", show_alert=True); return
        uid = int(callback.from_user.id); rows = snapshot(gid).get("players") or []
        current = next((r for r in rows if int(r["player_id"]) == uid and str(r.get("status") or "") not in {"removed", "finished"}), None)
        if not current:
            await callback.answer("ابتدا وارد بازی شوید.", show_alert=True); return
        occupied = {int(r["seat"]): int(r["player_id"]) for r in rows if r.get("seat") is not None}
        if target in occupied and occupied[target] != uid:
            await callback.answer("❌ این صندلی قبلاً گرفته شده است.", show_alert=True); return
        if not app.runtime.state.lobby.assign_seat(game_id, uid, target):
            await callback.answer("❌ تغییر صندلی انجام نشد.", show_alert=True); return
        await callback.answer(f"✅ صندلی {target} ثبت شد.")
        await render(gid, current_game(gid))

    async def reserve(callback: types.CallbackQuery):
        parts = parse_callback(callback, "lobby", 3)
        if not parts or parts[2] != "reserve":
            await callback.answer("⚠️ درخواست نامعتبر.", show_alert=True); return
        gid = group_id(callback); game_id = int(parts[1])
        game, error = require_game(callback, game_id)
        if error:
            await callback.answer(error, show_alert=True); return
        uid = int(callback.from_user.id); data = snapshot(gid); rows = data.get("players") or []
        cap = capacity(game)
        occupied = [r for r in rows if r.get("seat") is not None and str(r.get("status") or "") not in {"removed", "dead", "finished"}]
        if len(occupied) < cap:
            await callback.answer("رزرو پس از تکمیل ظرفیت فعال می‌شود.", show_alert=True); return
        current = next((r for r in rows if int(r["player_id"]) == uid and str(r.get("status") or "") not in {"removed", "finished"}), None)
        if current and current.get("seat") is None:
            app.runtime.state.lobby.leave(game_id, uid)
            await callback.answer("✅ رزرو لغو شد.")
        elif current:
            await callback.answer("شما در لیست اصلی هستید.", show_alert=True); return
        else:
            await app._ensure_player(callback.from_user)
            try:
                app.runtime.state.lobby.join(game_id, uid, None, is_substitute=True)
            except Exception:
                await callback.answer("❌ ثبت رزرو انجام نشد.", show_alert=True); return
            await callback.answer("🎟 به لیست رزرو اضافه شدید.")
        await render(gid, current_game(gid))

    async def management(callback: types.CallbackQuery):
        parts = parse_callback(callback, "lobby", 3)
        if not parts or parts[2] != "management":
            await callback.answer("⚠️ درخواست نامعتبر.", show_alert=True); return
        gid = group_id(callback); game_id = int(parts[1]); game, error = require_game(callback, game_id)
        if error:
            await callback.answer(error, show_alert=True); return
        if not await is_manager(callback, game):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        kb = InlineKeyboardMarkup(row_width=1)
        kb.add(
            InlineKeyboardButton("🔢 تغییر شماره بازی", callback_data=f"lobby:{game_id}:event_menu"),
            InlineKeyboardButton("📝 تغییر سناریو", callback_data=f"lobby:{game_id}:change_scenario"),
            InlineKeyboardButton("🎩 تغییر گرداننده", callback_data=f"lobby:{game_id}:change_moderator"),
            InlineKeyboardButton("🔄 بازسازی پیام لابی", callback_data=f"lobby:{game_id}:refresh"),
            InlineKeyboardButton("⬅️ بازگشت", callback_data=f"lobby:{game_id}:back"),
        )
        await callback.message.edit_text("⚙️ <b>مدیریت بازی</b>", parse_mode="HTML", reply_markup=kb)
        await callback.answer()

    async def event_menu(callback: types.CallbackQuery):
        parts = parse_callback(callback, "lobby", 3)
        if not parts or parts[2] != "event_menu":
            await callback.answer("⚠️ درخواست نامعتبر.", show_alert=True); return
        gid = group_id(callback); game_id = int(parts[1]); game, error = require_game(callback, game_id)
        if error:
            await callback.answer(error, show_alert=True); return
        if not await is_manager(callback, game):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        number = int(game.get("event_number") or 1)
        kb = InlineKeyboardMarkup(row_width=3)
        kb.row(
            InlineKeyboardButton("➖", callback_data=f"lobby:{game_id}:event:-1"),
            InlineKeyboardButton(f"🔢 {number}", callback_data=f"lobby:{game_id}:event:nochange"),
            InlineKeyboardButton("➕", callback_data=f"lobby:{game_id}:event:1"),
        )
        kb.add(InlineKeyboardButton("⬅️ بازگشت", callback_data=f"lobby:{game_id}:management"))
        await callback.message.edit_text("🔢 <b>شماره بازی</b>", parse_mode="HTML", reply_markup=kb)
        await callback.answer()

    async def event_adjust(callback: types.CallbackQuery):
        parts = parse_callback(callback, "lobby", 4)
        if not parts or parts[2] != "event":
            await callback.answer("⚠️ درخواست نامعتبر.", show_alert=True); return
        gid = group_id(callback); game_id = int(parts[1]); delta = parts[3]
        game, error = require_game(callback, game_id)
        if error:
            await callback.answer(error, show_alert=True); return
        if not await is_manager(callback, game):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        if delta == "nochange":
            await callback.answer(); return
        try:
            new_number = max(1, int(game.get("event_number") or 1) + int(delta))
        except ValueError:
            await callback.answer("❌ مقدار نامعتبر.", show_alert=True); return
        if not app.runtime.state.lobby.set_event_number(game_id, new_number):
            await callback.answer("❌ تغییر شماره انجام نشد.", show_alert=True); return
        await callback.answer(f"✅ شماره بازی: {new_number}")
        await event_menu(callback)

    async def change_scenario(callback: types.CallbackQuery):
        parts = parse_callback(callback, "lobby", 3)
        if not parts or parts[2] != "change_scenario":
            await callback.answer("⚠️ درخواست نامعتبر.", show_alert=True); return
        gid = group_id(callback); game_id = int(parts[1]); game, error = require_game(callback, game_id)
        if error:
            await callback.answer(error, show_alert=True); return
        if not await is_manager(callback, game):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        await callback.message.edit_text("📝 <b>تغییر سناریو</b>\n\nسناریوی جدید را انتخاب کنید:", parse_mode="HTML", reply_markup=scenario_keyboard(game_id))
        await callback.answer()

    async def change_moderator(callback: types.CallbackQuery):
        parts = parse_callback(callback, "lobby", 3)
        if not parts or parts[2] != "change_moderator":
            await callback.answer("⚠️ درخواست نامعتبر.", show_alert=True); return
        gid = group_id(callback); game_id = int(parts[1]); game, error = require_game(callback, game_id)
        if error:
            await callback.answer(error, show_alert=True); return
        if not await is_manager(callback, game):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        kb = InlineKeyboardMarkup(row_width=1)
        for admin in await bot.get_chat_administrators(gid):
            kb.add(InlineKeyboardButton(admin.user.full_name, callback_data=f"lobby:{game_id}:moderator:{int(admin.user.id)}"))
        await callback.message.edit_text("🎩 <b>تغییر گرداننده</b>", parse_mode="HTML", reply_markup=kb)
        await callback.answer()

    async def refresh(callback: types.CallbackQuery):
        parts = parse_callback(callback, "lobby", 3)
        if not parts or parts[2] != "refresh":
            await callback.answer("⚠️ درخواست نامعتبر.", show_alert=True); return
        gid = group_id(callback); game_id = int(parts[1]); game, error = require_game(callback, game_id)
        if error:
            await callback.answer(error, show_alert=True); return
        if not await is_manager(callback, game):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        state = lobby_state(game)
        state.pop("selection_message_id", None)
        save_lobby_state(game, **state)
        await render(gid, current_game(gid))
        await callback.answer("🔄 پیام لابی بازسازی شد.")

    async def back(callback: types.CallbackQuery):
        parts = parse_callback(callback, "lobby", 3)
        if not parts or parts[2] != "back":
            await callback.answer("⚠️ درخواست نامعتبر.", show_alert=True); return
        gid = group_id(callback); game_id = int(parts[1]); game, error = require_game(callback, game_id)
        if error:
            await callback.answer(error, show_alert=True); return
        if not await is_manager(callback, game):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        await render(gid, game)
        await callback.answer()

    async def cancel(callback: types.CallbackQuery):
        parts = parse_callback(callback, "lobby", 3)
        if not parts or parts[2] != "cancel":
            await callback.answer("⚠️ درخواست نامعتبر.", show_alert=True); return
        gid = group_id(callback); game_id = int(parts[1]); game, error = require_game(callback, game_id)
        if error:
            await callback.answer(error, show_alert=True); return
        if not await is_manager(callback, game):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        if not app.runtime.state.games.update_game(game_id, status="finished"):
            await callback.answer("❌ لغو بازی انجام نشد.", show_alert=True); return
        message_id = lobby_state(game).get("lobby_message_id")
        if message_id:
            try:
                await bot.edit_message_text("🚫 <b>این بازی لغو شد.</b>", gid, int(message_id), parse_mode="HTML", reply_markup=None)
            except Exception:
                logging.info("cancelled lobby message could not be edited game=%s", game_id)
        await callback.answer("🚫 بازی لغو شد.")

    async def distribute(callback: types.CallbackQuery):
        parts = parse_callback(callback, "lobby", 3)
        if not parts or parts[2] != "distribute":
            await callback.answer("⚠️ درخواست نامعتبر.", show_alert=True); return
        gid = group_id(callback); game_id = int(parts[1]); game, error = require_game(callback, game_id)
        if error:
            await callback.answer(error, show_alert=True); return
        if not await is_manager(callback, game):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        # Delegate to the authoritative role-distribution handler. It verifies
        # capacity and performs the lobby -> gameplay transition atomically at
        # the game-state level. A game-bound callback is also accepted by the
        # handler below through the optional parser installed there.
        await callback.answer("⏳ در حال پخش نقش‌ها...")
        # Keep the established callback contract for the role module while the
        # lobby itself remains game-bound. The module is invoked by a synthetic
        # callback-compatible flag stored only for this request.
        setattr(callback, "_canonical_lobby_game_id", game_id)
        await app._canonical_distribute_roles(callback)

    # Store the role callback entry point without importing/duplicating the
    # role-distribution implementation. main.py installs it after this module.
    async def canonical_distribute_roles(callback):
        await distribute(callback)

    app._canonical_distribute_roles = getattr(app, "_canonical_distribute_roles", None) or (lambda c: None)

    # The actual role module replaces this hook with its handler; when it does
    # not, the button still fails closed rather than executing a wrong game.
    async def dispatch_distribute(callback):
        handler = getattr(app, "_role_distribution_handler", None)
        if handler:
            await handler(callback)
        else:
            await callback.answer("❌ سرویس پخش نقش آماده نیست.", show_alert=True)

    app._canonical_distribute_roles = dispatch_distribute

    # Exact canonical callback surface. No aliases are intentionally accepted.
    dp.register_callback_query_handler(new_game, lambda c: c.data == "new_game", state="*")
    dp.register_callback_query_handler(scenario_selected, lambda c: str(c.data or "").startswith("lobby:") and ":scenario:" in str(c.data), state="*")
    dp.register_callback_query_handler(moderator_selected, lambda c: str(c.data or "").startswith("lobby:") and ":moderator:" in str(c.data), state="*")
    dp.register_callback_query_handler(toggle_join, lambda c: str(c.data or "").startswith("lobby:") and c.data.endswith(":toggle"), state="*")
    dp.register_callback_query_handler(seat, lambda c: str(c.data or "").startswith("lobby:") and ":seat:" in str(c.data), state="*")
    dp.register_callback_query_handler(reserve, lambda c: str(c.data or "").startswith("lobby:") and c.data.endswith(":reserve"), state="*")
    dp.register_callback_query_handler(management, lambda c: str(c.data or "").startswith("lobby:") and c.data.endswith(":management"), state="*")
    dp.register_callback_query_handler(event_menu, lambda c: str(c.data or "").startswith("lobby:") and c.data.endswith(":event_menu"), state="*")
    dp.register_callback_query_handler(event_adjust, lambda c: str(c.data or "").startswith("lobby:") and ":event:" in str(c.data), state="*")
    dp.register_callback_query_handler(change_scenario, lambda c: str(c.data or "").startswith("lobby:") and c.data.endswith(":change_scenario"), state="*")
    dp.register_callback_query_handler(change_moderator, lambda c: str(c.data or "").startswith("lobby:") and c.data.endswith(":change_moderator"), state="*")
    dp.register_callback_query_handler(refresh, lambda c: str(c.data or "").startswith("lobby:") and c.data.endswith(":refresh"), state="*")
    dp.register_callback_query_handler(back, lambda c: str(c.data or "").startswith("lobby:") and c.data.endswith(":back"), state="*")
    dp.register_callback_query_handler(cancel, lambda c: str(c.data or "").startswith("lobby:") and c.data.endswith(":cancel"), state="*")
    dp.register_callback_query_handler(distribute, lambda c: str(c.data or "").startswith("lobby:") and c.data.endswith(":distribute"), state="*")

    # Main menu is canonical too; the legacy MafiaApplication handler is
    # removed by _remove_legacy_handlers above.
    app._keyboard_main = lambda: InlineKeyboardMarkup(row_width=1).add(
        InlineKeyboardButton("🎮 بازی جدید", callback_data="new_game"),
        InlineKeyboardButton("📖 راهنما", callback_data="help"),
    )

    logging.info("CANONICAL_PRODUCTION_LOBBY_ACTIVE")
    return True
