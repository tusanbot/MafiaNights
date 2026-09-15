"""Final private-panel recovery router.

Owns the high-conflict private navigation callbacks that were historically
split across main1 and several patch generations. It also clears stale FSM
state when the user navigates away from a form.
"""
from __future__ import annotations

import html
import logging
from aiogram.dispatcher.handler import CancelHandler
from aiogram.dispatcher import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.exceptions import MessageNotModified


def _private(c):
    return bool(c.message and c.message.chat.type == "private")


def _gid(app):
    for k in ("ALLOWED_GROUP_ID", "GROUP_ID", "group_chat_id", "group_id"):
        v = getattr(app, k, None)
        if v:
            try: return int(v)
            except Exception: pass
    return None


async def _allowed(app, c):
    if not _private(c):
        raise CancelHandler()
    uid = int(c.from_user.id)
    if uid == int(getattr(app, "moderator_id", 0) or 0): return True
    cached = set()
    for obj in (app, getattr(app, "addons", None)):
        for attr in ("admins", "group_admins"):
            for x in getattr(obj, attr, None) or []:
                try: cached.add(int(getattr(getattr(x, "user", None), "id", x)))
                except Exception: pass
    if uid in cached: return True
    gid = _gid(app)
    if gid:
        try:
            admins = await app.bot.get_chat_administrators(gid)
            ids = {int(a.user.id) for a in admins}
            app.admins = ids; app.group_admins = list(ids)
            if uid in ids: return True
        except Exception: logging.exception("private recovery admin lookup failed")
    await c.answer("⛔ فقط گرداننده یا مدیر گروه دسترسی دارد.", show_alert=True)
    raise CancelHandler()


async def _finish(state):
    try: await state.finish()
    except Exception: pass


def _name(app, uid):
    try: return str(app.display_name(uid, (getattr(app, "players", {}) or {}).get(uid)))
    except Exception: pass
    v = (getattr(app, "players", {}) or {}).get(uid)
    if isinstance(v, dict): v = v.get("nickname") or v.get("full_name") or v.get("first_name")
    return str(v or f"بازیکن {uid}")


def _menu_kb():
    from runtime.final_private_ui import management_keyboard
    return management_keyboard()


