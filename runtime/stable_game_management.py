"""Stable game-management controls and navigation.

This layer owns the private game-management callbacks that historically were
only rendered by the menu but were not wired, and keeps scenario/moderator
selection inside the management flow instead of restarting the lobby.
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


def _is_running(app):
    return bool(getattr(app, "game_running", False) or getattr(app, "round_active", False)
                or getattr(app, "_stable_day_active", False))


def _name(app, uid):
    try:
        value = app.display_name(uid, getattr(app, "players", {}).get(uid))
        if value and str(value).strip() not in {"None", "?", "❓", "بازیکن"}:
            return str(value)
    except Exception:
        pass
    try:
        value = getattr(app, "players", {}).get(uid)
        if value and str(value).strip() not in {"None", "?", "❓", "بازیکن"}:
            return str(value)
    except Exception:
        pass
    return f"بازیکن {uid}"


def _management_kb(app):
    kb = InlineKeyboardMarkup(row_width=1)
    running = _is_running(app)
    lobby = bool(getattr(app, "lobby_active", False))
    if not running and not lobby:
        kb.add(InlineKeyboardButton("🎮 ساخت بازی جدید", callback_data="lv6_new"))
    else:
        kb.add(InlineKeyboardButton("⚙️ مدیریت لابی", callback_data="lv6_manage"))
    kb.add(InlineKeyboardButton("👥 لیست بازیکنان", callback_data="gm:players"))
    kb.add(InlineKeyboardButton("🚫 لغو بازی", callback_data="lv6_cancel"))
    if not _is_running(app):
        kb.add(InlineKeyboardButton("📝 تغییر سناریو", callback_data="gm:change_scenario"))
    kb.add(InlineKeyboardButton("🎩 تغییر گرداننده", callback_data="gm:change_moderator"))
    kb.add(InlineKeyboardButton("⚔️ وضعیت چالش", callback_data="lv6_challenge"))
    kb.add(InlineKeyboardButton("🔇 سکوت بازیکن", callback_data="gm:mute"))
    kb.add(InlineKeyboardButton("➕ ترن اضافه", callback_data="gm:extra"))
    kb.add(InlineKeyboardButton("🗑 حذف بازیکن", callback_data="lv6_remove"))
    kb.add(InlineKeyboardButton("📢 حاضری / تگ لیست", callback_data="lv6_ready"))
    kb.add(InlineKeyboardButton("⬅️ بازگشت", callback_data="adm2:main"))
    return kb


async def _render_management(app, callback, answer=None):
    running = _is_running(app)
    lobby = bool(getattr(app, "lobby_active", False))
    status = "در حال اجرای بازی" if running else ("لابی فعال" if lobby else "آماده")
    scenario = getattr(app, "selected_scenario", None) or "—"
    moderator = getattr(app, "moderator_id", None)
    mod_name = _name(app, moderator) if moderator else "—"
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
    await callback.answer(answer or "")


def install(app):
    dp = app.dp
    reg = getattr(getattr(dp, "callback_query_handlers", None), "handlers", None)
    if reg is None or getattr(app, "_stable_game_management_installed", False):
        return False

    # Replace the private AdminMenusV2.open_game renderer itself. This is
    # important because game_management_menu_patch previously rendered old
    # callback_data (lv6_change_s/lv6_change_m), which fell through to the
    # legacy lobby flow after a selection.
    try:
        from runtime.admin_menus_v2 import AdminMenusV2

        async def open_game(self, callback):
            if callback.message.chat.type != "private":
                await callback.answer("این بخش فقط در پیوی قابل استفاده است.", show_alert=True)
                return
            if not await self._can_manage(callback.from_user.id):
                await callback.answer("⛔ فقط گرداننده یا مدیر گروه دسترسی دارد.", show_alert=True)
                return
            await _render_management(self.app, callback)

        AdminMenusV2.open_game = open_game
    except Exception as exc:
        logging.warning("stable game management: could not replace AdminMenusV2.open_game: %s", exc)

    async def change_scenario(callback):
        if _is_running(app):
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
        await callback.message.edit_text("📝 <b>تغییر سناریو</b>\n\nسناریوی جدید را انتخاب کنید:", reply_markup=kb, parse_mode="HTML")
        await callback.answer()
        raise CancelHandler()

    async def scenario_select(callback):
        if not getattr(app, "_stable_return_to_management", False):
            raise CancelHandler()
        try:
            index = int(str(callback.data).rsplit(":", 1)[1])
            selected = list(app.scenarios)[index]
        except Exception:
            await callback.answer("سناریو نامعتبر است.", show_alert=True)
            raise CancelHandler()
        if _is_running(app):
            await callback.answer("⛔ تغییر سناریو بعد از شروع دور ممنوع است.", show_alert=True)
            raise CancelHandler()
        app.selected_scenario = selected
        app.MAX_SEATS = len((app.scenarios[selected] or {}).get("roles") or [])
        app.player_slots.clear()
        app.waiting_list.clear()
        app._stable_return_to_management = False
        app._lv6_change_scenario = False
        app._lv6_setup = False
        app.lobby_active = True
        await _render_management(app, callback, "✅ سناریو تغییر کرد")
        raise CancelHandler()

    async def back_management(callback):
        app._stable_return_to_management = False
        await _render_management(app, callback)
        raise CancelHandler()

    async def change_moderator(callback):
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
        await callback.message.edit_text("🎩 <b>تغییر گرداننده</b>\n\nگرداننده جدید را انتخاب کنید:", reply_markup=kb, parse_mode="HTML")
        await callback.answer()
        raise CancelHandler()

    async def moderator_select(callback):
        try:
            uid = int(str(callback.data).rsplit(":", 1)[1])
        except Exception:
            await callback.answer("گرداننده نامعتبر است.", show_alert=True)
            raise CancelHandler()
        gid = _gid(app)
        if gid:
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
        if gid:
            old_name = _name(app, old) if old else "—"
            new_name = _name(app, uid)
            await app.bot.send_message(
                gid,
                f"🎩 <b>تغییر گرداننده</b>\nگرداننده قبلی: {html.escape(old_name)}\nگرداننده جدید: {html.escape(new_name)}",
                parse_mode="HTML",
            )
        await _render_management(app, callback, "✅ گرداننده تغییر کرد")
        raise CancelHandler()

    async def mute_menu(callback):
        if not _is_running(app):
            await callback.answer("⚠️ بازی در حال اجرا نیست.", show_alert=True)
            raise CancelHandler()
        kb = InlineKeyboardMarkup(row_width=1)
        for seat, uid in sorted((app.player_slots or {}).items()):
            kb.add(InlineKeyboardButton(f"🔇 {seat}. {_name(app, uid)}", callback_data=f"gm:mute:{int(seat)}"))
        kb.add(InlineKeyboardButton("⬅️ مدیریت بازی", callback_data="gm:back"))
        await callback.message.edit_text("🔇 <b>سکوت بازیکن</b>\n\nبازیکن را انتخاب کنید:", reply_markup=kb, parse_mode="HTML")
        await callback.answer()
        raise CancelHandler()

    async def mute_toggle(callback):
        try:
            seat = int(str(callback.data).rsplit(":", 1)[1])
        except Exception:
            await callback.answer("صندلی نامعتبر است.", show_alert=True)
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
        await callback.answer(answer)
        await mute_menu(callback)

    async def extra_menu(callback):
        if not _is_running(app):
            await callback.answer("⚠️ بازی در حال اجرا نیست.", show_alert=True)
            raise CancelHandler()
        kb = InlineKeyboardMarkup(row_width=1)
        for seat, uid in sorted((app.player_slots or {}).items()):
            kb.add(InlineKeyboardButton(f"➕ {seat}. {_name(app, uid)}", callback_data=f"gm:extra:{int(seat)}"))
        kb.add(InlineKeyboardButton("⬅️ مدیریت بازی", callback_data="gm:back"))
        await callback.message.edit_text("➕ <b>ترن اضافه</b>\n\nبازیکن را انتخاب کنید:", reply_markup=kb, parse_mode="HTML")
        await callback.answer()
        raise CancelHandler()

    async def extra_select(callback):
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
        lines = ["👥 <b>بازیکنان بازی</b>", ""]
        for seat, uid in sorted((app.player_slots or {}).items()):
            lines.append(f"{seat:02d}. {html.escape(_name(app, uid))}")
        kb = InlineKeyboardMarkup().add(InlineKeyboardButton("⬅️ مدیریت بازی", callback_data="gm:back"))
        await callback.message.edit_text("\n".join(lines), reply_markup=kb, parse_mode="HTML")
        await callback.answer()
        raise CancelHandler()

    handlers = [
        (change_scenario, lambda c: c.data == "gm:change_scenario"),
        (scenario_select, lambda c: str(c.data or "").startswith("gm:scenario:")),
        (change_moderator, lambda c: c.data == "gm:change_moderator"),
        (moderator_select, lambda c: str(c.data or "").startswith("gm:moderator:")),
        (back_management, lambda c: c.data == "gm:back"),
        (mute_menu, lambda c: c.data == "gm:mute"),
        (mute_toggle, lambda c: str(c.data or "").startswith("gm:mute:")),
        (extra_menu, lambda c: c.data == "gm:extra"),
        (extra_select, lambda c: str(c.data or "").startswith("gm:extra:")),
        (players, lambda c: c.data == "gm:players"),
    ]
    for fn, filt in handlers:
        dp.register_callback_query_handler(fn, filt, state="*")
    for fn, _ in reversed(handlers):
        for i, item in enumerate(reg):
            if getattr(item, "handler", None) is fn:
                reg.insert(0, reg.pop(i))
                break
    app._stable_game_management_installed = True
    return True
