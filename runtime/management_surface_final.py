from __future__ import annotations

import html
import logging
from typing import Any

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def _handler(item: Any) -> Any:
    return getattr(item, "handler", None) or getattr(item, "callback", None)


def _registry(dp: Any):
    return getattr(getattr(dp, "callback_query_handlers", None), "handlers", [])


def _front(registry: Any, fn: Any) -> None:
    for i, item in enumerate(list(registry)):
        if _handler(item) is fn:
            registry.insert(0, registry.pop(i))
            return


def _action(data: Any) -> str | None:
    parts = str(data or "").split(":")
    return parts[2] if len(parts) >= 3 and parts[0] == "mgmt" else None


def install(app: Any) -> bool:
    if getattr(app, "_management_surface_final", False):
        return False
    management = getattr(app, "game_management", None)
    if management is None:
        logging.warning("FINAL MANAGEMENT: game_management unavailable")
        return False

    dp = app.dp
    reg = _registry(dp)
    app._management_surface_final = True

    def panel(game_id: int):
        items = [
            ("🔢 شماره بازی", "event"), ("📝 تغییر سناریو", "scenario"), ("🗑 حذف بازیکن", "remove"),
            ("🎟 لغو رزرو", "unreserve"), ("🔄 جایگزین بازیکن", "replace"), ("✅ حاضری", "attendance"),
            ("🎂 تولد بازیکن", "birthday"), ("⚔ وضعیت چالش", "challenge"), ("⏭ مدیریت نکست", "next"),
            ("🚫 لغو بازی", "cancel"), ("ℹ️ اطلاعات بازی", "info"), ("🦵 کیک از بازی", "kick"),
            ("⚠️ تذکر به بازیکن", "warning"), ("➕ ترن اضافه", "extra"), ("🔇 سکوت بازیکن", "mute"),
            ("🔊 حذف سکوت", "unmute"), ("⬅️ بازگشت به لابی", "back_lobby"),
        ]
        kb = InlineKeyboardMarkup(row_width=3)
        for i in range(0, len(items), 3):
            kb.row(*(InlineKeyboardButton(text, callback_data=f"mgmt:{int(game_id)}:{action}") for text, action in items[i:i + 3]))
        return kb

    management.panel = panel

    async def info(callback):
        gid = int(callback.message.chat.id); game = management._game(gid)
        if not game or not await management._allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید یا بازی فعال نیست.", show_alert=True); return
        rows = management._rows(game); state = management._state(game)
        scenario = str(state.get("scenario_name") or game.get("scenario") or game.get("scenario_id") or "---")
        moderator = str(state.get("moderator_name") or game.get("moderator_name") or game.get("moderator_id") or "---")
        event_number = game.get("event_number"); event_text = "---" if event_number is None else str(event_number)
        await callback.message.edit_text(
            f"ℹ️ <b>اطلاعات بازی {html.escape(event_text)}</b>\n\n"
            f"📌 وضعیت: <b>{html.escape(str(game.get('status') or '---'))}</b>\n"
            f"🎭 سناریو: <b>{html.escape(scenario)}</b>\n"
            f"👥 بازیکنان: <b>{sum(1 for r in rows if r.get('seat') is not None)}</b>\n"
            f"🎩 گرداننده: <b>{html.escape(moderator)}</b>\n"
            f"🌙 روز: <b>{int(game.get('current_day') or 0)}</b>\n"
            f"🔄 دور: <b>{int(game.get('current_round') or 0)}</b>",
            parse_mode="HTML", reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("⬅️ مدیریت بازی", callback_data=f"mgmt:{int(game['id'])}:open")),
        ); await callback.answer()

    async def pick_player(callback, action: str, title: str):
        gid = int(callback.message.chat.id); game = management._game(gid)
        if not game or not await management._allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید یا بازی فعال نیست.", show_alert=True); return
        rows = [r for r in management._rows(game) if r.get("seat") is not None and str(r.get("status") or "") not in {"removed", "dead", "finished", "kicked"}]
        if action == "unmute":
            muted = set(int(x) for x in (getattr(app, "_gm_muted_next_round", set()) or set())) | set(int(x) for x in (getattr(app, "_gm_muted_active", set()) or set()))
            rows = [r for r in rows if int(r.get("seat")) in muted]
        kb = InlineKeyboardMarkup(row_width=2)
        for row in rows:
            seat = int(row.get("seat") or 0); uid = int(row["player_id"])
            kb.insert(InlineKeyboardButton(f"{seat:02d}. {management._name(row)}", callback_data=f"mgmt:{int(game['id'])}:{action}_pick:{uid}"))
        kb.row(InlineKeyboardButton("⬅️ مدیریت", callback_data=f"mgmt:{int(game['id'])}:open"))
        await callback.message.edit_text(title, parse_mode="HTML", reply_markup=kb); await callback.answer()

    async def kick(callback): await pick_player(callback, "kick", "🦵 <b>کیک از بازی</b>\n\nبازیکن موردنظر را انتخاب کنید:")

    async def kick_pick(callback):
        p = str(callback.data or "").split(":");
        if len(p) != 4: return
        gid = int(callback.message.chat.id); uid = int(p[3]); game = management._game(gid)
        if not game or not await management._allowed(callback, gid, game): await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        row = next((r for r in management._rows(game) if int(r["player_id"]) == uid), None)
        if not row: await callback.answer("❌ بازیکن پیدا نشد.", show_alert=True); return
        games = app.runtime.state.games; games.set_player_seat(game["id"], uid, None); games.set_player_status(game["id"], uid, "kicked")
        alive = getattr(games, "set_player_alive", None)
        if alive: alive(game["id"], uid, False)
        state = management._state(game); kicks = dict(state.get("kicks") or {}); kicks[str(uid)] = int(kicks.get(str(uid), 0)) + 1; management._save(game, kicks=kicks)
        await callback.message.edit_text(f"🦵 <b>{html.escape(management._name(row))}</b> از بازی کیک شد.\n📉 جریمه کیک در پایان بازی ثبت می‌شود.", parse_mode="HTML", reply_markup=management.panel(game["id"])); await callback.answer("🦵 بازیکن کیک شد.")

    async def warning(callback): await pick_player(callback, "warning", "⚠️ <b>تذکر به بازیکن</b>\n\nبازیکنی را انتخاب کنید:")

    async def warning_pick(callback):
        p = str(callback.data or "").split(":");
        if len(p) != 4: return
        gid = int(callback.message.chat.id); uid = int(p[3]); game = management._game(gid)
        if not game or not await management._allowed(callback, gid, game): await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        row = next((r for r in management._rows(game) if int(r["player_id"]) == uid), None)
        if not row: await callback.answer("❌ بازیکن پیدا نشد.", show_alert=True); return
        state = management._state(game); warnings = dict(state.get("warnings") or {}); count = int(warnings.get(str(uid), 0)) + 1; warnings[str(uid)] = count; management._save(game, warnings=warnings)
        await callback.message.edit_text(f"⚠️ <b>تذکر ثبت شد.</b>\n\n{html.escape(management._name(row))}\n🔢 تعداد تذکر: <b>{count}</b>\n📉 جریمه این تذکر: <b>-{min(count,5)}</b>", parse_mode="HTML", reply_markup=management.panel(game["id"])); await callback.answer("⚠️ تذکر ثبت شد.")

    async def extra(callback): await pick_player(callback, "extra", "➕ <b>ترن اضافه</b>\n\nبازیکنی را انتخاب کنید:")

    async def extra_pick(callback):
        p = str(callback.data or "").split(":");
        if len(p) != 4: return
        gid = int(callback.message.chat.id); uid = int(p[3]); game = management._game(gid)
        if not game or not await management._allowed(callback, gid, game): await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        row = next((r for r in management._rows(game) if int(r["player_id"]) == uid), None)
        if not row: await callback.answer("❌ بازیکن پیدا نشد.", show_alert=True); return
        seat = int(row["seat"]); current = getattr(app, "_gm_extra_next_round", None)
        if not isinstance(current, set): current = set(current or []); app._gm_extra_next_round = current
        current.add(seat); management._save(game, extra_turn_seats=sorted(int(x) for x in current))
        await callback.message.edit_text(f"➕ <b>ترن اضافه ثبت شد.</b>\n\n{html.escape(management._name(row))} — صندلی {seat:02d}\nدر انتهای نوبت‌های عادی اجرا می‌شود.", parse_mode="HTML", reply_markup=management.panel(game["id"])); await callback.answer("➕ ترن اضافه ثبت شد.")

    async def mute(callback): await pick_player(callback, "mute", "🔇 <b>سکوت بازیکن</b>\n\nبازیکنی را انتخاب کنید:")

    async def mute_pick(callback):
        p = str(callback.data or "").split(":");
        if len(p) != 4: return
        gid = int(callback.message.chat.id); uid = int(p[3]); game = management._game(gid)
        if not game or not await management._allowed(callback, gid, game): await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        row = next((r for r in management._rows(game) if int(r["player_id"]) == uid), None)
        if not row: await callback.answer("❌ بازیکن پیدا نشد.", show_alert=True); return
        seat = int(row["seat"]); muted = getattr(app, "_gm_muted_next_round", None)
        if not isinstance(muted, set): muted = set(muted or []); app._gm_muted_next_round = muted
        muted.add(seat); management._save(game, muted_next_round_seats=sorted(int(x) for x in muted))
        await callback.message.edit_text(f"🔇 <b>سکوت ثبت شد.</b>\n\n{html.escape(management._name(row))} — صندلی {seat:02d}\nدر دور بعدی اعمال می‌شود.", parse_mode="HTML", reply_markup=management.panel(game["id"])); await callback.answer("🔇 سکوت ثبت شد.")

    async def unmute(callback): await pick_player(callback, "unmute", "🔊 <b>حذف سکوت</b>\n\nبازیکن موردنظر را انتخاب کنید:")

    async def unmute_pick(callback):
        p = str(callback.data or "").split(":");
        if len(p) != 4: return
        gid = int(callback.message.chat.id); uid = int(p[3]); game = management._game(gid)
        if not game or not await management._allowed(callback, gid, game): await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        row = next((r for r in management._rows(game) if int(r["player_id"]) == uid), None); seat = int(row["seat"]) if row and row.get("seat") is not None else None
        if seat is None: await callback.answer("❌ بازیکن پیدا نشد.", show_alert=True); return
        for attr in ("_gm_muted_next_round", "_gm_muted_active"):
            value = getattr(app, attr, None)
            if isinstance(value, set): value.discard(seat)
        management._save(game, muted_next_round_seats=sorted(int(x) for x in (getattr(app, "_gm_muted_next_round", set()) or set())))
        await callback.message.edit_text(f"🔊 <b>سکوت {html.escape(management._name(row))} حذف شد.</b>", parse_mode="HTML", reply_markup=management.panel(game["id"])); await callback.answer("🔊 سکوت حذف شد.")

    async def cancel(callback):
        gid = int(callback.message.chat.id); game = management._game(gid)
        if not game or not await management._allowed(callback, gid, game): await callback.answer("⛔ دسترسی ندارید یا بازی فعال نیست.", show_alert=True); return
        i = int(game["id"]); kb = InlineKeyboardMarkup(row_width=2)
        kb.row(InlineKeyboardButton("🚫 بله، لغو شود", callback_data=f"mgmt:{i}:cancel_confirm"), InlineKeyboardButton("⬅️ بازگشت", callback_data=f"mgmt:{i}:cancel_back"))
        await callback.message.edit_text("⚠️ <b>لغو بازی</b>\n\nآیا مطمئن هستید که می‌خواهید این بازی لغو شود؟", parse_mode="HTML", reply_markup=kb); await callback.answer()

    async def cancel_confirm(callback):
        gid = int(callback.message.chat.id); game = management._game(gid)
        if not game or not await management._allowed(callback, gid, game): await callback.answer("⛔ دسترسی ندارید یا بازی فعال نیست.", show_alert=True); return
        await management.cancel(callback)

    async def cancel_back(callback):
        gid = int(callback.message.chat.id); game = management._game(gid)
        if not game or not await management._allowed(callback, gid, game): await callback.answer("⛔ دسترسی ندارید یا بازی فعال نیست.", show_alert=True); return
        await management.open(callback)

    async def back_lobby(callback):
        gid = int(callback.message.chat.id); game = management._game(gid)
        if not game or not await management._allowed(callback, gid, game): await callback.answer("⛔ دسترسی ندارید یا بازی فعال نیست.", show_alert=True); return
        if str(game.get("status") or "") != "lobby": await callback.answer("ℹ️ لابی فقط قبل از شروع بازی قابل نمایش است.", show_alert=True); return
        renderer = getattr(app, "_render_final_lobby", None)
        if not renderer: await callback.answer("❌ رندر لابی در دسترس نیست.", show_alert=True); return
        try:
            await renderer(callback); await callback.answer("⬅️ به لابی برگشتید.")
        except Exception:
            logging.exception("final management back_lobby failed"); await callback.answer("❌ بازگشت به لابی انجام نشد.", show_alert=True)

    handlers = [
        (info, "info"), (kick, "kick"), (kick_pick, "kick_pick"), (warning, "warning"), (warning_pick, "warning_pick"),
        (extra, "extra"), (extra_pick, "extra_pick"), (mute, "mute"), (mute_pick, "mute_pick"),
        (unmute, "unmute"), (unmute_pick, "unmute_pick"), (cancel, "cancel"),
        (cancel_confirm, "cancel_confirm"), (cancel_back, "cancel_back"), (back_lobby, "back_lobby"),
    ]
    for fn, action in handlers:
        dp.register_callback_query_handler(fn, lambda c, a=action: _action(c.data) == a, state="*")
        _front(reg, fn)

    logging.info("FINAL MANAGEMENT SURFACE active: single-owner panel/cancel/navigation")
    return True
