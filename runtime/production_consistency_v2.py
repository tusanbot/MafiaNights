"""Final runtime consistency authority.

Installed last so historical panel builders cannot reintroduce duplicate
buttons. Also owns the finished-game event read/record flow and attendance UI.
"""
from __future__ import annotations

import html
import logging
from datetime import datetime, timezone
from typing import Any

from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


class RecordEventsState(StatesGroup):
    waiting_for_events = State()


def _registry(dp):
    return getattr(getattr(dp, "callback_query_handlers", None), "handlers", [])


def _fn(item):
    return getattr(item, "handler", None) or getattr(item, "callback", None)


def _remove_callbacks(dp, predicate):
    reg = _registry(dp)
    reg[:] = [item for item in reg if not predicate(_fn(item))]


def _latest_finished(app: Any, group_id: int | None = None):
    games = app.runtime.state.games.list_finished_games(group_id, limit=1) if group_id is not None else app.runtime.state.games.list_finished_games(limit=1)
    return (games or [None])[0]


def _events_text(game: dict[str, Any]) -> str:
    state = dict(game.get("state") or {})
    events = state.get("game_events")
    if not isinstance(events, dict):
        return ""
    return str(events.get("text") or "").strip()


def _final_menu(game_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(row_width=2).add(
        InlineKeyboardButton("📊 نتیجه بازی", callback_data=f"game_end:{int(game_id)}:result"),
        InlineKeyboardButton("📚 بازی‌های گذشته", callback_data=f"game_history:list:{int(game_id)}"),
        InlineKeyboardButton("✖️ بستن", callback_data=f"game_end:{int(game_id)}:close"),
    )


def _record_panel(game: dict[str, Any]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(row_width=1).add(
        InlineKeyboardButton(
            f"📝 ثبت اتفاقات بازی {int(game.get('event_number') or 1)}",
            callback_data=f"events_record:{int(game['id'])}:{int(game.get('group_chat_id') or 0)}",
        ),
    )


def _canonical_management_panel(app: Any, management: Any):
    def panel(game_id):
        game = management._game(int(game_id))
        if not game:
            return InlineKeyboardMarkup()
        gid = int(game["id"])
        status = str(game.get("status") or "lobby")
        rows = [
            [InlineKeyboardButton("🔢 شماره بازی", callback_data=f"mgmt:{gid}:event"), InlineKeyboardButton("📝 تغییر سناریو", callback_data=f"mgmt:{gid}:scenario"), InlineKeyboardButton("🗑 حذف بازیکن", callback_data=f"mgmt:{gid}:remove")],
            [InlineKeyboardButton("🎟 لغو رزرو", callback_data=f"mgmt:{gid}:unreserve"), InlineKeyboardButton("🔄 جایگزین بازیکن", callback_data=f"mgmt:{gid}:replace"), InlineKeyboardButton("✅ حاضری", callback_data=f"mgmt:{gid}:attendance")],
            [InlineKeyboardButton("🎂 تولد بازیکن", callback_data=f"mgmt:{gid}:birthday"), InlineKeyboardButton("⚔ وضعیت چالش", callback_data=f"mgmt:{gid}:challenge"), InlineKeyboardButton("⏭ مدیریت نکست", callback_data=f"mgmt:{gid}:next")],
            [InlineKeyboardButton("ℹ️ اطلاعات بازی", callback_data=f"mgmt:{gid}:info"), InlineKeyboardButton("🦵 کیک از بازی", callback_data=f"mgmt:{gid}:kick"), InlineKeyboardButton("⚠️ تذکر به بازیکن", callback_data=f"mgmt:{gid}:warning")],
            [InlineKeyboardButton("➕ ترن اضافه", callback_data=f"mgmt:{gid}:extra"), InlineKeyboardButton("🔇 سکوت بازیکن", callback_data=f"mgmt:{gid}:mute"), InlineKeyboardButton("🔊 حذف سکوت", callback_data=f"mgmt:{gid}:unmute")],
        ]
        if status == "running":
            rows.append([InlineKeyboardButton("🏁 اتمام بازی", callback_data=f"mgmt:{gid}:finish"), InlineKeyboardButton("🚫 لغو بازی", callback_data=f"mgmt:{gid}:cancel")])
        else:
            rows.append([InlineKeyboardButton("🚫 لغو بازی", callback_data=f"mgmt:{gid}:cancel")])
        rows.append([InlineKeyboardButton("⬅️ بازگشت به لابی", callback_data=f"mgmt:{gid}:back_lobby")])
        return InlineKeyboardMarkup(inline_keyboard=rows)
    return panel


async def install(app: Any) -> bool:
    if getattr(app, "_production_consistency_v2", False):
        return False
    app._production_consistency_v2 = True
    dp = app.dp
    management = getattr(app, "game_management", None)
    if management:
        management.panel = _canonical_management_panel(app, management)

    # Final result/history handlers. Remove every previous namespace handler so
    # a legacy handler cannot consume the callback before the working one.
    try:
        from runtime import game_end

        async def game_end_authority(callback: types.CallbackQuery):
            parts = str(callback.data or "").split(":")
            if len(parts) != 3 or parts[0] != "game_end": return
            game_id, action = int(parts[1]), parts[2]
            game = app.runtime.state.games.get_game(game_id)
            if not game:
                await callback.answer("❌ بازی پیدا نشد.", show_alert=True); return
            uid = int(callback.from_user.id); gid = int(game.get("group_chat_id") or callback.message.chat.id)
            allowed = uid == int(game.get("moderator_id") or 0)
            if not allowed:
                try: allowed = (await app.bot.get_chat_member(gid, uid)).status in {"creator", "administrator"}
                except Exception: allowed = False
            if not allowed:
                await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
            if action == "close":
                try: await callback.message.delete()
                except Exception: pass
                await callback.answer(); return
            if action == "result":
                rows = app.runtime.state.games.list_players(game_id)
                await callback.message.edit_text(game_end._final_text(game, rows), parse_mode="HTML", reply_markup=_final_menu(game_id))
                await callback.answer(); return
            await callback.answer("❌ عملیات نامعتبر است.", show_alert=True)

        async def history_list_authority(callback: types.CallbackQuery):
            parts = str(callback.data or "").split(":")
            if len(parts) != 3 or parts[:2] != ["game_history", "list"]: return
            reference = app.runtime.state.games.get_game(int(parts[2]))
            if not reference:
                await callback.answer("❌ بازی پیدا نشد.", show_alert=True); return
            gid = int(reference.get("group_chat_id") or callback.message.chat.id); uid = int(callback.from_user.id)
            allowed = uid == int(reference.get("moderator_id") or 0)
            if not allowed:
                try: allowed = (await app.bot.get_chat_member(gid, uid)).status in {"creator", "administrator"}
                except Exception: allowed = False
            if not allowed:
                await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
            games = app.runtime.state.games.list_finished_games(gid, limit=20) or []
            if not games:
                await callback.answer("ℹ️ هنوز بازی ثبت نهایی‌شده‌ای وجود ندارد.", show_alert=True); return
            kb = InlineKeyboardMarkup(row_width=1)
            for g in games:
                st = dict(g.get("state") or {})
                label = str(st.get("game_result_label") or st.get("game_result") or "بدون نتیجه")
                kb.add(InlineKeyboardButton(f"📓 بازی {int(g.get('event_number') or 1)} — {label}", callback_data=f"game_history:view:{int(g['id'])}"))
            kb.add(InlineKeyboardButton("✖️ بستن", callback_data=f"game_end:{int(reference['id'])}:close"))
            await callback.message.edit_text("📚 <b>بازی‌های گذشته</b>\n\nبازی موردنظر را انتخاب کنید:", parse_mode="HTML", reply_markup=kb)
            await callback.answer()

        async def history_view_authority(callback: types.CallbackQuery):
            parts = str(callback.data or "").split(":")
            if len(parts) != 3 or parts[:2] != ["game_history", "view"]: return
            game = app.runtime.state.games.get_finished_game(int(parts[2]))
            if not game:
                await callback.answer("❌ این بازی در آرشیو پیدا نشد.", show_alert=True); return
            rows = app.runtime.state.games.list_players(int(parts[2]))
            await callback.message.edit_text(game_end._final_text(game, rows), parse_mode="HTML", reply_markup=_final_menu(int(parts[2])))
            await callback.answer()

        _remove_callbacks(dp, lambda fn: getattr(fn, "__name__", "") in {"game_end", "game_history", "game_end_authority", "history_list_authority", "history_view_authority"})
        dp.register_callback_query_handler(history_view_authority, lambda c: str(c.data or "").startswith("game_history:view:"), state="*")
        dp.register_callback_query_handler(history_list_authority, lambda c: str(c.data or "").startswith("game_history:list:"), state="*")
        dp.register_callback_query_handler(game_end_authority, lambda c: str(c.data or "").startswith("game_end:"), state="*")
    except Exception:
        logging.exception("result/history authority install failed")

    async def events_command(message: types.Message):
        if message.chat.type != "private" or (message.text or "").strip() not in {"اتفاقات بازی", "/اتفاقات_بازی"}:
            return
        game = _latest_finished(app)
        if not game:
            await message.reply("ℹ️ هنوز بازی اتمام‌یافته‌ای برای نمایش وجود ندارد."); return
        text = _events_text(game)
        if not text:
            await message.reply(f"ℹ️ اتفاقات بازی اخیر (بازی {int(game.get('event_number') or 1)}) ثبت نشده است."); return
        await message.reply(f"📝 <b>اتفاقات بازی {int(game.get('event_number') or 1)}</b>\n\n{html.escape(text)}", parse_mode="HTML")

    async def private_events_panel(message: types.Message):
        if message.chat.type != "private" or (message.text or "").strip() != "ثبت اتفاقات بازی": return
        game = _latest_finished(app)
        if not game:
            await message.reply("ℹ️ هنوز بازی اتمام‌یافته‌ای برای ثبت اتفاقات وجود ندارد."); return
        await message.reply(
            f"📝 <b>پنل ثبت اتفاقات بازی</b>\n\nآخرین بازی اتمام‌یافته: <b>بازی {int(game.get('event_number') or 1)}</b>\n\nمتن اتفاقات فقط برای همین بازی ثبت خواهد شد.",
            parse_mode="HTML", reply_markup=_record_panel(game),
        )

    async def record_events_entry(callback: types.CallbackQuery):
        parts = str(callback.data or "").split(":")
        if len(parts) != 3 or parts[0] != "events_record": return
        if parts[1] == "back":
            await callback.message.delete(); await callback.answer(); return
        game_id, group_id = int(parts[1]), int(parts[2])
        game = app.runtime.state.games.get_finished_game(game_id)
        if not game or int(game.get("group_chat_id") or 0) != group_id:
            await callback.answer("❌ بازی موردنظر پیدا نشد.", show_alert=True); return
        uid = int(callback.from_user.id)
        if uid != int(game.get("moderator_id") or 0):
            try:
                if (await app.bot.get_chat_member(group_id, uid)).status not in {"creator", "administrator"}: raise PermissionError
            except Exception:
                await callback.answer("⛔ فقط گرداننده یا مدیر گروه می‌تواند اتفاقات را ثبت کند.", show_alert=True); return
        await callback.message.edit_text(
            f"📝 <b>ثبت اتفاقات بازی {int(game.get('event_number') or 1)}</b>\n\nمتن کامل اتفاقات بازی را در پیام بعدی ارسال کنید.",
            parse_mode="HTML",
        )
        await RecordEventsState.waiting_for_events.set()
        await callback.bot.dispatcher.storage.set_data(chat=int(callback.from_user.id), user=int(callback.from_user.id), data={"game_id": game_id, "group_id": group_id})
        await callback.answer()

    async def record_events_text(message: types.Message, state: FSMContext):
        data = await state.get_data(); game_id = int(data.get("game_id") or 0); group_id = int(data.get("group_id") or 0)
        if not game_id or not group_id: await state.finish(); return
        game = app.runtime.state.games.get_finished_game(game_id)
        if not game or int(game.get("group_chat_id") or 0) != group_id:
            await state.finish(); await message.reply("❌ بازی موردنظر دیگر در دسترس نیست."); return
        text = (message.text or "").strip()
        if not text: await message.reply("❌ متن اتفاقات نمی‌تواند خالی باشد."); return
        state_data = dict(game.get("state") or {}); events = dict(state_data.get("game_events") or {})
        events.update({"text": text, "recorded": True, "recorded_at": datetime.now(timezone.utc).isoformat(), "recorded_by": int(message.from_user.id), "event_number": int(game.get("event_number") or 1), "game_id": int(game["id"])})
        state_data["game_events"] = events
        app.runtime.state.games.update_game(game["id"], state=state_data)
        await state.finish(); await message.reply(f"✅ اتفاقات بازی شماره {int(game.get('event_number') or 1)} ثبت شد.")

    dp.register_message_handler(events_command, lambda m: m.chat.type == "private" and (m.text or "").strip() in {"اتفاقات بازی", "/اتفاقات_بازی"}, content_types=types.ContentTypes.TEXT, state="*")
    dp.register_message_handler(private_events_panel, lambda m: m.chat.type == "private" and (m.text or "").strip() == "ثبت اتفاقات بازی", content_types=types.ContentTypes.TEXT, state="*")
    dp.register_message_handler(record_events_text, state=RecordEventsState.waiting_for_events, content_types=types.ContentTypes.TEXT)
    dp.register_callback_query_handler(record_events_entry, lambda c: str(c.data or "").startswith("events_record:"), state="*")

    async def attendance_authority(callback: types.CallbackQuery):
        parts = str(callback.data or "").split(":")
        if len(parts) != 3 or parts[0] != "mgmt" or parts[2] != "attendance_ready": return
        gid = int(callback.message.chat.id); uid = int(callback.from_user.id); game = app.runtime.state.active_game(gid)
        if not game:
            await callback.answer("❌ بازی فعالی وجود ندارد.", show_alert=True); return
        rows = app.runtime.state.games.list_players(game["id"])
        player = next((r for r in rows if int(r["player_id"]) == uid), None)
        if not player or player.get("seat") is None or str(player.get("status") or "") in {"removed", "dead", "finished", "kicked"}:
            await callback.answer("⛔ فقط بازیکنان حاضر در بازی می‌توانند اعلام آمادگی کنند.", show_alert=True); return
        state_data = dict(game.get("state") or {}); attendance = dict(state_data.get("attendance") or {})
        active = [r for r in rows if r.get("seat") is not None and str(r.get("status") or "active") not in {"removed", "dead", "finished", "kicked"}]
        for r in active: attendance.setdefault(str(int(r["player_id"])), False)
        attendance[str(uid)] = True; state_data["attendance"] = attendance; state_data["attendance_announced"] = False
        app.runtime.state.games.update_game(game["id"], state=state_data)
        lines = ["🟢 <b>بازیکنان حاضر در لیست</b>", ""]
        for r in sorted(active, key=lambda x: int(x.get("seat") or 999)):
            mark = "🟢" if attendance.get(str(int(r["player_id"])), False) else "⚪️"
            label = r.get("nickname") or r.get("first_name") or r.get("username") or r.get("player_id")
            lines.append(f"{mark} {int(r['seat']):02d}. <a href=\"tg://user?id={int(r['player_id'])}\"><b>{html.escape(str(label))}</b></a>")
        lines.extend(["", "برای اعلام آمادگی، «آماده‌ام» را بزنید."])
        kb = InlineKeyboardMarkup(row_width=1).add(InlineKeyboardButton("آماده‌ام ✅", callback_data=f"mgmt:{int(game['id'])}:attendance_ready"))
        try:
            await app.bot.edit_message_text("\n".join(lines), gid, int(callback.message.message_id), parse_mode="HTML", reply_markup=kb)
        except Exception:
            logging.exception("attendance message edit failed")
        await callback.answer("✅ آمادگی شما ثبت شد.")

    _remove_callbacks(dp, lambda fn: getattr(fn, "__name__", "") == "attendance_ready")
    dp.register_callback_query_handler(attendance_authority, lambda c: str(c.data or "").startswith("mgmt:") and str(c.data or "").endswith(":attendance_ready"), state="*")
    return True
