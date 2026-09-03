"""Private UI authority for Mafia Nights.

The private menu is isolated from the group lobby. Group-only keyboards are
never rendered from private callbacks.
"""
from __future__ import annotations

import html
import logging

from aiogram.dispatcher.handler import CancelHandler
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


LEGACY_MANAGEMENT_MODULES = {
    "runtime.admin_menus_v2",
    "runtime.stable_game_management",
    "runtime.stable_game_management_entry",
    "runtime.game_management_menu_patch",
    "runtime.private_game_management_v4",
}


def _private(callback):
    return bool(callback.message and callback.message.chat.type == "private")


def _group_id(app):
    # group_chat_id is the active game group. Before a lobby exists it is None,
    # so ALLOWED_GROUP_ID is the canonical configured group for private admin
    # authorization.
    for key in ("group_chat_id", "ALLOWED_GROUP_ID", "GROUP_ID", "group_id"):
        value = getattr(app, key, None)
        if value:
            try:
                return int(value)
            except Exception:
                pass
    return None


def _display(app, uid):
    if not uid:
        return "—"
    try:
        value = app.display_name(uid, (getattr(app, "players", {}) or {}).get(uid))
        if value and str(value) not in {"?", "❓", "None", "بازیکن"}:
            return str(value)
    except Exception:
        pass
    value = (getattr(app, "players", {}) or {}).get(uid)
    if isinstance(value, dict):
        value = value.get("nickname") or value.get("full_name") or value.get("first_name")
    return str(value or f"بازیکن {uid}")


def _is_running(app):
    return bool(
        getattr(app, "game_running", False)
        or getattr(app, "round_active", False)
        or getattr(app, "_stable_day_active", False)
        or getattr(app, "_stable_round_started", False)
    )


def start_keyboard():
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton("🛠 مدیریت بازی", callback_data="manage_game"),
        InlineKeyboardButton("⚙️ مدیریت سناریو", callback_data="final:scenarios"),
        InlineKeyboardButton("⚙️ امکانات اضافه", callback_data="addons_menu"),
        InlineKeyboardButton("👤 پروفایل", callback_data="up:menu"),
        InlineKeyboardButton("📚 راهنما", callback_data="final:help"),
    )
    return kb


def management_keyboard():
    kb = InlineKeyboardMarkup(row_width=1)
    for text, data in (
        ("👥 لیست بازیکنان", "finalgm:players"),
        ("📤 ارسال دوباره نقشها", "finalgm:roles"),
        ("🗑 حذف بازیکن", "finalgm:remove"),
        ("🎂 تولد بازیکن", "finalgm:birthday"),
        ("🎩 تغییر گرداننده", "finalgm:moderator"),
        ("🔄 جایگزین بازیکن", "finalgm:replace"),
        ("🔇 سکوت", "finalgm:mute"),
        ("➕ ترن اضافی", "finalgm:extra"),
        ("⬅️ بازگشت", "finalgm:back"),
    ):
        kb.add(InlineKeyboardButton(text, callback_data=data))
    return kb


def management_report(app):
    running = _is_running(app)
    status = "🟢 در حال اجرای بازی" if running else (
        "🟡 لابی فعال" if getattr(app, "lobby_active", False) else "⚪ آماده"
    )
    return (
        "🛠 <b>مدیریت بازی</b>\n\n"
        f"📌 وضعیت: <b>{status}</b>\n"
        f"📝 سناریو: <b>{html.escape(str(getattr(app, 'selected_scenario', None) or '—'))}</b>\n"
        f"👥 بازیکنان: <b>{len(getattr(app, 'players', {}) or {})}</b>\n"
        f"💺 صندلی‌ها: <b>{len(getattr(app, 'player_slots', {}) or {})}</b>\n"
        f"🎩 گرداننده: <b>{html.escape(_display(app, getattr(app, 'moderator_id', None)))}</b>"
    )


def scenario_keyboard():
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton("➕ افزودن سناریو", callback_data="final:scenario:add"),
        InlineKeyboardButton("➖ حذف سناریو", callback_data="final:scenario:remove"),
        InlineKeyboardButton("⬅️ بازگشت", callback_data="final:start"),
    )
    return kb


