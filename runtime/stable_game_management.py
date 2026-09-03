"""Stable private game-management controls.

This module owns only callbacks rendered in the bot's private admin panel.
It must never render or invoke group/lobby callbacks such as lv6_manage,
lv6_new, lv6_ready, or other group-flow handlers.
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


def _round_started(app):
    return bool(
        getattr(app, "round_active", False)
        or getattr(app, "_stable_day_active", False)
        or getattr(app, "_stable_round_started", False)
    )


def _is_running(app):
    return bool(getattr(app, "game_running", False) or _round_started(app))


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
        if value and str(value).strip() not in {"None", "?", "❓", "بازیکن"}:
            return str(value)
    except Exception:
        pass
    return f"بازیکن {uid}"


def _management_kb(app):
    """Keyboard for PRIVATE management only.

    Deliberately contains no legacy group/lobby callback_data.
    """
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton("👥 لیست بازیکنان", callback_data="gm:players"))
    if not _round_started(app):
        kb.add(InlineKeyboardButton("📝 تغییر سناریو", callback_data="gm:change_scenario"))
    kb.add(InlineKeyboardButton("🎩 تغییر گرداننده", callback_data="gm:change_moderator"))
    kb.add(InlineKeyboardButton("⚔️ وضعیت چالش", callback_data="gm:challenge"))
    kb.add(InlineKeyboardButton("🔇 سکوت بازیکن", callback_data="gm:mute"))
    kb.add(InlineKeyboardButton("➕ ترن اضافه", callback_data="gm:extra"))
    kb.add(InlineKeyboardButton("⬅️ بازگشت", callback_data="gm:back"))
    return kb


async def _render_management(app, callback, answer=None):
    running = _is_running(app)
    lobby = bool(getattr(app, "lobby_active", False))
    status = "در حال اجرای بازی" if running else ("لابی فعال" if lobby else "آماده")
    scenario = getattr(app, "selected_scenario", None) or "—"
    moderator = getattr(app, "moderator_id", None)
    mod_name = _name(app, moderator)
    text = (
        "🛠 <b>مدیریت بازی</b>\n\n"
        f"📌 وضعیت: <b>{status}</b>\n"
        f"📝 سناریو: <b>{html.escape(str(scenario))}</b>\n"
        f"🎩 گرداننده: <b>{html.escape(mod_name)}</b>\n"
        f"👥 بازیکنان: <b>{len(getattr(app, 'players', {}) or {})}</b>"
    )
    try:
        await callback.message.edit_text(text, reply_markup=_management_kb(app), parse_mode="HTML")
    except Exception as exc:
        logging.warning("stable game management render failed: %s", exc)
    try:
        await callback.answer(answer or "")
    except Exception:
        pass


def install(app):
    dp = app.dp
    reg = getattr(getattr(dp, "callback_query_handlers", None), "handlers", None)
    if reg is None or getattr(app, "_stable_game_management_installed", False):
        return False

    async def _private(callback):
        return bool(callback.message and callback.message.chat.type == "private")

    async def _can_manage(uid):
        if uid == getattr(app, "moderator_id", None):
            return True
        gid = _gid(app)
        if not gid:
            return False
        try:
            return uid in {a.user.id for a in await app.bot.get_chat_administrators(gid)}
        except Exception:
            return False

    async def change_scenario(callback):
        if not await _private(callback):
            raise CancelHandler()
        if not await _can_manage(callback.from_user.id):
            await callback.answer("⛔ فقط گرداننده یا مدیر گروه دسترسی دارد.", show_alert=True)
            raise CancelHandler()
        if _round_started(app):
            await callback.answer("⛔ بعد از شروع دور، تغییر سناریو امکان‌پذیر نیست.", show_alert=True)
            raise CancelHandler()
        app._stable_return_to_management = True
        kb = InlineKeyboardMarkup(row_width=1)
        for i, (scenario, cfg) in enumerate((app.scenarios or {}).items()):
            roles = (cfg or {}).get("roles") or []
            kb.add(InlineKeyboardButton(
                f"📝 {scenario} ({(cfg or {}).get('min_players', 1)}-{len(roles)})",
                callback_data=f"gm:scenario:{i}",
            ))
        kb.add(InlineKeyboardButton("⬅️ مدیریت بازی", callback_data="gm:back"))
        await callback.message.edit_text(
            "📝 <b>تغییر سناریو</b>\n\nسناریوی جدید را انتخاب کنید:",
            reply_markup=kb, parse_mode="HTML"
        )
        await callback.answer()
        raise CancelHandler()

    async def scenario_select(callback):
        if not await _private(callback):
            raise CancelHandler()
        if not await _can_manage(callback.from_user.id):
            await callback.answer("⛔ فقط گرداننده یا مدیر گروه دسترسی دارد.", show_alert=True)
            raise CancelHandler()
        if _round_started(app):
            await callback.answer("⛔ تغییر سناریو بعد از شروع دور ممنوع است.", show_alert=True)
            raise CancelHandler()
        try:
            index = int(str(callback.data).rsplit(":", 1)[1])
            selected = list(app.scenarios)[index]
        except Exception:
            await callback.answer("سناریو نامعتبر است.", show_alert=True)
            raise CancelHandler()
        app.selected_scenario = selected
        app.MAX_SEATS = len((app.scenarios[selected] or {}).get("roles") or [])
        # Do not call lobby handlers or create/render a group lobby here.
        # Existing player membership is preserved; only seat assignment is reset.
        if isinstance(getattr(app, "player_slots", None), dict):
            app.player_slots.clear()
        app._stable_return_to_management = False
        app._lv6_change_scenario = False
        app._lv6_setup = False
        await _render_management(app, callback, "✅ سناریو تغییر کرد")
        raise CancelHandler()

    async def change_moderator(callback):
        if not await _private(callback):
            raise CancelHandler()
        if not await _can_manage(callback.from_user.id):
            await callback.answer("⛔ فقط گرداننده یا مدیر گروه دسترسی دارد.", show_alert=True)
            raise CancelHandler()
        if not getattr(app, "lobby_active", False) and not getattr(app, "game_running", False):
            await callback.answer("⚠️ بازی یا لابی فعالی وجود ندارد.", show_alert=True)
            raise CancelHandler()
        app._stable_return_to_management = True
        kb = InlineKeyboardMarkup(row_width=1)
        gid = _gid(app)
        if gid:
            try:
                admins = await app.bot.get_chat_administrators(gid)
            except Exception:
                admins = []
            for admin in admins:
                label = html.escape(admin.user.full_name or str(admin.user.id))
                kb.add(InlineKeyboardButton(label, callback_data=f"gm:moderator:{admin.user.id}"))
        kb.add(InlineKeyboardButton("⬅️ مدیریت بازی", callback_data="gm:back"))
        await callback.message.edit_text(
            "🎩 <b>تغییر گرداننده</b>\n\nگرداننده جدید را انتخاب کنید:",
            reply_markup=kb, parse_mode="HTML"
        )
        await callback.answer()
        raise CancelHandler()

    async def moderator_select(callback):
        if not await _private(callback):
            raise CancelHandler()
        if not await _can_manage(callback.from_user.id):
            await callback.answer("⛔ فقط گرداننده یا مدیر گروه دسترسی دارد.", show_alert=True)
            raise CancelHandler()
        try:
            uid = int(str(callback.data).rsplit(":", 1)[1])
        except Exception:
            await callback.answer("گرداننده نامعتبر است.", show_alert=True)
            raise CancelHandler()
        gid = _gid(app)
        if not gid:
            await callback.answer("⚠️ گروه بازی تنظیم نشده است.", show_alert=True)
            raise CancelHandler()
        try:
            admins = {a.user.id for a in await app.bot.get_chat_administrators(gid)}
        except Exception:
            admins = set()
        if uid not in admins:
            await callback.answer("گرداننده باید مدیر گروه باشد.", show_alert=True)
            raise CancelHandler()
        old = getattr(app, "moderator_id", None)
        app.moderator_id = uid
        app._stable_return_to_management = False
        old_name = _name(app, old) if old else "—"
        new_name = _name(app, uid)
        try:
            await app.bot.send_message(
                gid,
                f"🎩 <b>تغییر گرداننده</b>\nگرداننده قبلی: {html.escape(old_name)}\nگرداننده جدید: {html.escape(new_name)}",
                parse_mode="HTML",
            )
        except Exception as exc:
            logging.warning("moderator change notice failed: %s", exc)
        await _render_management(app, callback, "✅ گرداننده تغییر کرد")
        raise CancelHandler()

    async def mute_menu(callback):
        if not await _private(callback):
            raise CancelHandler()
        if not await _can_manage(callback.from_user.id):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
            raise CancelHandler()
        if not _is_running(app):
            await callback.answer("⚠️ بازی در حال اجرا نیست.", show_alert=True)
            raise CancelHandler()
        kb = InlineKeyboardMarkup(row_width=1)
        for seat, uid in sorted((app.player_slots or {}).items()):
            kb.add(InlineKeyboardButton(
                f"{'🔊' if int(seat) in getattr(app, '_gm_muted_active', set()) else '🔇'} {seat}. {_name(app, uid)}",
                callback_data=f"gm:mute:{int(seat)}"
            ))
        kb.add(InlineKeyboardButton("⬅️ مدیریت بازی", callback_data="gm:back"))
        await callback.message.edit_text(
            "🔇 <b>سکوت بازیکن</b>\n\nبازیکن را انتخاب کنید:\n🔇 = ساکت | 🔊 = لغو سکوت",
            reply_markup=kb, parse_mode="HTML"
        )
        await callback.answer()
        raise CancelHandler()

    async def mute_toggle(callback):
        if not await _private(callback):
            raise CancelHandler()
        if not await _can_manage(callback.from_user.id):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
            raise CancelHandler()
        try:
            seat = int(str(callback.data).rsplit(":", 1)[1])
        except Exception:
            await callback.answer("صندلی نامعتبر است.", show_alert=True)
            raise CancelHandler()
        if seat not in (app.player_slots or {}):
            await callback.answer("بازیکن یافت نشد.", show_alert=True)
            raise CancelHandler()
        muted = getattr(app, "_gm_muted_active", None)
        if not isinstance(muted, set):
            muted = set()
            app._gm_muted_active = muted
        if seat in muted:
            muted.remove(seat)
            answer = "🔊 سکوت بازیکن لغو شد."
        else:
            muted.add(seat)
            answer = "🔇 بازیکن برای نوبت جاری ساکت شد."
            # If this is the currently active normal speaker, advance now.
            try:
                active = int(app.turn_order[app.current_turn_index])
            except Exception:
                active = None
            if active == seat and getattr(app, "_stable_phase", "normal") == "normal":
                from runtime.stable_round_engine import advance_from_management
                await advance_from_management(app)
        await callback.answer(answer)
        await mute_menu(callback)

    async def extra_menu(callback):
        if not await _private(callback):
            raise CancelHandler()
        if not await _can_manage(callback.from_user.id):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
            raise CancelHandler()
        if not _is_running(app):
            await callback.answer("⚠️ بازی در حال اجرا نیست.", show_alert=True)
            raise CancelHandler()
        kb = InlineKeyboardMarkup(row_width=1)
        pending = getattr(app, "_gm_extra_next_round", set()) or set()
        for seat, uid in sorted((app.player_slots or {}).items()):
            icon = "➖" if int(seat) in pending else "➕"
            kb.add(InlineKeyboardButton(
                f"{icon} {seat}. {_name(app, uid)}",
                callback_data=f"gm:extra:{int(seat)}"
            ))
        kb.add(InlineKeyboardButton("⬅️ مدیریت بازی", callback_data="gm:back"))
        await callback.message.edit_text(
            "➕ <b>ترن اضافه</b>\n\nبازیکن را انتخاب کنید:\n➕ = ثبت | ➖ = لغو",
            reply_markup=kb, parse_mode="HTML"
        )
        await callback.answer()
        raise CancelHandler()

    async def extra_select(callback):
        if not await _private(callback):
            raise CancelHandler()
        if not await _can_manage(callback.from_user.id):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
            raise CancelHandler()
        try:
            seat = int(str(callback.data).rsplit(":", 1)[1])
        except Exception:
            await callback.answer("صندلی نامعتبر است.", show_alert=True)
            raise CancelHandler()
        if seat not in (app.player_slots or {}):
            await callback.answer("بازیکن یافت نشد.", show_alert=True)
            raise CancelHandler()
        pending = getattr(app, "_gm_extra_next_round", None)
        if not isinstance(pending, set):
            pending = set()
            app._gm_extra_next_round = pending
        if seat in pending:
            pending.remove(seat)
            answer = "➖ ترن اضافه لغو شد."
        else:
            pending.add(seat)
            answer = "➕ ترن اضافه برای پایان نوبت‌های عادی ثبت شد."
        await callback.answer(answer)
        await extra_menu(callback)

    async def players(callback):
        if not await _private(callback):
            raise CancelHandler()
        if not await _can_manage(callback.from_user.id):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
            raise CancelHandler()
        lines = ["👥 <b>بازیکنان بازی</b>", ""]
        for seat, uid in sorted((app.player_slots or {}).items()):
            lines.append(f"{int(seat):02d}. {html.escape(_name(app, uid))}")
        kb = InlineKeyboardMarkup().add(InlineKeyboardButton("⬅️ مدیریت بازی", callback_data="gm:back"))
        await callback.message.edit_text("\n".join(lines), reply_markup=kb, parse_mode="HTML")
        await callback.answer()
        raise CancelHandler()

    async def challenge_menu(callback):
        if not await _private(callback):
            raise CancelHandler()
        if not await _can_manage(callback.from_user.id):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
            raise CancelHandler()
        # Keep this private-only. The actual challenge mechanics remain in the
        # round engine/group UI and are not invoked from this panel.
        await callback.answer("⚔️ وضعیت چالش از پنل مدیریت بازی قابل مشاهده است.", show_alert=True)
        raise CancelHandler()

    async def back_management(callback):
        if not await _private(callback):
            raise CancelHandler()
        if not await _can_manage(callback.from_user.id):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
            raise CancelHandler()
        app._stable_return_to_management = False
        await _render_management(app, callback)
        raise CancelHandler()

    handlers = [
        (change_scenario, lambda c: c.data == "gm:change_scenario"),
        (scenario_select, lambda c: str(c.data or "").startswith("gm:scenario:")),
        (change_moderator, lambda c: c.data == "gm:change_moderator"),
        (moderator_select, lambda c: str(c.data or "").startswith("gm:moderator:")),
        (back_management, lambda c: c.data == "gm:back"),
        (challenge_menu, lambda c: c.data == "gm:challenge"),
        (mute_menu, lambda c: c.data == "gm:mute"),
        (mute_toggle, lambda c: str(c.data or "").startswith("gm:mute:")),
        (extra_menu, lambda c: c.data == "gm:extra"),
        (extra_select, lambda c: str(c.data or "").startswith("gm:extra:")),
        (players, lambda c: c.data == "gm:players"),
    ]
    for fn, filt in handlers:
        dp.register_callback_query_handler(fn, filt, state="*")
    # Put all stable private-management handlers ahead of legacy handlers.
    for fn, _ in reversed(handlers):
        for i, item in enumerate(reg):
            if getattr(item, "handler", None) is fn:
                reg.insert(0, reg.pop(i))
                break
    app._stable_game_management_installed = True
    return True
