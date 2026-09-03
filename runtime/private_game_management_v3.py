"""Private-only game management v3.

This is the sole UI owner for the private game-management panel.
It deliberately never renders or invokes lobby/group menu callbacks.
"""
from __future__ import annotations

import html
import logging
from aiogram.dispatcher.handler import CancelHandler
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def _gid(app):
    for key in ("group_chat_id", "ALLOWED_GROUP_ID", "GROUP_ID", "group_id"):
        value = getattr(app, key, None)
        if value:
            try:
                return int(value)
            except Exception:
                pass
    return None


def _is_round_started(app):
    return bool(
        getattr(app, "round_active", False)
        or getattr(app, "_stable_day_active", False)
        or getattr(app, "_stable_round_started", False)
    )


def _is_private(callback):
    return bool(callback.message and callback.message.chat.type == "private")


def _name(app, uid):
    if not uid:
        return "—"
    try:
        value = app.display_name(uid, getattr(app, "players", {}).get(uid))
        if value and str(value).strip() not in {"None", "?", "❓", "بازیکن"}:
            return str(value)
    except Exception:
        pass
    try:
        value = getattr(app, "players", {}).get(uid)
        if isinstance(value, dict):
            value = value.get("nickname") or value.get("full_name") or value.get("first_name")
        if value:
            return str(value)
    except Exception:
        pass
    return f"بازیکن {uid}"


def management_keyboard(app):
    """Exactly the nine private management actions requested by the product."""
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton("👥 لیست بازیکنان", callback_data="list_players"))
    kb.add(InlineKeyboardButton("📤 ارسال دوباره نقشها", callback_data="resend_roles"))
    kb.add(InlineKeyboardButton("🗑 حذف بازیکن", callback_data="remove_player"))
    kb.add(InlineKeyboardButton("🎂 تولد بازیکن", callback_data="player_birthday"))
    kb.add(InlineKeyboardButton("🎩 تغییر گرداننده", callback_data="pmgm:change_moderator"))
    kb.add(InlineKeyboardButton("🔄 جایگزین بازیکن", callback_data="replace_player"))
    kb.add(InlineKeyboardButton("🔇 سکوت", callback_data="pmgm:mute"))
    kb.add(InlineKeyboardButton("➕ ترن اضافی", callback_data="pmgm:extra"))
    kb.add(InlineKeyboardButton("⬅️ بازگشت", callback_data="back_main"))
    return kb


def _report(app):
    running = bool(getattr(app, "game_running", False))
    round_started = _is_round_started(app)
    if running or round_started:
        status = "🟢 در حال اجرای بازی"
    elif getattr(app, "lobby_active", False):
        status = "🟡 لابی فعال"
    else:
        status = "⚪ آماده"

    scenario = getattr(app, "selected_scenario", None) or "—"
    players = getattr(app, "players", {}) or {}
    slots = getattr(app, "player_slots", {}) or {}
    moderator = getattr(app, "moderator_id", None)
    return (
        "🛠 <b>مدیریت بازی</b>\n\n"
        f"📌 وضعیت: <b>{status}</b>\n"
        f"📝 سناریو: <b>{html.escape(str(scenario))}</b>\n"
        f"👥 آمار بازیکنان: <b>{len(players)}</b> نفر\n"
        f"💺 صندلی‌های انتخاب‌شده: <b>{len(slots)}</b>\n"
        f"🎩 گرداننده: <b>{html.escape(_name(app, moderator))}</b>"
    )


async def render(app, callback, answer=None):
    if not _is_private(callback):
        raise CancelHandler()
    try:
        await callback.message.edit_text(
            _report(app), reply_markup=management_keyboard(app), parse_mode="HTML"
        )
    except Exception as exc:
        logging.warning("private management render failed: %s", exc)
    try:
        await callback.answer(answer or "")
    except Exception:
        pass


async def _can_manage(app, uid):
    if uid == getattr(app, "moderator_id", None):
        return True
    gid = _gid(app)
    if not gid:
        return False
    try:
        return uid in {a.user.id for a in await app.bot.get_chat_administrators(gid)}
    except Exception:
        return False


