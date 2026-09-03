"""Clean private-only game management controller."""
from __future__ import annotations
import html
import logging
from aiogram.dispatcher.handler import CancelHandler
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def gid(app):
    for k in ("group_chat_id", "ALLOWED_GROUP_ID", "GROUP_ID", "group_id"):
        v = getattr(app, k, None)
        if v:
            try: return int(v)
            except Exception: pass
    return None


def private(c):
    return bool(c.message and c.message.chat.type == "private")


def name(app, uid):
    if not uid: return "—"
    try:
        v = app.display_name(uid, (getattr(app, "players", {}) or {}).get(uid))
        if v and str(v) not in {"?", "❓", "None", "بازیکن"}: return str(v)
    except Exception: pass
    return str((getattr(app, "players", {}) or {}).get(uid, f"بازیکن {uid}"))


def round_started(app):
    return bool(getattr(app, "round_active", False) or getattr(app, "_stable_day_active", False) or getattr(app, "_stable_round_started", False))


def kb(app):
    k = InlineKeyboardMarkup(row_width=1)
    for text, data in [
        ("👥 لیست بازیکنان", "list_players"),
        ("📤 ارسال دوباره نقشها", "resend_roles"),
        ("🗑 حذف بازیکن", "remove_player"),
        ("🎂 تولد بازیکن", "player_birthday"),
        ("🎩 تغییر گرداننده", "pmgm:mod"),
        ("🔄 جایگزین بازیکن", "replace_player"),
        ("🔇 سکوت", "pmgm:mute"),
        ("➕ ترن اضافی", "pmgm:extra"),
        ("⬅️ بازگشت", "back_main"),
    ]: k.add(InlineKeyboardButton(text, callback_data=data))
    return k


def report(app):
    running = getattr(app, "game_running", False) or round_started(app)
    status = "🟢 در حال اجرای بازی" if running else ("🟡 لابی فعال" if getattr(app, "lobby_active", False) else "⚪ آماده")
    return ("🛠 <b>مدیریت بازی</b>\n\n"
            f"📌 وضعیت: <b>{status}</b>\n"
            f"📝 سناریو: <b>{html.escape(str(getattr(app, 'selected_scenario', None) or '—'))}</b>\n"
            f"👥 آمار بازیکنان: <b>{len(getattr(app, 'players', {}) or {})}</b>\n"
            f"💺 صندلی‌ها: <b>{len(getattr(app, 'player_slots', {}) or {})}</b>\n"
            f"🎩 گرداننده: <b>{html.escape(name(app, getattr(app, 'moderator_id', None)))}</b>")


async def install(app):
    # Kept async for compatibility with startup callers that may await it.
    return _install(app)


