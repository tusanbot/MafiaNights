"""Final private UI routing fixes.

Installed after the legacy/private UI layers so these callbacks have deterministic
precedence without removing any existing game functionality.
"""
from __future__ import annotations

import html

from aiogram.dispatcher.handler import CancelHandler
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def install(app):
    if getattr(app, "_private_ui_hotfix_installed", False):
        return False
    dp = app.dp
    handlers = getattr(getattr(dp, "callback_query_handlers", None), "handlers", [])

    async def allowed(c):
        if not c.message or c.message.chat.type != "private":
            raise CancelHandler()
        uid = int(c.from_user.id)
        if uid == int(getattr(app, "moderator_id", 0) or 0):
            return
        cached = set()
        for obj in (app, getattr(app, "addons", None)):
            for attr in ("admins", "group_admins"):
                for x in getattr(obj, attr, None) or []:
                    try: cached.add(int(getattr(getattr(x, "user", None), "id", x)))
                    except Exception: pass
        if uid in cached: return
        gid = getattr(app, "ALLOWED_GROUP_ID", None)
        if gid:
            try:
                admins = await app.bot.get_chat_administrators(int(gid))
                ids = {int(a.user.id) for a in admins}; app.admins = ids; app.group_admins = list(ids)
                if uid in ids: return
            except Exception: pass
        await c.answer("⛔ فقط گرداننده یا مدیر گروه دسترسی دارد.", show_alert=True)
        raise CancelHandler()

    def start_kb():
        from runtime.final_private_ui import start_keyboard
        return start_keyboard()

    def mgmt_kb():
        from runtime.final_private_ui import management_keyboard
        return management_keyboard()

    def report():
        from runtime.final_private_ui import management_report
        return management_report(app)

    async def management_back(c):
        await allowed(c)
        current = (getattr(c.message, "text", None) or "").strip()
        if current.startswith("🛠 <b>مدیریت بازی</b>"):
            await c.message.edit_text("🎭 <b>Mafia Nights</b>\n\nیک گزینه را انتخاب کنید:", reply_markup=start_kb(), parse_mode="HTML")
        else:
            await c.message.edit_text(report(), reply_markup=mgmt_kb(), parse_mode="HTML")
        await c.answer(); raise CancelHandler()

    async def birthday_menu(c):
        await allowed(c)
        gid = next((getattr(app, k, None) for k in ("ALLOWED_GROUP_ID", "GROUP_ID", "group_chat_id") if getattr(app, k, None)), None)
        removed = (getattr(app, "removed_players", {}) or {}).get(int(gid), {}) if gid else {}
        if not removed:
            await c.answer("🚫 لیست بازیکنان حذف‌شده خالی است.", show_alert=True); raise CancelHandler()
        kb = InlineKeyboardMarkup(row_width=1)
        for seat, info in sorted(removed.items(), key=lambda x: int(x[0])):
            kb.add(InlineKeyboardButton(f"🎂 {int(seat)}. {info.get('name') or info.get('id')}", callback_data=f"finalgm:birthday:{int(seat)}"))
        kb.add(InlineKeyboardButton("⬅️ مدیریت بازی", callback_data="finalgm:back"))
        await c.message.edit_text("🎂 <b>تولد بازیکن</b>\n\nبازیکن حذف‌شده را برای بازگرداندن انتخاب کنید:", reply_markup=kb, parse_mode="HTML")
        await c.answer(); raise CancelHandler()

    async def birthday_restore(c):
        await allowed(c)
        try: seat = int(str(c.data).rsplit(":", 1)[1])
        except Exception: await c.answer("⚠️ صندلی نامعتبر است.", show_alert=True); raise CancelHandler()
        gid = next((getattr(app, k, None) for k in ("ALLOWED_GROUP_ID", "GROUP_ID", "group_chat_id") if getattr(app, k, None)), None)
        removed_all = getattr(app, "removed_players", {}) or {}; removed = removed_all.get(int(gid), {}) if gid else {}; info = removed.get(seat)
        if info is None: await c.answer("⚠️ بازیکن حذف‌شده پیدا نشد.", show_alert=True); raise CancelHandler()
        slots = getattr(app, "player_slots", {}) or {}
        if seat in slots or int(info.get("id")) in slots.values(): await c.answer("⚠️ صندلی یا بازیکن در حال حاضر درگیر است.", show_alert=True); raise CancelHandler()
        uid = int(info.get("id")); slots[seat] = uid
        if not isinstance(getattr(app, "players", None), dict): app.players = {}
        app.players[uid] = info.get("name") or f"بازیکن {uid}"
        removed.pop(seat, None)
        if info.get("role"):
            app.last_role_map = getattr(app, "last_role_map", {}) or {}; app.last_role_map[uid] = info["role"]
        try:
            authority = (getattr(app, "_persistent_state_authority", None) or {}).get("authority")
            if authority and gid: authority.capture_compatibility_mutations(int(gid))
        except Exception: pass
        await c.answer("✅ بازیکن با شماره قبلی بازگردانده شد.")
        await c.message.edit_text("🎂 <b>بازیکن بازگردانده شد</b>\n\n" f"{html.escape(str(info.get('name') or uid))} دوباره با صندلی <b>{seat}</b> وارد بازی شد.", reply_markup=mgmt_kb(), parse_mode="HTML")
        raise CancelHandler()

    async def moderator_menu(c):
        await allowed(c)
        gid = getattr(app, "ALLOWED_GROUP_ID", None) or getattr(app, "GROUP_ID", None) or getattr(app, "group_chat_id", None)
        if not gid: await c.answer("⚠️ گروه بازی تنظیم نشده است.", show_alert=True); raise CancelHandler()
        try: admins = await app.bot.get_chat_administrators(int(gid))
        except Exception: admins = []
        kb = InlineKeyboardMarkup(row_width=1)
        for admin in admins: kb.add(InlineKeyboardButton(admin.user.full_name or str(admin.user.id), callback_data=f"finalgm:moderator:{admin.user.id}"))
        kb.add(InlineKeyboardButton("⬅️ مدیریت بازی", callback_data="finalgm:back"))
        await c.message.edit_text("🎩 <b>تغییر گرداننده</b>\n\nگرداننده جدید را انتخاب کنید:", reply_markup=kb, parse_mode="HTML"); await c.answer(); raise CancelHandler()

    async def moderator_set(c):
        await allowed(c)
        try: uid = int(str(c.data).rsplit(":", 1)[1])
        except Exception: await c.answer("گرداننده نامعتبر است.", show_alert=True); raise CancelHandler()
        gid = getattr(app, "ALLOWED_GROUP_ID", None) or getattr(app, "GROUP_ID", None) or getattr(app, "group_chat_id", None)
        try: admins = {a.user.id for a in await app.bot.get_chat_administrators(int(gid))} if gid else set()
        except Exception: admins = set()
        if uid not in admins: await c.answer("گرداننده باید مدیر گروه باشد.", show_alert=True); raise CancelHandler()
        app.moderator_id = uid
        await c.message.edit_text(report(), reply_markup=mgmt_kb(), parse_mode="HTML"); await c.answer("✅ گرداننده تغییر کرد"); raise CancelHandler()

    async def scenarios(c):
        await allowed(c)
        manager = getattr(app, "_private_scenario_manager", None)
        if manager:
            await manager.menu(c)
        else:
            from runtime.final_private_ui import scenario_keyboard
            await c.message.edit_text("⚙️ <b>مدیریت سناریو</b>\n\nاز گزینه‌های زیر استفاده کنید:", reply_markup=scenario_keyboard(), parse_mode="HTML"); await c.answer()
        raise CancelHandler()

    regs = [
        (management_back, lambda c: c.data == "finalgm:back"),
        (birthday_menu, lambda c: c.data == "finalgm:birthday"),
        (birthday_restore, lambda c: str(c.data or "").startswith("finalgm:birthday:")),
        (moderator_menu, lambda c: c.data == "finalgm:moderator"),
        (moderator_set, lambda c: str(c.data or "").startswith("finalgm:moderator:")),
        (scenarios, lambda c: c.data == "final:scenarios"),
    ]
    for fn, filt in regs:
        dp.register_callback_query_handler(fn, filt, state="*")

    # Put only these exact routes at the very front. Other management features
    # keep their existing handlers and therefore remain available.
    current = getattr(getattr(dp, "callback_query_handlers", None), "handlers", [])
    own = [h for h in current if getattr(getattr(h, "handler", None), "__name__", "") in {getattr(fn, "__name__", "") for fn, _ in regs}]
    for h in own:
        if h in current: current.remove(h)
    current[0:0] = own
    app._private_ui_hotfix_installed = True
    return True