async def install(app):
    if getattr(app, "_private_game_management_v3_installed", False):
        return False
    handlers = getattr(getattr(app.dp, "callback_query_handlers", None), "handlers", None)
    if handlers is None:
        return False

    async def guard(callback):
        if not _is_private(callback):
            raise CancelHandler()
        if not await _can_manage(app, callback.from_user.id):
            await callback.answer("⛔ فقط گرداننده یا مدیر گروه دسترسی دارد.", show_alert=True)
            raise CancelHandler()

    async def open_management(callback):
        await guard(callback)
        await render(app, callback)
        raise CancelHandler()

    async def delegate(callback, name, *args):
        await guard(callback)
        fn = getattr(app, name, None)
        if fn is None:
            await callback.answer("⚠️ این عملیات در نسخه فعلی در دسترس نیست.", show_alert=True)
            raise CancelHandler()
        try:
            result = await fn(callback, *args) if args else await fn(callback)
        except Exception:
            logging.exception("private management delegate failed: %s", name)
            await callback.answer("❌ اجرای عملیات ناموفق بود.", show_alert=True)
            raise CancelHandler()
        # The delegated legacy handlers are private handlers and may render
        # their own submenus. They must never be followed by a lobby callback.
        raise CancelHandler()

    async def list_players(callback):
        await delegate(callback, "list_players_pv")

    async def resend_roles(callback):
        await guard(callback)
        fn = getattr(app, "send_roles_panel", None)
        if fn is None:
            await callback.answer("⚠️ ارسال نقش در دسترس نیست.", show_alert=True)
            raise CancelHandler()
        try:
            await fn(callback, app.bot)
        except Exception:
            logging.exception("resend roles failed")
            await callback.answer("❌ ارسال دوباره نقش‌ها ناموفق بود.", show_alert=True)
        raise CancelHandler()

    async def remove_player(callback):
        await delegate(callback, "remove_player_handler")

    async def birthday(callback):
        await delegate(callback, "birthday_player_handler")

    async def replace_player(callback):
        await delegate(callback, "show_substitute_list")

    async def moderator_menu(callback):
        await guard(callback)
        gid = _gid(app)
        if not gid:
            await callback.answer("⚠️ گروه بازی تنظیم نشده است.", show_alert=True)
            raise CancelHandler()
        try:
            admins = await app.bot.get_chat_administrators(gid)
        except Exception:
            admins = []
        kb = InlineKeyboardMarkup(row_width=1)
        for admin in admins:
            uid = admin.user.id
            label = html.escape(admin.user.full_name or str(uid))
            kb.add(InlineKeyboardButton(label, callback_data=f"pmgm:moderator:{uid}"))
        kb.add(InlineKeyboardButton("⬅️ مدیریت بازی", callback_data="pmgm:back"))
        await callback.message.edit_text(
            "🎩 <b>تغییر گرداننده</b>\n\nگرداننده جدید را انتخاب کنید:",
            reply_markup=kb,
            parse_mode="HTML",
        )
        await callback.answer()
        raise CancelHandler()

    async def moderator_select(callback):
        await guard(callback)
        try:
            uid = int(str(callback.data).rsplit(":", 1)[1])
        except Exception:
            await callback.answer("گرداننده نامعتبر است.", show_alert=True)
            raise CancelHandler()
        gid = _gid(app)
        try:
            admins = {a.user.id for a in await app.bot.get_chat_administrators(gid)} if gid else set()
        except Exception:
            admins = set()
        if uid not in admins:
            await callback.answer("گرداننده باید مدیر گروه باشد.", show_alert=True)
            raise CancelHandler()
        old = getattr(app, "moderator_id", None)
        app.moderator_id = uid
        try:
            await app.bot.send_message(
                gid,
                "🎩 <b>تغییر گرداننده</b>\n"
                f"گرداننده قبلی: {html.escape(_name(app, old))}\n"
                f"گرداننده جدید: {html.escape(_name(app, uid))}",
                parse_mode="HTML",
            )
        except Exception:
            logging.exception("moderator announcement failed")
        await render(app, callback, "✅ گرداننده تغییر کرد")
        raise CancelHandler()

    async def mute_menu(callback):
        await guard(callback)
        if not (getattr(app, "game_running", False) or _is_round_started(app)):
            await callback.answer("⚠️ بازی در حال اجرا نیست.", show_alert=True)
            raise CancelHandler()
        muted = {int(x) for x in (getattr(app, "_gm_muted_active", set()) or set())}
        kb = InlineKeyboardMarkup(row_width=1)
        for seat, uid in sorted((getattr(app, "player_slots", {}) or {}).items()):
            seat = int(seat)
            icon = "🔊" if seat in muted else "🔇"
            kb.add(InlineKeyboardButton(f"{icon} {seat}. {_name(app, uid)}", callback_data=f"pmgm:mute:{seat}"))
        kb.add(InlineKeyboardButton("⬅️ مدیریت بازی", callback_data="pmgm:back"))
        await callback.message.edit_text(
            "🔇 <b>سکوت</b>\n\nبازیکن را انتخاب کنید:\n🔇 = ساکت | 🔊 = لغو سکوت",
            reply_markup=kb,
            parse_mode="HTML",
        )
        await callback.answer()
        raise CancelHandler()

    async def mute_toggle(callback):
        await guard(callback)
        try:
            seat = int(str(callback.data).rsplit(":", 1)[1])
        except Exception:
            await callback.answer("صندلی نامعتبر است.", show_alert=True)
            raise CancelHandler()
        slots = getattr(app, "player_slots", {}) or {}
        if seat not in slots:
            await callback.answer("بازیکن یافت نشد.", show_alert=True)
            raise CancelHandler()
        muted = getattr(app, "_gm_muted_active", None)
        if not isinstance(muted, set):
            muted = set(muted or [])
            app._gm_muted_active = muted
        if seat in muted:
            muted.remove(seat)
            answer = "🔊 سکوت لغو شد."
        else:
            muted.add(seat)
            answer = "🔇 بازیکن ساکت شد."
            try:
                active = int(app.turn_order[app.current_turn_index])
            except Exception:
                active = None
            if active == seat and getattr(app, "_stable_phase", "normal") == "normal":
                from runtime.stable_round_engine import _advance
                await _advance(app)
        await callback.answer(answer)
        await mute_menu(callback)

    async def extra_menu(callback):
        await guard(callback)
        if not (getattr(app, "game_running", False) or _is_round_started(app)):
            await callback.answer("⚠️ بازی در حال اجرا نیست.", show_alert=True)
            raise CancelHandler()
        pending = {int(x) for x in (getattr(app, "_gm_extra_next_round", set()) or set())}
        kb = InlineKeyboardMarkup(row_width=1)
        for seat, uid in sorted((getattr(app, "player_slots", {}) or {}).items()):
            seat = int(seat)
            icon = "➖" if seat in pending else "➕"
            kb.add(InlineKeyboardButton(f"{icon} {seat}. {_name(app, uid)}", callback_data=f"pmgm:extra:{seat}"))
        kb.add(InlineKeyboardButton("⬅️ مدیریت بازی", callback_data="pmgm:back"))
        await callback.message.edit_text(
            "➕ <b>ترن اضافی</b>\n\nبازیکن را انتخاب کنید:\n➕ = ثبت | ➖ = لغو",
            reply_markup=kb,
            parse_mode="HTML",
        )
        await callback.answer()
        raise CancelHandler()

    async def extra_toggle(callback):
        await guard(callback)
        try:
            seat = int(str(callback.data).rsplit(":", 1)[1])
        except Exception:
            await callback.answer("صندلی نامعتبر است.", show_alert=True)
            raise CancelHandler()
        if seat not in (getattr(app, "player_slots", {}) or {}):
            await callback.answer("بازیکن یافت نشد.", show_alert=True)
            raise CancelHandler()
        pending = getattr(app, "_gm_extra_next_round", None)
        if not isinstance(pending, set):
            pending = set(pending or [])
            app._gm_extra_next_round = pending
        if seat in pending:
            pending.remove(seat)
            answer = "➖ ترن اضافی لغو شد."
        else:
            pending.add(seat)
            answer = "➕ ترن اضافی ثبت شد."
        await callback.answer(answer)
        await extra_menu(callback)

    async def back_management(callback):
        await guard(callback)
        await render(app, callback)
        raise CancelHandler()

    async def back_start(callback):
        await guard(callback)
        fn = getattr(app, "back_main", None)
        if fn is not None:
            try:
                await fn(callback)
                raise CancelHandler()
            except CancelHandler:
                raise
            except Exception:
                logging.exception("back_main failed; rendering private main menu")
        try:
            kb = app.main_menu_keyboard()
            await callback.message.edit_text("🏠 <b>منوی اصلی</b>", reply_markup=kb, parse_mode="HTML")
        except Exception:
            await callback.answer("🏠 بازگشت به منوی اصلی", show_alert=False)
        raise CancelHandler()

    registrations = [
        (open_management, lambda c: c.data == "manage_game"),
        (list_players, lambda c: c.data == "list_players"),
        (resend_roles, lambda c: c.data == "resend_roles"),
        (remove_player, lambda c: c.data == "remove_player"),
        (birthday, lambda c: c.data == "player_birthday"),
        (moderator_menu, lambda c: c.data == "pmgm:change_moderator"),
        (moderator_select, lambda c: str(c.data or "").startswith("pmgm:moderator:")),
        (replace_player, lambda c: c.data == "replace_player"),
        (mute_menu, lambda c: c.data == "pmgm:mute"),
        (mute_toggle, lambda c: str(c.data or "").startswith("pmgm:mute:")),
        (extra_menu, lambda c: c.data == "pmgm:extra"),
        (extra_toggle, lambda c: str(c.data or "").startswith("pmgm:extra:")),
        (back_management, lambda c: c.data == "pmgm:back"),
        (back_start, lambda c: c.data == "back_main"),
    ]

    for fn, filt in registrations:
        app.dp.register_callback_query_handler(fn, filt, state="*")

    # Aiogram checks handlers in registration order. Move our private handlers
    # to the front so legacy patches cannot redirect these callbacks to lobby UI.
    for fn, _ in reversed(registrations):
        for i, item in enumerate(handlers):
            if getattr(item, "callback", None) is fn:
                handlers.insert(0, handlers.pop(i))
                break

    app._private_game_management_v3_installed = True
    logging.info("Private game management v3 installed: nine actions, private-only navigation")
    return True