def _install(app):
    if getattr(app, "_private_game_management_v4", False): return False
    reg = getattr(getattr(app.dp, "callback_query_handlers", None), "handlers", None)
    if reg is None: return False

    async def access(c):
        if not private(c): raise CancelHandler()
        uid = c.from_user.id
        if uid == getattr(app, "moderator_id", None): return
        g = gid(app)
        try:
            admins = await app.bot.get_chat_administrators(g) if g else []
            if uid in {a.user.id for a in admins}: return
        except Exception: pass
        await c.answer("⛔ فقط گرداننده یا مدیر گروه دسترسی دارد.", show_alert=True)
        raise CancelHandler()

    async def open_m(c):
        await access(c)
        try: await c.message.edit_text(report(app), reply_markup=kb(app), parse_mode="HTML")
        except Exception: logging.exception("management render failed")
        await c.answer()
        raise CancelHandler()

    async def delegate(c, attr, *args):
        await access(c)
        fn = getattr(app, attr, None)
        if not fn:
            await c.answer("⚠️ این عملیات در نسخه فعلی موجود نیست.", show_alert=True); raise CancelHandler()
        try:
            await fn(c, *args) if args else await fn(c)
        except Exception:
            logging.exception("management action failed: %s", attr)
            await c.answer("❌ اجرای عملیات ناموفق بود.", show_alert=True)
        raise CancelHandler()

    async def roles(c):
        await access(c); fn = getattr(app, "send_roles_panel", None)
        if not fn:
            await c.answer("⚠️ ارسال نقش در دسترس نیست.", show_alert=True); raise CancelHandler()
        try: await fn(c, app.bot)
        except Exception:
            logging.exception("resend roles failed"); await c.answer("❌ ارسال نقش ناموفق بود.", show_alert=True)
        raise CancelHandler()

    async def mod_menu(c):
        await access(c); g = gid(app)
        if not g: await c.answer("⚠️ گروه بازی تنظیم نشده است.", show_alert=True); raise CancelHandler()
        try: admins = await app.bot.get_chat_administrators(g)
        except Exception: admins = []
        k = InlineKeyboardMarkup(row_width=1)
        for a in admins: k.add(InlineKeyboardButton(html.escape(a.user.full_name), callback_data=f"pmgm:mod:{a.user.id}"))
        k.add(InlineKeyboardButton("⬅️ مدیریت بازی", callback_data="pmgm:back"))
        await c.message.edit_text("🎩 <b>تغییر گرداننده</b>\n\nگرداننده جدید را انتخاب کنید:", reply_markup=k, parse_mode="HTML")
        await c.answer(); raise CancelHandler()

    async def mod_set(c):
        await access(c); uid = int(str(c.data).rsplit(":", 1)[1]); g = gid(app)
        try: admins = {a.user.id for a in await app.bot.get_chat_administrators(g)} if g else set()
        except Exception: admins = set()
        if uid not in admins: await c.answer("گرداننده باید مدیر گروه باشد.", show_alert=True); raise CancelHandler()
        old = getattr(app, "moderator_id", None); app.moderator_id = uid
        try: await app.bot.send_message(g, f"🎩 <b>تغییر گرداننده</b>\nقبلی: {html.escape(name(app, old))}\nجدید: {html.escape(name(app, uid))}", parse_mode="HTML")
        except Exception: logging.exception("moderator notice failed")
        await c.message.edit_text(report(app), reply_markup=kb(app), parse_mode="HTML"); await c.answer("✅ گرداننده تغییر کرد"); raise CancelHandler()

    async def player_menu(c, mode):
        await access(c)
        if not (getattr(app, "game_running", False) or round_started(app)):
            await c.answer("⚠️ بازی در حال اجرا نیست.", show_alert=True); raise CancelHandler()
        pending = set(int(x) for x in (getattr(app, "_gm_extra_next_round", set()) or set()))
        muted = set(int(x) for x in (getattr(app, "_gm_muted_active", set()) or set()))
        k = InlineKeyboardMarkup(row_width=1)
        for s,u in sorted((getattr(app, "player_slots", {}) or {}).items()):
            s=int(s); selected = s in (muted if mode=="mute" else pending); icon = ("🔊" if selected else "🔇") if mode=="mute" else ("➖" if selected else "➕")
            k.add(InlineKeyboardButton(f"{icon} {s}. {name(app,u)}", callback_data=f"pmgm:{mode}:{s}"))
        k.add(InlineKeyboardButton("⬅️ مدیریت بازی", callback_data="pmgm:back"))
        title = "🔇 <b>سکوت</b>" if mode=="mute" else "➕ <b>ترن اضافی</b>"
        await c.message.edit_text(title+"\n\nبازیکن را انتخاب کنید:", reply_markup=k, parse_mode="HTML"); await c.answer(); raise CancelHandler()

    async def toggle(c, mode):
        await access(c); s=int(str(c.data).rsplit(":",1)[1]); slots=getattr(app,"player_slots",{}) or {}
        if s not in slots: await c.answer("بازیکن یافت نشد.", show_alert=True); raise CancelHandler()
        attr = "_gm_muted_active" if mode=="mute" else "_gm_extra_next_round"; st=getattr(app,attr,None)
        if not isinstance(st,set): st=set(st or []); setattr(app,attr,st)
        if s in st: st.remove(s); msg="🔊 سکوت لغو شد." if mode=="mute" else "➖ ترن اضافی لغو شد."
        else:
            st.add(s); msg="🔇 بازیکن ساکت شد." if mode=="mute" else "➕ ترن اضافی ثبت شد."
            if mode=="mute" and getattr(app,"_stable_phase","normal")=="normal":
                try:
                    if int(app.turn_order[app.current_turn_index])==s:
                        from runtime.stable_round_engine import _advance; await _advance(app)
                except Exception: pass
        await c.answer(msg); await player_menu(c, mode)

    async def back(c):
        await access(c); fn=getattr(app,"back_main",None)
        if fn:
            try: await fn(c); raise CancelHandler()
            except CancelHandler: raise
            except Exception: logging.exception("back_main failed")
        await c.message.edit_text("🏠 <b>منوی اصلی</b>", reply_markup=app.main_menu_keyboard(), parse_mode="HTML"); raise CancelHandler()

    regs=[
        (open_m, lambda c:c.data=="manage_game"),
        (lambda c:delegate(c,"list_players_pv"), lambda c:c.data=="list_players"),
        (roles, lambda c:c.data=="resend_roles"),
        (lambda c:delegate(c,"remove_player_handler"), lambda c:c.data=="remove_player"),
        (lambda c:delegate(c,"birthday_player_handler"), lambda c:c.data=="player_birthday"),
        (mod_menu, lambda c:c.data=="pmgm:mod"),
        (mod_set, lambda c:str(c.data or "").startswith("pmgm:mod:")),
        (lambda c:delegate(c,"show_substitute_list"), lambda c:c.data=="replace_player"),
        (lambda c:player_menu(c,"mute"), lambda c:c.data=="pmgm:mute"),
        (lambda c:toggle(c,"mute"), lambda c:str(c.data or "").startswith("pmgm:mute:")),
        (lambda c:player_menu(c,"extra"), lambda c:c.data=="pmgm:extra"),
        (lambda c:toggle(c,"extra"), lambda c:str(c.data or "").startswith("pmgm:extra:")),
        (lambda c:(access(c), render(app,c)), lambda c:c.data=="pmgm:back"),
        (back, lambda c:c.data=="back_main"),
    ]
    async def render(app,c):
        await c.message.edit_text(report(app), reply_markup=kb(app), parse_mode="HTML"); await c.answer(); raise CancelHandler()
    # Replace the tuple's late-bound render reference with a real handler.
    regs[-2]=(render, lambda c:c.data=="pmgm:back")
    for fn,filt in regs: app.dp.register_callback_query_handler(fn,filt,state="*")
    for fn,_ in reversed(regs):
        for i,item in enumerate(reg):
            if getattr(item,"callback",None) is fn: reg.insert(0,reg.pop(i)); break
    app._private_game_management_v4=True
    return True
