"""Unified, final Telegram lobby implementation.

The lobby is intentionally the only active owner of lobby callbacks.  It keeps
legacy callback aliases where useful, but all state is stored in the persistent
game/game-player tables and every mutating callback carries the durable game id.
"""
from __future__ import annotations

import html
import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from aiogram import types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.exceptions import MessageCantBeEdited, MessageNotModified, MessageToEditNotFound

from repositories.scenario_repository import ScenarioRepository


LEGACY_LOBBY_HANDLERS = {
    "new_game", "join", "leave", "choose_scenario", "scenario_selected",
    "moderator_selected", "slot", "seat", "reserve", "change_scenario",
    "change_moderator", "cancel_game", "management", "event_number_menu",
    "event_number_adjust", "refresh_lobby", "back_lobby", "legacy_join",
    "legacy_leave", "waiting_join", "waiting_leave", "toggle_join",
}


def _remove_lobby_handlers(dp) -> int:
    table = getattr(dp.callback_query_handlers, "handlers", [])
    kept = []
    removed = 0
    for item in table:
        fn = getattr(item, "callback", None)
        if getattr(fn, "__name__", "") in LEGACY_LOBBY_HANDLERS:
            removed += 1
        else:
            kept.append(item)
    table[:] = kept
    return removed


def install(app: Any) -> bool:
    dp, bot = app.dp, app.bot
    scenarios = ScenarioRepository()
    removed = _remove_lobby_handlers(dp)
    logging.info("UNIFIED_LOBBY_INSTALL removed_legacy_handlers=%d", removed)

    if not hasattr(app, "_lobby_render_lock"):
        app._lobby_render_lock = None

    def gid(cb: types.CallbackQuery) -> int:
        return int(cb.message.chat.id)

    def game_for(group_id: int) -> dict[str, Any] | None:
        return app.runtime.state.active_game(int(group_id))

    def snapshot(group_id: int) -> dict[str, Any]:
        return app.runtime.lobby_snapshot(int(group_id))

    def state(game: dict[str, Any]) -> dict[str, Any]:
        return dict(game.get("state") or {})

    def save_state(game: dict[str, Any], **changes: Any) -> bool:
        value = state(game)
        value.update(changes)
        return bool(app.runtime.state.games.update_game(int(game["id"]), state=value))

    def scenario_info(value: Any) -> dict[str, Any] | None:
        if value is None:
            return None
        try:
            return scenarios.get_by_id(value)
        except (TypeError, ValueError):
            return scenarios.get_by_name(str(value))

    def scenario_name(value: Any) -> str:
        row = scenario_info(value)
        return str((row or {}).get("name") or value or "انتخاب نشده")

    def capacity(game: dict[str, Any]) -> int:
        row = scenario_info(game.get("scenario_id"))
        roles = (row or {}).get("roles") or []
        return len(roles)

    def name(row: dict[str, Any] | None) -> str:
        if not row:
            return "❓"
        return str(row.get("nickname") or row.get("first_name") or row.get("username") or row.get("player_id") or "❓")

    def mention(uid: int, label: str | None = None) -> str:
        return f'<a href="tg://user?id={int(uid)}"><b>{html.escape(str(label or uid))}</b></a>'

    def parse(data: Any) -> list[str]:
        return str(data or "").split(":")

    async def answer(cb: types.CallbackQuery, text: str = "", *, alert: bool = False) -> None:
        try:
            await cb.answer(text, show_alert=alert)
        except Exception as exc:
            # Telegram callback queries expire quickly; a late answer must never
            # turn an otherwise successful lobby action into a 500 response.
            if "query is too old" not in str(exc).lower() and "invalid" not in str(exc).lower():
                logging.debug("callback answer failed: %s", exc)

    async def manager(cb: types.CallbackQuery, game: dict[str, Any] | None = None) -> bool:
        game = game or game_for(gid(cb))
        uid = int(cb.from_user.id)
        if game and uid == int(game.get("moderator_id") or 0):
            return True
        try:
            member = await bot.get_chat_member(gid(cb), uid)
            return member.status in {"creator", "administrator"}
        except Exception:
            return False

    def require(cb: types.CallbackQuery, game_id: int, *, lobby_only: bool = True):
        game = game_for(gid(cb))
        if not game:
            return None, "❌ بازی فعالی وجود ندارد."
        if int(game.get("id")) != int(game_id):
            return None, "⚠️ این دکمه مربوط به بازی قبلی است."
        if lobby_only and str(game.get("status") or "") != "lobby":
            return None, "❌ لابی فعال نیست."
        return game, None

    def scenario_keyboard(game_id: int, *, back_to_management: bool = False) -> InlineKeyboardMarkup:
        kb = InlineKeyboardMarkup(row_width=1)
        for row in scenarios.list_active():
            sid = int(row["id"])
            kb.add(InlineKeyboardButton(
                f"📝 {row.get('name') or sid} ({len(row.get('roles') or [])} نقش)",
                callback_data=f"lobby:{game_id}:scenario:{sid}",
            ))
        if back_to_management:
            kb.add(InlineKeyboardButton("⬅️ بازگشت", callback_data=f"lobby:{game_id}:management"))
        return kb

    def moderator_keyboard(game_id: int, admins: list[Any], *, back: bool = True) -> InlineKeyboardMarkup:
        kb = InlineKeyboardMarkup(row_width=1)
        for admin in admins:
            uid = int(admin.user.id)
            kb.add(InlineKeyboardButton(
                admin.user.full_name or admin.user.username or str(uid),
                callback_data=f"lobby:{game_id}:moderator:{uid}",
            ))
        if back:
            kb.add(InlineKeyboardButton("⬅️ بازگشت", callback_data=f"lobby:{game_id}:management"))
        return kb

    def build_text(game: dict[str, Any], rows: list[dict[str, Any]], cap: int) -> tuple[str, InlineKeyboardMarkup]:
        active = [r for r in rows if r.get("seat") is not None and str(r.get("status") or "active") not in {"removed", "dead", "finished"}]
        waiting = [r for r in rows if r.get("seat") is None and str(r.get("status") or "waiting") in {"waiting", "substitute"}]
        active.sort(key=lambda r: int(r.get("seat") or 999))
        occupied = {int(r["seat"]): r for r in active}
        moderator_id = int(game.get("moderator_id") or 0)
        moderator_row = next((r for r in rows if int(r.get("player_id") or 0) == moderator_id), None)
        moderator_label = name(moderator_row) if moderator_row else (str(moderator_id) if moderator_id else "❓")

        lines = [
            "༄ <b>لیست بازی Mafia Nights</b>",
            "",
            f"📅 <b>تاریخ:</b> {datetime.now(ZoneInfo('Asia/Tehran')).strftime('%Y/%m/%d')}",
            f"📝 <b>سناریو:</b> {html.escape(scenario_name(game.get('scenario_id')))}",
            f"🔢 <b>شماره بازی:</b> {int(game.get('event_number') or 1)}",
            f"🎩 <b>گرداننده:</b> {mention(moderator_id, moderator_label) if moderator_id else '❌ انتخاب نشده'}",
            "",
            "━━━━━━━━━━━━━━━━━━",
            f"👥 <b>بازیکنان:</b> {len(active)}/{cap}",
            "",
            "🪑 <b>لیست صندلی‌ها</b>",
        ]
        for seat_no in range(1, cap + 1):
            row = occupied.get(seat_no)
            if row:
                lines.append(f"{seat_no:02d}. {mention(int(row['player_id']), name(row))}")
            else:
                lines.append(f"{seat_no:02d}. ⬜ آزاد")
        if waiting:
            lines += ["", "🎟 <b>لیست رزرو</b>"]
            for index, row in enumerate(waiting, 1):
                lines.append(f"{index}. {mention(int(row['player_id']), name(row))}")
        lines += ["", "━━━━━━━━━━━━━━━━━━"]

        kb = InlineKeyboardMarkup(row_width=3)
        # Keep the classic seat grid: three buttons per row and only seats that
        # are currently useful. Occupied seats remain clickable so players can
        # change their seat; an occupied seat is rejected for other users.
        for seat_no in range(1, cap + 1):
            row = occupied.get(seat_no)
            label = f"{seat_no:02d} {name(row)[:10]}" if row else f"{seat_no:02d} ⬜"
            kb.insert(InlineKeyboardButton(label, callback_data=f"lobby:{int(game['id'])}:seat:{seat_no}"))
        kb.row(
            InlineKeyboardButton("✅ ورود", callback_data=f"lobby:{int(game['id'])}:join"),
            InlineKeyboardButton("❌ خروج", callback_data=f"lobby:{int(game['id'])}:leave"),
        )
        if len(active) >= cap > 0:
            kb.row(InlineKeyboardButton("🎟 رزرو / لغو رزرو", callback_data=f"lobby:{int(game['id'])}:reserve"))
            kb.row(InlineKeyboardButton("🎭 پخش نقش", callback_data=f"lobby:{int(game['id'])}:distribute"))
        kb.row(InlineKeyboardButton("📝 انتخاب سناریو", callback_data=f"lobby:{int(game['id'])}:change_scenario"))
        kb.row(InlineKeyboardButton("🎩 انتخاب گرداننده", callback_data=f"lobby:{int(game['id'])}:change_moderator"))
        kb.row(InlineKeyboardButton("⚙️ مدیریت بازی", callback_data=f"lobby:{int(game['id'])}:management"))
        kb.row(InlineKeyboardButton("🚫 لغو بازی", callback_data=f"lobby:{int(game['id'])}:cancel"))
        return "\n".join(lines), kb

    async def render(group_id: int, game: dict[str, Any] | None = None) -> bool:
        game = game or game_for(group_id)
        if not game or str(game.get("status") or "") != "lobby":
            return False
        # The selection screen is the lobby message until both values exist.
        data = snapshot(group_id)
        game = data.get("game") or game
        rows = data.get("players") or []
        cap = capacity(game)
        text, kb = build_text(game, rows, cap)
        message_id = state(game).get("lobby_message_id")
        try:
            if message_id:
                await bot.edit_message_text(text, group_id, int(message_id), parse_mode="HTML", reply_markup=kb)
            else:
                msg = await bot.send_message(group_id, text, parse_mode="HTML", reply_markup=kb)
                save_state(game, lobby_message_id=int(msg.message_id))
            return True
        except (MessageNotModified, MessageCantBeEdited):
            return True
        except MessageToEditNotFound:
            pass
        except Exception as exc:
            if "message is not modified" in str(exc).lower():
                return True
            logging.warning("lobby render failed game=%s group=%s: %s", game.get("id"), group_id, exc)
        try:
            msg = await bot.send_message(group_id, text, parse_mode="HTML", reply_markup=kb)
            save_state(game, lobby_message_id=int(msg.message_id))
            return True
        except Exception:
            logging.exception("lobby replacement send failed game=%s group=%s", game.get("id"), group_id)
            return False

    app._render_production_lobby = render
    app._production_lobby_render = render
    app._production_lobby_game_id = game_for

    async def new_game(cb: types.CallbackQuery):
        await answer(cb)
        group_id = gid(cb)
        if not await manager(cb):
            await answer(cb, "⛔ فقط گرداننده یا مدیر گروه می‌تواند بازی جدید ایجاد کند.", alert=True); return
        try:
            game = app.runtime.lobby.start_new(group_id)
            msg = cb.message
            await msg.edit_text("📝 <b>انتخاب سناریو</b>\n\nسناریوی بازی را انتخاب کنید:", parse_mode="HTML", reply_markup=scenario_keyboard(int(game["id"])))
            save_state(game, lobby_message_id=int(msg.message_id), selection_message_id=int(msg.message_id))
            app.ui.group_chat_id = group_id
        except RuntimeError as exc:
            await answer(cb, str(exc), alert=True)
        except Exception:
            logging.exception("new game failed group=%s", group_id)
            await answer(cb, "❌ ایجاد بازی انجام نشد.", alert=True)

    async def scenario_selected(cb: types.CallbackQuery):
        await answer(cb)
        parts = parse(cb.data)
        if len(parts) != 4 or parts[0] != "lobby" or parts[2] != "scenario":
            return
        group_id, game_id, sid = gid(cb), int(parts[1]), int(parts[3])
        game, error = require(cb, game_id)
        if error: await answer(cb, error, alert=True); return
        if not await manager(cb, game): await answer(cb, "⛔ فقط گرداننده یا مدیر گروه.", alert=True); return
        row = scenario_info(sid)
        if not row or not row.get("is_active", True): await answer(cb, "❌ سناریو معتبر نیست.", alert=True); return
        if not app.runtime.state.lobby.set_scenario(game_id, str(sid)):
            await answer(cb, "❌ ذخیره سناریو انجام نشد.", alert=True); return
        try:
            admins = await bot.get_chat_administrators(group_id)
            await cb.message.edit_text("🎩 <b>انتخاب گرداننده</b>\n\nیکی از مدیران گروه را انتخاب کنید:", parse_mode="HTML", reply_markup=moderator_keyboard(game_id, admins))
        except Exception:
            logging.exception("failed to render moderator selector game=%s", game_id)
            await render(group_id, game_for(group_id))

    async def moderator_selected(cb: types.CallbackQuery):
        await answer(cb)
        parts = parse(cb.data)
        if len(parts) != 4 or parts[0] != "lobby" or parts[2] != "moderator": return
        group_id, game_id, moderator_id = gid(cb), int(parts[1]), int(parts[3])
        game, error = require(cb, game_id)
        if error: await answer(cb, error, alert=True); return
        if not await manager(cb, game): await answer(cb, "⛔ فقط مدیر گروه می‌تواند گرداننده را تعیین کند.", alert=True); return
        try:
            admins = await bot.get_chat_administrators(group_id)
            if moderator_id not in {int(x.user.id) for x in admins}:
                await answer(cb, "❌ این کاربر دیگر مدیر گروه نیست.", alert=True); return
        except Exception:
            await answer(cb, "❌ بررسی مدیران گروه انجام نشد.", alert=True); return
        if not app.runtime.state.lobby.set_moderator(game_id, moderator_id):
            await answer(cb, "❌ ذخیره گرداننده انجام نشد.", alert=True); return
        await render(group_id, game_for(group_id))

    async def join(cb: types.CallbackQuery):
        await answer(cb)
        parts = parse(cb.data); group_id = gid(cb)
        game_id = int(parts[1]) if len(parts) >= 3 and parts[0] == "lobby" else int((game_for(group_id) or {}).get("id") or 0)
        game, error = require(cb, game_id)
        if error: await answer(cb, error, alert=True); return
        user = cb.from_user
        await app._ensure_player(user)
        data = snapshot(group_id); rows = data.get("players") or []
        existing = next((r for r in rows if int(r.get("player_id") or 0) == int(user.id) and str(r.get("status") or "") not in {"removed", "finished"}), None)
        if existing:
            await answer(cb, "⚠️ شما قبلاً وارد بازی شده‌اید.", alert=True); return
        cap = capacity(game)
        if not cap: await answer(cb, "⚠️ ابتدا سناریو را انتخاب کنید.", alert=True); return
        occupied = {int(r["seat"]) for r in rows if r.get("seat") is not None and str(r.get("status") or "") not in {"removed", "dead", "finished"}}
        seat = next((n for n in range(1, cap + 1) if n not in occupied), None)
        try:
            app.runtime.state.lobby.join(game_id, int(user.id), seat, is_substitute=seat is None)
        except Exception as exc:
            logging.warning("join rejected game=%s user=%s: %s", game_id, user.id, exc)
            await answer(cb, "❌ ورود انجام نشد؛ احتمالاً صندلی همزمان گرفته شده است.", alert=True); return
        await render(group_id, game_for(group_id))

    async def leave(cb: types.CallbackQuery):
        await answer(cb)
        parts = parse(cb.data); group_id = gid(cb)
        game_id = int(parts[1]) if len(parts) >= 3 and parts[0] == "lobby" else int((game_for(group_id) or {}).get("id") or 0)
        game, error = require(cb, game_id)
        if error: await answer(cb, error, alert=True); return
        rows = snapshot(group_id).get("players") or []
        current = next((r for r in rows if int(r.get("player_id") or 0) == int(cb.from_user.id)), None)
        old_seat = current.get("seat") if current else None
        if not app.runtime.state.lobby.leave(game_id, int(cb.from_user.id)):
            await answer(cb, "⚠️ شما در بازی نیستید.", alert=True); return
        if old_seat is not None:
            try: app.runtime.state.lobby.promote_waiting(game_id, int(old_seat))
            except Exception: logging.exception("waiting promotion failed game=%s seat=%s", game_id, old_seat)
        await render(group_id, game_for(group_id))

    async def seat(cb: types.CallbackQuery):
        await answer(cb)
        parts = parse(cb.data)
        if len(parts) != 4 or parts[0] != "lobby" or parts[2] != "seat": return
        group_id, game_id, target = gid(cb), int(parts[1]), int(parts[3])
        game, error = require(cb, game_id)
        if error: await answer(cb, error, alert=True); return
        cap = capacity(game)
        if target < 1 or target > cap: await answer(cb, "❌ شماره صندلی نامعتبر است.", alert=True); return
        rows = snapshot(group_id).get("players") or []
        uid = int(cb.from_user.id)
        current = next((r for r in rows if int(r.get("player_id") or 0) == uid and str(r.get("status") or "") not in {"removed", "finished"}), None)
        if not current: await answer(cb, "ابتدا وارد بازی شوید.", alert=True); return
        occupied = {int(r["seat"]): int(r["player_id"]) for r in rows if r.get("seat") is not None and str(r.get("status") or "") not in {"removed", "finished"}}
        if target in occupied and occupied[target] != uid: await answer(cb, "❌ این صندلی قبلاً گرفته شده است.", alert=True); return
        try: app.runtime.state.lobby.assign_seat(game_id, uid, target)
        except Exception: await answer(cb, "❌ تغییر صندلی انجام نشد.", alert=True); return
        await render(group_id, game_for(group_id))

    async def reserve(cb: types.CallbackQuery):
        await answer(cb)
        parts = parse(cb.data)
        if len(parts) != 3 or parts[0] != "lobby": return
        group_id, game_id = gid(cb), int(parts[1])
        game, error = require(cb, game_id)
        if error: await answer(cb, error, alert=True); return
        rows = snapshot(group_id).get("players") or []
        cap = capacity(game)
        active = [r for r in rows if r.get("seat") is not None and str(r.get("status") or "") not in {"removed", "dead", "finished"}]
        if len(active) < cap: await answer(cb, "رزرو پس از تکمیل ظرفیت فعال می‌شود.", alert=True); return
        uid = int(cb.from_user.id)
        current = next((r for r in rows if int(r.get("player_id") or 0) == uid and str(r.get("status") or "") not in {"removed", "finished"}), None)
        if current and current.get("seat") is None:
            app.runtime.state.lobby.leave(game_id, uid); await render(group_id, game_for(group_id)); return
        if current: await answer(cb, "⚠️ شما در لیست اصلی بازی هستید.", alert=True); return
        await app._ensure_player(cb.from_user)
        try: app.runtime.state.lobby.join(game_id, uid, None, is_substitute=True)
        except Exception: await answer(cb, "❌ ثبت رزرو انجام نشد.", alert=True); return
        await render(group_id, game_for(group_id))

    async def management(cb: types.CallbackQuery):
        await answer(cb)
        parts = parse(cb.data)
        if len(parts) != 3 or parts[0] != "lobby": return
        group_id, game_id = gid(cb), int(parts[1]); game, error = require(cb, game_id)
        if error: await answer(cb, error, alert=True); return
        if not await manager(cb, game): await answer(cb, "⛔ دسترسی ندارید.", alert=True); return
        kb = InlineKeyboardMarkup(row_width=1).add(
            InlineKeyboardButton("🔢 تغییر شماره بازی", callback_data=f"lobby:{game_id}:event_menu"),
            InlineKeyboardButton("📝 تغییر سناریو", callback_data=f"lobby:{game_id}:change_scenario"),
            InlineKeyboardButton("🎩 تغییر گرداننده", callback_data=f"lobby:{game_id}:change_moderator"),
            InlineKeyboardButton("🔄 بازسازی پیام لابی", callback_data=f"lobby:{game_id}:refresh"),
            InlineKeyboardButton("⬅️ بازگشت", callback_data=f"lobby:{game_id}:back"),
        )
        await cb.message.edit_text("⚙️ <b>مدیریت بازی</b>", parse_mode="HTML", reply_markup=kb)

    async def event_menu(cb: types.CallbackQuery):
        await answer(cb)
        parts = parse(cb.data)
        if len(parts) != 3 or parts[2] != "event_menu": return
        game, error = require(cb, int(parts[1]))
        if error: await answer(cb, error, alert=True); return
        if not await manager(cb, game): await answer(cb, "⛔ دسترسی ندارید.", alert=True); return
        n = int(game.get("event_number") or 1)
        kb = InlineKeyboardMarkup(row_width=3).row(
            InlineKeyboardButton("➖", callback_data=f"lobby:{game['id']}:event:-1"),
            InlineKeyboardButton(f"🔢 {n}", callback_data=f"lobby:{game['id']}:event:nochange"),
            InlineKeyboardButton("➕", callback_data=f"lobby:{game['id']}:event:1"),
        ).add(InlineKeyboardButton("⬅️ بازگشت", callback_data=f"lobby:{game['id']}:management"))
        await cb.message.edit_text("🔢 <b>شماره بازی</b>", parse_mode="HTML", reply_markup=kb)

    async def event_adjust(cb: types.CallbackQuery):
        await answer(cb)
        parts = parse(cb.data)
        if len(parts) != 4 or parts[2] != "event": return
        game, error = require(cb, int(parts[1]))
        if error: await answer(cb, error, alert=True); return
        if not await manager(cb, game): await answer(cb, "⛔ دسترسی ندارید.", alert=True); return
        if parts[3] == "nochange": return
        new_number = max(1, int(game.get("event_number") or 1) + int(parts[3]))
        if not app.runtime.state.lobby.set_event_number(int(game["id"]), new_number):
            await answer(cb, "❌ تغییر شماره انجام نشد.", alert=True); return
        await event_menu(cb)

    async def change_scenario(cb: types.CallbackQuery):
        await answer(cb)
        parts = parse(cb.data)
        if len(parts) != 3: return
        game, error = require(cb, int(parts[1]))
        if error: await answer(cb, error, alert=True); return
        if not await manager(cb, game): await answer(cb, "⛔ دسترسی ندارید.", alert=True); return
        await cb.message.edit_text("📝 <b>تغییر سناریو</b>\n\nسناریوی جدید را انتخاب کنید:", parse_mode="HTML", reply_markup=scenario_keyboard(int(game["id"]), back_to_management=True))

    async def change_moderator(cb: types.CallbackQuery):
        await answer(cb)
        parts = parse(cb.data)
        if len(parts) != 3: return
        game, error = require(cb, int(parts[1]))
        if error: await answer(cb, error, alert=True); return
        if not await manager(cb, game): await answer(cb, "⛔ دسترسی ندارید.", alert=True); return
        try: admins = await bot.get_chat_administrators(gid(cb))
        except Exception: await answer(cb, "❌ دریافت مدیران گروه انجام نشد.", alert=True); return
        await cb.message.edit_text("🎩 <b>انتخاب گرداننده</b>", parse_mode="HTML", reply_markup=moderator_keyboard(int(game["id"]), admins))

    async def refresh(cb: types.CallbackQuery):
        await answer(cb)
        parts = parse(cb.data)
        if len(parts) != 3: return
        game, error = require(cb, int(parts[1]))
        if error: await answer(cb, error, alert=True); return
        if not await manager(cb, game): await answer(cb, "⛔ دسترسی ندارید.", alert=True); return
        ok = await render(gid(cb), game_for(gid(cb)))
        await answer(cb, "🔄 پیام لابی به‌روزرسانی شد." if ok else "❌ بازسازی انجام نشد.", alert=not ok)

    async def back(cb: types.CallbackQuery):
        await answer(cb)
        parts = parse(cb.data)
        if len(parts) != 3: return
        game, error = require(cb, int(parts[1]))
        if error: await answer(cb, error, alert=True); return
        if not await manager(cb, game): await answer(cb, "⛔ دسترسی ندارید.", alert=True); return
        await render(gid(cb), game)

    async def cancel(cb: types.CallbackQuery):
        await answer(cb)
        parts = parse(cb.data)
        if len(parts) != 3: return
        group_id, game_id = gid(cb), int(parts[1])
        game, error = require(cb, game_id)
        if error: await answer(cb, error, alert=True); return
        if not await manager(cb, game): await answer(cb, "⛔ دسترسی ندارید.", alert=True); return
        if not app.runtime.state.games.update_game(game_id, status="finished", state={}):
            await answer(cb, "❌ لغو بازی انجام نشد.", alert=True); return
        try: app.runtime.state.games.clear_game_players(game_id)
        except Exception: logging.exception("failed to clear cancelled lobby players game=%s", game_id)
        message_id = state(game).get("lobby_message_id")
        if message_id:
            try: await bot.edit_message_text("🚫 <b>این بازی لغو شد.</b>", group_id, int(message_id), parse_mode="HTML", reply_markup=None)
            except Exception: logging.debug("cancelled lobby message could not be edited")

    async def distribute(cb: types.CallbackQuery):
        await answer(cb)
        parts = parse(cb.data)
        if len(parts) != 3: return
        game, error = require(cb, int(parts[1]))
        if error: await answer(cb, error, alert=True); return
        if not await manager(cb, game): await answer(cb, "⛔ فقط گرداننده یا مدیر گروه.", alert=True); return
        setattr(cb, "_canonical_lobby_game_id", int(game["id"]))
        await app._canonical_distribute_roles(cb)

    # Canonical callback names are game-id scoped. Legacy aliases remain only
    # as harmless compatibility aliases and are routed into this same code.
    dp.register_callback_query_handler(new_game, lambda c: c.data == "new_game", state="*")
    dp.register_callback_query_handler(scenario_selected, lambda c: str(c.data or "").startswith("lobby:") and ":scenario:" in str(c.data), state="*")
    dp.register_callback_query_handler(moderator_selected, lambda c: str(c.data or "").startswith("lobby:") and ":moderator:" in str(c.data), state="*")
    dp.register_callback_query_handler(join, lambda c: str(c.data or "").startswith("lobby:") and (c.data.endswith(":join") or c.data.endswith(":toggle")), state="*")
    dp.register_callback_query_handler(leave, lambda c: str(c.data or "").startswith("lobby:") and c.data.endswith(":leave"), state="*")
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

    # Also expose the legacy-looking keyboard helpers expected by older UI code.
    app._keyboard_lobby = lambda scenario, group_id: build_text(game_for(group_id) or {}, snapshot(group_id).get("players") or [], capacity(game_for(group_id) or {}))[1]
    return True
