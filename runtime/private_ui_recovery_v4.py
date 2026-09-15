"""Last-priority private UI fixes for navigation, profile fallbacks, and scenario keep buttons."""
from __future__ import annotations

import html
import logging
from aiogram.dispatcher.handler import CancelHandler
from aiogram.dispatcher import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import text


def _private(c):
    return bool(c.message and c.message.chat.type == "private")


async def _finish(state):
    try:
        await state.finish()
    except Exception:
        pass


async def install(app):
    dp = app.dp
    cq = getattr(getattr(dp, "callback_query_handlers", None), "handlers", None)
    if cq is None or getattr(app, "_private_ui_recovery_v4", False):
        return False

    async def _allowed(c):
        if not _private(c):
            raise CancelHandler()
        uid = int(c.from_user.id)
        if uid == int(getattr(app, "moderator_id", 0) or 0):
            return
        admins = set()
        for obj in (app, getattr(app, "addons", None)):
            for attr in ("admins", "group_admins"):
                for item in getattr(obj, attr, None) or []:
                    try:
                        admins.add(int(getattr(getattr(item, "user", None), "id", item)))
                    except Exception:
                        pass
        if uid in admins:
            return
        gid = getattr(app, "ALLOWED_GROUP_ID", None) or getattr(app, "GROUP_ID", None) or getattr(app, "group_chat_id", None)
        if gid:
            try:
                ids = {int(x.user.id) for x in await app.bot.get_chat_administrators(int(gid))}
                app.admins = ids
                app.group_admins = list(ids)
                if uid in ids:
                    return
            except Exception:
                logging.exception("private recovery v4 admin lookup failed")
        await c.answer("⛔ فقط گرداننده یا مدیر گروه دسترسی دارد.", show_alert=True)
        raise CancelHandler()

    async def management_back(c, state: FSMContext):
        await _allowed(c)
        await _finish(state)
        from runtime.final_private_ui import management_report, management_keyboard
        await c.message.edit_text(management_report(app), reply_markup=management_keyboard(), parse_mode="HTML")
        await c.answer()
        raise CancelHandler()

    async def main_panel(c, state: FSMContext):
        if not _private(c):
            raise CancelHandler()
        await _finish(state)
        from runtime.final_private_ui import start_keyboard
        await c.message.edit_text("🎭 <b>Mafia Nights</b>\n\nیک گزینه را انتخاب کنید:", reply_markup=start_keyboard(), parse_mode="HTML")
        await c.answer()
        raise CancelHandler()

    def _safe_profile_row(uid):
        enhancement = getattr(app, "profile_enhancements", None)
        if enhancement is None:
            return {}
        try:
            with enhancement._session() as s:
                row = s.execute(text("select id,username,first_name,last_name,nickname from public.mafia_players where id=:id"), {"id": uid}).mappings().first()
                return dict(row) if row else {}
        except Exception:
            logging.exception("private recovery v4 profile row failed")
            return {}

    async def profile(c, state: FSMContext):
        if not _private(c):
            raise CancelHandler()
        await _finish(state)
        enhancement = getattr(app, "profile_enhancements", None)
        try:
            if enhancement is not None:
                await enhancement.profile(c)
                raise CancelHandler()
        except CancelHandler:
            raise
        except Exception:
            logging.exception("private recovery v4 profile enhancement failed")
        uid = int(c.from_user.id)
        row = _safe_profile_row(uid)
        name = row.get("nickname") or " ".join(x for x in ((row.get("first_name") or "").strip(), (row.get("last_name") or "").strip()) if x) or c.from_user.full_name or "❓"
        kb = InlineKeyboardMarkup(row_width=2).add(
            InlineKeyboardButton("⚙️ تنظیمات پروفایل", callback_data="profile:settings"),
            InlineKeyboardButton("⬅️ پنل اصلی", callback_data="up:menu"),
        )
        await c.message.edit_text(
            "👤 <b>پروفایل من</b>\n\n"
            f"نام: <b>{html.escape(str(name))}</b>\n"
            f"نام کاربری: @{html.escape(str(row.get('username'))) if row.get('username') else '—'}\n"
            f"شناسه عددی: <code>{uid}</code>",
            reply_markup=kb, parse_mode="HTML")
        await c.answer()
        raise CancelHandler()

    async def profile_settings(c, state: FSMContext):
        if not _private(c):
            raise CancelHandler()
        await _finish(state)
        enhancement = getattr(app, "profile_enhancements", None)
        try:
            if enhancement is not None:
                await enhancement.settings(c)
                raise CancelHandler()
        except CancelHandler:
            raise
        except Exception:
            logging.exception("private recovery v4 profile settings enhancement failed")
        uid = int(c.from_user.id)
        row = _safe_profile_row(uid)
        nickname = row.get("nickname") or "تنظیم نشده"
        kb = InlineKeyboardMarkup(row_width=1).add(
            InlineKeyboardButton("✏️ تغییر نام مستعار", callback_data="profile:nickname"),
            InlineKeyboardButton("🔁 انتقال حساب من", callback_data="profile:transfer"),
            InlineKeyboardButton("⬅️ پروفایل", callback_data="up:profile"),
            InlineKeyboardButton("⬅️ پنل اصلی", callback_data="up:menu"),
        )
        await c.message.edit_text(
            "⚙️ <b>تنظیمات پروفایل</b>\n\n"
            f"نام مستعار: <b>{html.escape(str(nickname))}</b>\n\n"
            "تنظیمات قابل استفاده از گزینه‌های زیر:",
            reply_markup=kb, parse_mode="HTML")
        await c.answer()
        raise CancelHandler()

    async def scenario_keep(c, state: FSMContext):
        if not _private(c):
            raise CancelHandler()
        manager = getattr(app, "_private_scenario_manager", None)
        if manager is None:
            await c.answer("❌ مدیریت سناریو در دسترس نیست.", show_alert=True)
            raise CancelHandler()
        uid = int(c.from_user.id)
        session = getattr(manager, "sessions", {}).get(uid)
        if not session or session.get("mode") != "edit":
            await c.answer("⚠️ فرم ویرایش منقضی شده است.", show_alert=True)
            raise CancelHandler()
        current = await state.get_state()
        current = str(current or "")
        data = session.setdefault("data", {})
        if current.endswith(":name"):
            await c.message.answer("📖 توضیح سناریو را وارد کنید؛ برای حفظ مقدار فعلی همین دکمه «بدون تغییر» را بزنید.", reply_markup=manager.keep_kb())
            from runtime.scenario_management_v2 import ScenarioForm
            await ScenarioForm.description.set()
        elif current.endswith(":description"):
            data["description"] = data.get("description")
            await c.message.answer("👥 حداقل تعداد بازیکنان را وارد کنید.", reply_markup=manager.keep_kb())
            from runtime.scenario_management_v2 import ScenarioForm
            await ScenarioForm.min_players.set()
        elif current.endswith(":min_players"):
            data["min_players"] = int(data.get("min_players") or 1)
            await c.message.answer("👥 حداکثر تعداد بازیکنان را وارد کنید.", reply_markup=manager.keep_kb())
            from runtime.scenario_management_v2 import ScenarioForm
            await ScenarioForm.max_players.set()
        elif current.endswith(":max_players"):
            data["max_players"] = int(data.get("max_players") or data.get("min_players") or 1)
            await c.message.answer("🎭 نقش و ساید را همزمان وارد کنید؛ هر خط یک مورد. برای حفظ مقدار فعلی دکمه «بدون تغییر» را بزنید.", reply_markup=manager.keep_kb())
            from runtime.scenario_management_v2 import ScenarioForm
            await ScenarioForm.roles.set()
        elif current.endswith(":roles"):
            data["roles"] = list(data.get("roles") or [])
            data["sides"] = dict(data.get("sides") or {})
            cfg = data.get("config") or {}
            old = cfg.get("settings") or {}
            settings = dict(manager.DEFAULTS)
            if isinstance(old, dict):
                for k in settings:
                    if k in old:
                        settings[k] = bool(old[k])
            data["settings"] = settings
            await manager._show_settings(c.message, settings)
            from runtime.scenario_management_v2 import ScenarioForm
            await ScenarioForm.settings.set()
        else:
            await c.answer("⚠️ در این مرحله گزینه «بدون تغییر» کاربرد ندارد.", show_alert=True)
            raise CancelHandler()
        await c.answer("بدون تغییر ثبت شد")
        raise CancelHandler()

    regs = [
        (management_back, lambda c: c.data == "finalgm:back"),
        (main_panel, lambda c: c.data in {"up:menu", "up:profile", "final:start", "private:start"}),
        (profile_settings, lambda c: c.data == "profile:settings"),
        (profile, lambda c: c.data in {"up:profile:open", "profile:open"}),
        (scenario_keep, lambda c: c.data == "sm5:keep"),
    ]
    for fn, filt in regs:
        dp.register_callback_query_handler(fn, filt, state="*")
    wanted = {fn for fn, _ in regs}
    current = list(cq)
    matches = [h for h in current if getattr(h, "handler", None) in wanted]
    cq[:] = matches + [h for h in current if h not in matches]
    app._private_ui_recovery_v4 = True
    logging.info("PRIVATE UI RECOVERY V4 ACTIVE")
    return True
