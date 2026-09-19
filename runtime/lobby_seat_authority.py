"""Canonical persistent lobby surface: seats, attendance and lobby rendering."""
from __future__ import annotations

import html
import logging
from typing import Any

from aiogram.dispatcher.handler import CancelHandler
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from repositories.scenario_repository import ScenarioRepository


def install(app: Any) -> bool:
    if getattr(app, "_lobby_seat_authority", False):
        return False
    app._lobby_seat_authority = True
    dp = app.dp
    scenarios = ScenarioRepository()
    cr = getattr(getattr(dp, "callback_query_handlers", None), "handlers", [])

    def game(gid: int):
        # get_game deliberately bypasses active-game cache so seat/ready changes
        # are always rendered from the latest database state.
        active = app.runtime.state.active_game(int(gid))
        if not active:
            return None
        return app.runtime.state.games.get_game(active["id"])

    def rows(g):
        return app.runtime.state.games.list_players(g["id"]) if g else []

    def scenario(g):
        try:
            return scenarios.get_by_id(int(g["scenario_id"])) if g and g.get("scenario_id") else None
        except Exception:
            return None

    def name(row):
        return str(row.get("nickname") or row.get("first_name") or row.get("username") or row.get("player_id") or "👤")

    def mention(row):
        uid = int(row["player_id"])
        return f'<a href="tg://user?id={uid}"><b>{html.escape(name(row))}</b></a>'

    def active_rows(g):
        return sorted(
            [r for r in rows(g) if r.get("seat") is not None and str(r.get("status") or "active") not in {"removed", "dead", "finished", "kicked"}],
            key=lambda r: int(r.get("seat") or 999),
        )

    def waiting_rows(g):
        return [r for r in rows(g) if r.get("seat") is None and str(r.get("status") or "waiting") == "waiting"]

    async def render(callback):
        gid = int(callback.message.chat.id)
        g = game(gid)
        if not g or str(g.get("status") or "") != "lobby":
            await callback.answer("ℹ️ لابی فعالی وجود ندارد.", show_alert=True)
            return False
        r = scenario(g); active = active_rows(g); waiting = waiting_rows(g)
        cap = len((r or {}).get("roles") or [])
        occupied = {int(x["seat"]): x for x in active}
        lines = [
            "༄", "    <b>Mafia Nights</b>", "",
            f"📝 <b>سناریو:</b> {html.escape(str((r or {}).get('name') or '---'))}",
            f"🎩 <b>گرداننده:</b> {html.escape(str(g.get('moderator_name') or '---')) if g.get('moderator_name') else '---'}",
            f"👥 <b>بازیکنان:</b> {len(active)}/{cap}", "",
            "◤◢◣◥◤◢◣◥◤◢◣◥", "        <b>لیست صندلی‌ها</b>", "◤◢◣◥◤◢◣◥◤◢◣◥",
        ]
        for seat in range(1, cap + 1):
            row = occupied.get(seat)
            lines.append(f"{seat:02d}. {mention(row) if row else '⬜ آزاد'}")
        if waiting:
            lines += ["", "🎟 <b>لیست رزرو</b>"] + [f"{i}. {mention(p)}" for i, p in enumerate(waiting, 1)]
        lines += ["", "◤◢◣◥◤◢◣◥◤◢◣◥", "༄"]
        kb = InlineKeyboardMarkup(row_width=3)
        for seat in range(1, cap + 1):
            row = occupied.get(seat)
            kb.insert(InlineKeyboardButton(f"{seat:02d} {'🔒' if row else '🪑'}", callback_data=f"lobby:{int(g['id'])}:seat:{seat}"))
        kb.row(InlineKeyboardButton("🔄 ورود / خروج", callback_data="fl_toggle"))
        if len(active) >= cap > 0:
            kb.row(InlineKeyboardButton("🎟 رزرو / لغو رزرو", callback_data="fl_reserve"))
            kb.row(InlineKeyboardButton("🎭 پخش نقش", callback_data="distribute_roles"))
        kb.row(InlineKeyboardButton("📝 تغییر سناریو", callback_data="fl_scenario"), InlineKeyboardButton("⚙️ مدیریت بازی", callback_data="fl_manage"))
        kb.row(InlineKeyboardButton("⭐ امکانات ویژه", callback_data="fl_special"), InlineKeyboardButton("🚫 لغو بازی", callback_data="fl_cancel"))
        try:
            await callback.message.edit_text("\n".join(lines), parse_mode="HTML", reply_markup=kb)
        except Exception:
            logging.exception("canonical lobby render failed game=%s", g.get("id"))
            await callback.answer("❌ بروزرسانی لابی انجام نشد.", show_alert=True)
            return False
        app.lobby_message_id = callback.message.message_id
        state = dict(g.get("state") or {})
        state["lobby_message_id"] = int(callback.message.message_id)
        app.runtime.state.games.update_game(g["id"], state=state)
        return True

    async def seat(callback):
        parts = str(callback.data or "").split(":")
        if len(parts) != 4 or parts[0] != "lobby" or parts[2] != "seat":
            return
        gid = int(callback.message.chat.id); uid = int(callback.from_user.id); desired = int(parts[3])
        g = game(gid); r = scenario(g)
        if not g or str(g.get("status") or "") != "lobby" or not r:
            await callback.answer("❌ لابی فعال نیست.", show_alert=True); raise CancelHandler()
        cap = len(r.get("roles") or [])
        if desired < 1 or desired > cap:
            await callback.answer("❌ صندلی نامعتبر است.", show_alert=True); raise CancelHandler()
        all_rows = rows(g)
        occupied = next((p for p in all_rows if p.get("seat") is not None and int(p.get("seat")) == desired and int(p.get("player_id")) != uid and str(p.get("status") or "active") not in {"removed", "dead", "finished", "kicked"}), None)
        if occupied:
            await callback.answer("صندلی مورد نظر پر شده", show_alert=True); raise CancelHandler()
        current = next((p for p in all_rows if int(p.get("player_id")) == uid), None)
        if current and current.get("seat") is not None and int(current["seat"]) == desired:
            await callback.answer("شما روی همین صندلی هستید.", show_alert=True); raise CancelHandler()
        try:
            if current and current.get("seat") is None:
                app.runtime.state.games.set_player_seat(g["id"], uid, desired)
            elif current:
                app.runtime.state.games.set_player_seat(g["id"], uid, desired)
            else:
                app.runtime.state.lobby.join(g["id"], uid, desired)
        except ValueError:
            await callback.answer("صندلی مورد نظر پر شده", show_alert=True); raise CancelHandler()
        await render(callback)
        await callback.answer(f"💺 صندلی {desired} برای شما ثبت شد.")
        raise CancelHandler()

    async def toggle(callback):
        gid = int(callback.message.chat.id); uid = int(callback.from_user.id); g = game(gid); r = scenario(g)
        if not g or str(g.get("status") or "") != "lobby" or not r:
            await callback.answer("❌ لابی فعال نیست.", show_alert=True); raise CancelHandler()
        all_rows = rows(g)
        current = next((p for p in all_rows if int(p.get("player_id")) == uid), None)
        if current:
            if current.get("seat") is not None:
                freed = int(current["seat"])
                app.runtime.state.games.remove_player(g["id"], uid)
                promoted = app.runtime.state.lobby.promote_waiting(g["id"], freed)
                await render(callback)
                if promoted:
                    await callback.answer(f"🚪 از بازی خارج شدید؛ جای شما به {name(next((p for p in rows(g) if int(p['player_id']) == int(promoted['player_id'])), {'player_id': promoted['player_id'] }))} واگذار شد.")
                else:
                    await callback.answer("🚪 از بازی خارج شدید.")
                raise CancelHandler()
            if str(current.get("status") or "") == "waiting":
                app.runtime.state.games.remove_player(g["id"], uid)
                await render(callback); await callback.answer("🎟 از لیست رزرو خارج شدید."); raise CancelHandler()
        active = active_rows(g); cap = len(r.get("roles") or [])
        if len(active) >= cap:
            await callback.answer("🎟 ظرفیت اصلی تکمیل است؛ از «رزرو / لغو رزرو» استفاده کنید.", show_alert=True); raise CancelHandler()
        occupied_seats = {int(p["seat"]) for p in active}
        desired = next((s for s in range(1, cap + 1) if s not in occupied_seats), None)
        if desired is None:
            await callback.answer("❌ صندلی خالی وجود ندارد.", show_alert=True); raise CancelHandler()
        app.runtime.state.lobby.join(g["id"], uid, desired)
        await render(callback); await callback.answer(f"✅ وارد بازی شدید؛ صندلی {desired} برای شما ثبت شد."); raise CancelHandler()

    async def attendance(callback):
        gid = int(callback.message.chat.id); g = game(gid)
        active = active_rows(g) if g else []
        if not active:
            await callback.answer("👥 بازیکنی در بازی نیست.", show_alert=True); raise CancelHandler()
        state = dict(g.get("state") or {})
        ready = {int(x) for x in (state.get("ready_players") or []) if str(x).lstrip("-").isdigit()}
        lines = ["📢 <b>تگ لیست / حاضری</b>", ""]
        for p in active:
            lines.append(f"{'🟢' if int(p['player_id']) in ready else '⚪️'} {int(p['seat']):02d}. {mention(p)}")
        kb = InlineKeyboardMarkup(row_width=1).add(InlineKeyboardButton("🙋‍♂️ آماده‌ام", callback_data="fl_ready"), InlineKeyboardButton("⬅️ بازگشت به لابی", callback_data="fl_back"))
        await callback.message.edit_text("\n".join(lines), parse_mode="HTML", reply_markup=kb)
        await callback.answer()
        raise CancelHandler()

    async def ready(callback):
        gid = int(callback.message.chat.id); uid = int(callback.from_user.id); g = game(gid)
        active = active_rows(g) if g else []
        if not g or not any(int(p["player_id"]) == uid for p in active):
            await callback.answer("⛔ فقط بازیکنان داخل بازی می‌توانند آماده شوند.", show_alert=True); raise CancelHandler()
        current = dict(g.get("state") or {})
        ready = {int(x) for x in (current.get("ready_players") or []) if str(x).lstrip("-").isdigit()}
        ready.add(uid); current["ready_players"] = sorted(ready)
        if not app.runtime.state.games.update_game(g["id"], state=current):
            await callback.answer("❌ ثبت آمادگی انجام نشد.", show_alert=True); raise CancelHandler()
        fresh = app.runtime.state.games.get_game(g["id"])
        active = active_rows(fresh)
        lines = ["📢 <b>تگ لیست / حاضری</b>", ""] + [f"{'🟢' if int(p['player_id']) in ready else '⚪️'} {int(p['seat']):02d}. {mention(p)}" for p in active]
        kb = InlineKeyboardMarkup(row_width=1).add(InlineKeyboardButton("🙋‍♂️ آماده‌ام", callback_data="fl_ready"), InlineKeyboardButton("⬅️ بازگشت به لابی", callback_data="fl_back"))
        await callback.message.edit_text("\n".join(lines), parse_mode="HTML", reply_markup=kb)
        await callback.answer("✅ آماده‌ام ثبت شد")
        raise CancelHandler()

    async def back(callback):
        await render(callback)
        await callback.answer("⬅️ به لابی برگشتید.")

    async def attendance_text(message):
        g = game(int(message.chat.id))
        if not g or str(g.get("status") or "") != "lobby":
            await message.reply("ℹ️ لابی فعالی وجود ندارد."); return
        active = active_rows(g)
        state = dict(g.get("state") or {}); ready = {int(x) for x in (state.get("ready_players") or []) if str(x).lstrip("-").isdigit()}
        lines = ["📢 <b>تگ لیست / حاضری</b>", ""] + [f"{'🟢' if int(p['player_id']) in ready else '⚪️'} {int(p['seat']):02d}. {mention(p)}" for p in active]
        await message.reply("\n".join(lines), parse_mode="HTML", reply_markup=InlineKeyboardMarkup(row_width=1).add(InlineKeyboardButton("🙋‍♂️ آماده‌ام", callback_data="fl_ready"), InlineKeyboardButton("⬅️ بازگشت به لابی", callback_data="fl_back")))

    async def lobby_text(message):
        g = game(int(message.chat.id))
        if not g or str(g.get("status") or "") != "lobby":
            await message.reply("ℹ️ بازی شروع شده یا لابی فعالی وجود ندارد."); return
        active = active_rows(g); r = scenario(g); cap = len((r or {}).get("roles") or [])
        occupied = {int(p["seat"]): p for p in active}; waiting = waiting_rows(g)
        lines = ["🏠 <b>لابی فعال</b>", f"🎭 سناریو: <b>{html.escape(str((r or {}).get('name') or '---'))}</b>", f"👥 بازیکنان: <b>{len(active)}/{cap}</b>", "", "🪑 <b>لیست صندلی‌ها</b>"]
        lines += [f"{s:02d}. {mention(occupied[s]) if s in occupied else '⬜ آزاد'}" for s in range(1, cap + 1)]
        if waiting: lines += ["", "🎟 <b>لیست رزرو</b>"] + [f"{i}. {mention(p)}" for i,p in enumerate(waiting,1)]
        await message.reply("\n".join(lines), parse_mode="HTML", reply_markup=InlineKeyboardMarkup(row_width=3).add(*[InlineKeyboardButton(f"{s:02d} {'🔒' if s in occupied else '🪑'}", callback_data=f"lobby:{int(g['id'])}:seat:{s}") for s in range(1, cap+1)]))

    # Register authoritative handlers, then put them ahead of every legacy lobby
    # callback. We intentionally use callback field because aiogram Handler stores
    # the executable callback there in the deployed runtime.
    dp.register_callback_query_handler(seat, lambda c: str(c.data or "").startswith("lobby:") and ":seat:" in str(c.data or ""), state="*")
    dp.register_callback_query_handler(toggle, lambda c: str(c.data or "") == "fl_toggle", state="*")
    dp.register_callback_query_handler(attendance, lambda c: str(c.data or "") == "fl_attendance", state="*")
    dp.register_callback_query_handler(ready, lambda c: str(c.data or "") == "fl_ready", state="*")
    dp.register_callback_query_handler(back, lambda c: str(c.data or "") == "fl_back", state="*")
    registry = getattr(getattr(dp, "callback_query_handlers", None), "handlers", [])
    for item in reversed(registry):
        fn = getattr(item, "callback", None) or getattr(item, "handler", None)
        if fn in {seat, toggle, attendance, ready, back}:
            try: registry.remove(item); registry.insert(0, item)
            except ValueError: pass

    dp.register_message_handler(attendance_text, lambda m: (m.text or "").strip().replace("‌", " ").casefold() in {"حاضری"}, content_types="text", state="*")
    dp.register_message_handler(lobby_text, lambda m: (m.text or "").strip().replace("‌", " ").casefold() in {"لابی"}, content_types="text", state="*")
    dp.register_message_handler(
        lambda m: None,
        lambda m: False,
        content_types="text", state="*"
    )
    app._render_lobby_authority = render
    app._render_attendance_authority = attendance_text
    logging.info("CANONICAL LOBBY SEAT AUTHORITY active: seats=restored auto-assign=on move=on occupied-alert=on reserve-promotion=on attendance=fresh")
    return True