async def install(app):
    dp = app.dp
    cq = getattr(getattr(dp, "callback_query_handlers", None), "handlers", None)
    mh = getattr(getattr(dp, "message_handlers", None), "handlers", None)
    if cq is None or getattr(app, "_final_private_ui_installed", False):
        return False

    async def allowed(callback):
        if not _private(callback):
            raise CancelHandler()
        uid = callback.from_user.id
        if uid == getattr(app, "moderator_id", None):
            return True
        gid = _group_id(app)
        if gid:
            try:
                admins = await app.bot.get_chat_administrators(gid)
                if uid in {a.user.id for a in admins}:
                    return True
            except Exception:
                logging.exception("private UI: failed to resolve group administrators")
        await callback.answer("⛔ فقط گرداننده یا مدیر گروه دسترسی دارد.", show_alert=True)
        raise CancelHandler()

    async def start_message(message):
        if message.chat.type != "private":
            return
        await message.answer(
            "🎭 <b>Mafia Nights</b>\n\nیک گزینه را انتخاب کنید:",
            reply_markup=start_keyboard(),
            parse_mode="HTML",
        )
        raise CancelHandler()

    async def start_callback(callback):
        if not _private(callback):
            raise CancelHandler()
        await callback.message.edit_text(
            "🎭 <b>Mafia Nights</b>\n\nیک گزینه را انتخاب کنید:",
            reply_markup=start_keyboard(),
            parse_mode="HTML",
        )
        await callback.answer()
        raise CancelHandler()

    async def open_management(callback):
        await allowed(callback)
        await callback.message.edit_text(
            management_report(app), reply_markup=management_keyboard(), parse_mode="HTML"
        )
        await callback.answer()
        raise CancelHandler()

    async def open_scenarios(callback):
        await allowed(callback)
        await callback.message.edit_text(
            "⚙️ <b>مدیریت سناریو</b>\n\nیک گزینه را انتخاب کنید:",
            reply_markup=scenario_keyboard(), parse_mode="HTML"
        )
        await callback.answer()
        raise CancelHandler()

    async def scenario_add(callback):
        await allowed(callback)
        fn = getattr(app, "add_scenario_start", None)
        if not fn:
            await callback.answer("⚠️ افزودن سناریو در دسترس نیست.", show_alert=True)
            raise CancelHandler()
        await fn(callback, await app.dp.current_state(user=callback.from_user.id, chat=callback.message.chat.id))
        raise CancelHandler()

    async def scenario_remove(callback):
        await allowed(callback)
        scenarios = getattr(app, "scenarios", {}) or {}
        if not scenarios:
            await callback.message.edit_text("⚠️ هیچ سناریویی ثبت نشده است.", reply_markup=scenario_keyboard())
            await callback.answer()
            raise CancelHandler()
        kb = InlineKeyboardMarkup(row_width=1)
        for name in scenarios:
            kb.add(InlineKeyboardButton(f"❌ {name}", callback_data=f"final:scenario:delete:{name}"))
        kb.add(InlineKeyboardButton("⬅️ مدیریت سناریو", callback_data="final:scenarios"))
        await callback.message.edit_text("سناریوی موردنظر برای حذف را انتخاب کنید:", reply_markup=kb)
        await callback.answer()
        raise CancelHandler()

    async def scenario_delete(callback):
        await allowed(callback)
        name = str(callback.data).split(":", 3)[3]
        scenarios = getattr(app, "scenarios", {})
        if name not in scenarios:
            await callback.answer("⚠️ سناریو پیدا نشد.", show_alert=True)
            raise CancelHandler()
        scenarios.pop(name, None)
        saver = getattr(app, "save_scenarios", None)
        if saver:
            saver()
        await callback.message.edit_text(
            f"✅ سناریو «{html.escape(name)}» حذف شد.",
            reply_markup=scenario_keyboard(), parse_mode="HTML"
        )
        await callback.answer()
        raise CancelHandler()

    async def delegate(callback, attr, *args):
        await allowed(callback)
        fn = getattr(app, attr, None)
        if not fn:
            await callback.answer("⚠️ این عملیات در نسخه فعلی موجود نیست.", show_alert=True)
            raise CancelHandler()
        try:
            if args:
                await fn(callback, *args)
            else:
                await fn(callback)
        except Exception:
            logging.exception("private management action failed: %s", attr)
            await callback.answer("❌ اجرای عملیات ناموفق بود.", show_alert=True)
        raise CancelHandler()

    async def roles(callback):
        await allowed(callback)
        fn = getattr(app, "send_roles_panel", None)
        if not fn:
            await callback.answer("⚠️ ارسال نقش در دسترس نیست.", show_alert=True)
            raise CancelHandler()
        try:
            await fn(callback, app.bot)
        except Exception:
            logging.exception("private resend roles failed")
            await callback.answer("❌ ارسال نقش ناموفق بود.", show_alert=True)
        raise CancelHandler()

    async def moderator_menu(callback):
        await allowed(callback)
        gid = _group_id(app)
        if not gid:
            await callback.answer("⚠️ گروه بازی تنظیم نشده است.", show_alert=True)
            raise CancelHandler()
        try:
            admins = await app.bot.get_chat_administrators(gid)
        except Exception:
            admins = []
        kb = InlineKeyboardMarkup(row_width=1)
        for admin in admins:
            kb.add(InlineKeyboardButton(
                admin.user.full_name or str(admin.user.id),
                callback_data=f"finalgm:moderator:{admin.user.id}",
            ))
        kb.add(InlineKeyboardButton("⬅️ مدیریت بازی", callback_data="finalgm:back"))
        await callback.message.edit_text(
            "🎩 <b>تغییر گرداننده</b>\n\nگرداننده جدید را انتخاب کنید:",
            reply_markup=kb, parse_mode="HTML",
        )
        await callback.answer()
        raise CancelHandler()

    async def moderator_set(callback):
        await allowed(callback)
        try:
            uid = int(str(callback.data).rsplit(":", 1)[1])
        except Exception:
            await callback.answer("گرداننده نامعتبر است.", show_alert=True)
            raise CancelHandler()
        gid = _group_id(app)
        try:
            admins = {a.user.id for a in await app.bot.get_chat_administrators(gid)} if gid else set()
        except Exception:
            admins = set()
        if uid not in admins:
            await callback.answer("گرداننده باید مدیر گروه باشد.", show_alert=True)
            raise CancelHandler()
        old = getattr(app, "moderator_id", None)
        app.moderator_id = uid
        if gid:
            try:
                await app.bot.send_message(
                    gid,
                    "🎩 <b>تغییر گرداننده</b>\n"
                    f"قبلی: {html.escape(_display(app, old))}\n"
                    f"جدید: {html.escape(_display(app, uid))}",
                    parse_mode="HTML",
                )
            except Exception:
                logging.exception("private moderator announcement failed")
        await callback.message.edit_text(
            management_report(app), reply_markup=management_keyboard(), parse_mode="HTML"
        )
        await callback.answer("✅ گرداننده تغییر کرد")
        raise CancelHandler()

    async def player_menu(callback, mode):
        await allowed(callback)
        if not _is_running(app):
            await callback.answer("⚠️ بازی در حال اجرا نیست.", show_alert=True)
            raise CancelHandler()
        selected = getattr(app, "_gm_muted_active" if mode == "mute" else "_gm_extra_next_round", set()) or set()
        kb = InlineKeyboardMarkup(row_width=1)
        for seat, uid in sorted((getattr(app, "player_slots", {}) or {}).items()):
            seat = int(seat)
            active = seat in selected
            icon = ("🔊" if active else "🔇") if mode == "mute" else ("➖" if active else "➕")
            kb.add(InlineKeyboardButton(
                f"{icon} {seat}. {_display(app, uid)}",
                callback_data=f"finalgm:{mode}:{seat}",
            ))
        kb.add(InlineKeyboardButton("⬅️ مدیریت بازی", callback_data="finalgm:back"))
        title = "🔇 <b>سکوت</b>" if mode == "mute" else "➕ <b>ترن اضافی</b>"
        await callback.message.edit_text(
            f"{title}\n\nبازیکن را انتخاب کنید:", reply_markup=kb, parse_mode="HTML"
        )
        await callback.answer()
        raise CancelHandler()

    async def player_toggle(callback, mode):
        await allowed(callback)
        try:
            seat = int(str(callback.data).rsplit(":", 1)[1])
        except Exception:
            await callback.answer("صندلی نامعتبر است.", show_alert=True)
            raise CancelHandler()
        slots = getattr(app, "player_slots", {}) or {}
        if seat not in slots:
            await callback.answer("بازیکن یافت نشد.", show_alert=True)
            raise CancelHandler()
        attr = "_gm_muted_active" if mode == "mute" else "_gm_extra_next_round"
        selected = getattr(app, attr, None)
        if not isinstance(selected, set):
            selected = set(selected or [])
            setattr(app, attr, selected)
        if seat in selected:
            selected.remove(seat)
            answer = "🔊 سکوت لغو شد." if mode == "mute" else "➖ ترن اضافی لغو شد."
        else:
            selected.add(seat)
            answer = "🔇 بازیکن ساکت شد." if mode == "mute" else "➕ ترن اضافی ثبت شد."
        await callback.answer(answer)
        await player_menu(callback, mode)

    async def back(callback):
        await allowed(callback)
        await callback.message.edit_text(
            "🎭 <b>Mafia Nights</b>\n\nیک گزینه را انتخاب کنید:",
            reply_markup=start_keyboard(), parse_mode="HTML",
        )
        await callback.answer()
        raise CancelHandler()

    regs = [
        (open_management, lambda c: c.data == "manage_game"),
        (open_scenarios, lambda c: c.data == "final:scenarios"),
        (scenario_add, lambda c: c.data == "final:scenario:add"),
        (scenario_remove, lambda c: c.data == "final:scenario:remove"),
        (scenario_delete, lambda c: str(c.data or "").startswith("final:scenario:delete:")),
        (lambda c: delegate(c, "list_players_pv"), lambda c: c.data == "finalgm:players"),
        (roles, lambda c: c.data == "finalgm:roles"),
        (lambda c: delegate(c, "remove_player_handler"), lambda c: c.data == "finalgm:remove"),
        (lambda c: delegate(c, "birthday_player_handler"), lambda c: c.data == "finalgm:birthday"),
        (moderator_menu, lambda c: c.data == "finalgm:moderator"),
        (moderator_set, lambda c: str(c.data or "").startswith("finalgm:moderator:")),
        (lambda c: delegate(c, "show_substitute_list"), lambda c: c.data == "finalgm:replace"),
        (lambda c: player_menu(c, "mute"), lambda c: c.data == "finalgm:mute"),
        (lambda c: player_toggle(c, "mute"), lambda c: str(c.data or "").startswith("finalgm:mute:")),
        (lambda c: player_menu(c, "extra"), lambda c: c.data == "finalgm:extra"),
        (lambda c: player_toggle(c, "extra"), lambda c: str(c.data or "").startswith("finalgm:extra:")),
        (back, lambda c: c.data == "finalgm:back"),
        (start_callback, lambda c: c.data == "final:start"),
        (lambda c: delegate(c, "help_handler"), lambda c: c.data == "final:help"),
    ]
    for fn, filt in regs:
        dp.register_callback_query_handler(fn, filt, state="*")

    # aiogram 2.x stores the callable on HandlerObj.handler, not .callback.
    owned = [h for h in list(cq) if getattr(getattr(h, "handler", None), "__module__", "") == __name__]
    others = [h for h in list(cq) if h not in owned]
    cq[:] = owned + others

    dp.register_message_handler(start_message, commands=["start"], state="*")
    if mh:
        for i, h in enumerate(list(mh)):
            if getattr(getattr(h, "handler", None), "__module__", "") == __name__:
                mh.insert(0, mh.pop(i))
                break

    app._final_private_ui_installed = True
    return True