async def install(app):
    dp = app.dp
    cq = getattr(getattr(dp, "callback_query_handlers", None), "handlers", None)
    if cq is None or getattr(app, "_private_ui_recovery_v3", False): return False

    async def back(c, state: FSMContext):
        await _allowed(app, c); await _finish(state)
        from runtime.final_private_ui import management_report
        try: await c.message.edit_text(management_report(app), reply_markup=_menu_kb(), parse_mode="HTML")
        except MessageNotModified: pass
        await c.answer(); raise CancelHandler()

    async def start(c, state: FSMContext):
        if not _private(c): raise CancelHandler()
        await _finish(state)
        from runtime.final_private_ui import start_keyboard
        try: await c.message.edit_text("🎭 <b>Mafia Nights</b>\n\nیک گزینه را انتخاب کنید:", reply_markup=start_keyboard(), parse_mode="HTML")
        except MessageNotModified: pass
        await c.answer(); raise CancelHandler()

    async def scenarios(c, state: FSMContext):
        await _allowed(app, c); await _finish(state)
        from runtime.final_private_ui import scenario_keyboard
        await c.message.edit_text("⚙️ <b>مدیریت سناریو</b>\n\nاز گزینه‌های زیر استفاده کنید:", reply_markup=scenario_keyboard(), parse_mode="HTML")
        await c.answer(); raise CancelHandler()

    async def help_(c, state: FSMContext):
        await _allowed(app, c); await _finish(state)
        text = "📚 راهنمای Mafia Nights\n\n"
        try:
            with open("help.txt", "r", encoding="utf-8") as f: text = f.read()
        except Exception: pass
        kb = InlineKeyboardMarkup().add(InlineKeyboardButton("⬅️ بازگشت", callback_data="final:start"))
        await c.message.edit_text(text, reply_markup=kb); await c.answer(); raise CancelHandler()

    async def profile(c, state: FSMContext):
        if not _private(c): raise CancelHandler()
        await _finish(state)
        try:
            enhancement = getattr(app, "profile_enhancements", None)
            if enhancement is not None:
                await enhancement.profile(c)
            else:
                raise RuntimeError("profile enhancement unavailable")
        except Exception:
            logging.exception("private recovery profile failed; using fallback")
            uid = int(c.from_user.id)
            kb = InlineKeyboardMarkup(row_width=2).add(
                InlineKeyboardButton("⚙️ تنظیمات پروفایل", callback_data="profile:settings"),
                InlineKeyboardButton("⬅️ پنل اصلی", callback_data="up:menu"),
            )
            await c.message.edit_text(
                "👤 <b>پروفایل من</b>\n\n"
                f"نام: <b>{html.escape(c.from_user.full_name or '❓')}</b>\n"
                f"نام کاربری: @{html.escape(c.from_user.username) if c.from_user.username else '—'}\n"
                f"شناسه عددی: <code>{uid}</code>\n\n"
                "⚠️ اطلاعات تکمیلی پروفایل فعلاً در دسترس نیست.",
                reply_markup=kb, parse_mode="HTML")
            await c.answer()
        raise CancelHandler()

    async def birthday(c, state: FSMContext):
        await _allowed(app, c); await _finish(state)
        gid = _gid(app); removed = (getattr(app, "removed_players", {}) or {}).get(gid, {})
        kb = InlineKeyboardMarkup(row_width=1)
        for seat, info in sorted(removed.items()):
            kb.add(InlineKeyboardButton(f"🎂 {seat}. {info.get('name','❓')}", callback_data=f"recovery:revive:{seat}"))
        kb.add(InlineKeyboardButton("⬅️ مدیریت بازی", callback_data="finalgm:back"))
        text = "🎂 <b>تولد بازیکن</b>\n\n" + ("بازیکن خارج‌شده‌ای برای بازگرداندن وجود ندارد." if not removed else "بازیکن را انتخاب کنید:")
        await c.message.edit_text(text, reply_markup=kb, parse_mode="HTML"); await c.answer(); raise CancelHandler()

    async def revive(c, state: FSMContext):
        await _allowed(app, c); await _finish(state)
        gid = _gid(app)
        try: seat = int(c.data.rsplit(":",1)[1])
        except Exception: await c.answer("⚠️ صندلی نامعتبر است.", show_alert=True); raise CancelHandler()
        bucket = (getattr(app, "removed_players", {}) or {}).get(gid, {})
        info = bucket.pop(seat, None)
        if not info: await c.answer("⚠️ بازیکن پیدا نشد.", show_alert=True); raise CancelHandler()
        uid = int(info["id"]); app.player_slots[seat] = uid
        if isinstance(getattr(app, "players", None), dict): app.players[uid] = info.get("name", "❓")
        await c.answer("✅ بازیکن بازگردانده شد.")
        await back(c, state)

    async def moderator(c, state: FSMContext):
        await _allowed(app, c); await _finish(state)
        gid = _gid(app); kb = InlineKeyboardMarkup(row_width=2)
        try: admins = await app.bot.get_chat_administrators(gid) if gid else []
        except Exception: admins = []
        for a in admins:
            kb.insert(InlineKeyboardButton(a.user.full_name, callback_data=f"recovery:moderator:{a.user.id}"))
        kb.add(InlineKeyboardButton("⬅️ مدیریت بازی", callback_data="finalgm:back"))
        await c.message.edit_text("🎩 <b>تغییر گرداننده</b>\n\nگرداننده جدید را انتخاب کنید:", reply_markup=kb, parse_mode="HTML"); await c.answer(); raise CancelHandler()

    async def set_moderator(c, state: FSMContext):
        await _allowed(app, c); await _finish(state)
        gid = _gid(app); uid = int(c.data.rsplit(":",1)[1])
        app.moderator_id = uid
        try:
            game = app.runtime.state.active_game(gid) if gid else None
            if game: app.runtime.state.games.update_game(game["id"], moderator_id=uid)
        except Exception: logging.exception("moderator persistence failed")
        await c.answer("✅ گرداننده تغییر کرد.")
        await back(c, state)

    async def replace(c, state: FSMContext):
        await _allowed(app, c); await _finish(state)
        gid = _gid(app); subs = (getattr(app, "substitute_list", {}) or {}).get(gid, {})
        kb = InlineKeyboardMarkup(row_width=1)
        for uid, info in subs.items(): kb.add(InlineKeyboardButton(f"🔄 {info.get('name','❓')}", callback_data=f"recovery:sub:{uid}"))
        kb.add(InlineKeyboardButton("⬅️ مدیریت بازی", callback_data="finalgm:back"))
        await c.message.edit_text("🔄 <b>جایگزین بازیکن</b>\n\nجایگزین را انتخاب کنید:", reply_markup=kb); await c.answer(); raise CancelHandler()

    async def choose_sub(c, state: FSMContext):
        await _allowed(app, c); await _finish(state)
        gid = _gid(app); uid = int(c.data.rsplit(":",1)[1]); slots = getattr(app, "player_slots", {}) or {}
        kb = InlineKeyboardMarkup(row_width=1)
        for seat, old in sorted(slots.items()): kb.add(InlineKeyboardButton(f"{seat}. {_name(app, old)}", callback_data=f"recovery:replace:{uid}:{seat}"))
        kb.add(InlineKeyboardButton("⬅️ جایگزین‌ها", callback_data="finalgm:replace"))
        await c.message.edit_text("👤 بازیکنی که باید جایگزین شود را انتخاب کنید:", reply_markup=kb); await c.answer(); raise CancelHandler()

    async def do_replace(c, state: FSMContext):
        await _allowed(app, c); await _finish(state)
        try: _,_,_,uid_s,seat_s = c.data.split(":")
        except Exception: await c.answer("⚠️ اطلاعات نامعتبر است.", show_alert=True); raise CancelHandler()
        uid, seat = int(uid_s), int(seat_s); slots = getattr(app, "player_slots", {}) or {}; old = slots.get(seat)
        if old is None: await c.answer("⚠️ بازیکن پیدا نشد.", show_alert=True); raise CancelHandler()
        subs = (getattr(app, "substitute_list", {}) or {}).get(_gid(app), {}); info = subs.pop(uid, None)
        if not info: await c.answer("⚠️ جایگزین پیدا نشد.", show_alert=True); raise CancelHandler()
        slots[seat] = uid
        role_map = getattr(app, "last_role_map", {}) or {}
        if old in role_map: role_map[uid] = role_map.pop(old)
        await c.answer("✅ جایگزینی انجام شد.")
        await back(c, state)

    regs = [
        (back, lambda c: c.data == "finalgm:back"),
        (start, lambda c: c.data in {"final:start", "private:start"}),
        (scenarios, lambda c: c.data == "final:scenarios"),
        (help_, lambda c: c.data in {"final:help", "help"}),
        (profile, lambda c: c.data in {"up:menu", "up:profile"}),
        (birthday, lambda c: c.data == "finalgm:birthday"),
        (revive, lambda c: c.data.startswith("recovery:revive:")),
        (moderator, lambda c: c.data == "finalgm:moderator"),
        (set_moderator, lambda c: c.data.startswith("recovery:moderator:")),
        (replace, lambda c: c.data == "finalgm:replace"),
        (choose_sub, lambda c: c.data.startswith("recovery:sub:")),
        (do_replace, lambda c: c.data.startswith("recovery:replace:")),
    ]
    for fn, filt in regs:
        dp.register_callback_query_handler(fn, filt, state="*")

    current = list(cq)
    owned = [h for h in current if getattr(getattr(h, "handler", None), "__self__", None) is None and getattr(getattr(h, "handler", None), "__name__", "") in {"back","start","scenarios","help_","profile","birthday","revive","moderator","set_moderator","replace","choose_sub","do_replace"}]
    # The newly registered handlers are the last entries; promote by exact callback filters
    # using handler function identity captured above.
    wanted = {fn for fn,_ in regs}
    matches = [h for h in list(cq) if getattr(h, "handler", None) in wanted]
    cq[:] = matches + [h for h in list(cq) if h not in matches]
    app._private_ui_recovery_v3 = True
    logging.info("PRIVATE UI RECOVERY V3 ACTIVE")
    return True
