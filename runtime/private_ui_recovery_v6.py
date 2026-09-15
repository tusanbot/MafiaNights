"""Last-mile private UI and profile/scenario persistence fixes.

Installed after all previous private UI generations. This layer deliberately
owns only the callbacks that still have ambiguous/legacy routing.
"""
from __future__ import annotations

import html
import logging

from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.handler import CancelHandler
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.exceptions import MessageNotModified
from sqlalchemy import text

from runtime.scenario_management_v2 import ScenarioForm


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
    mh = getattr(getattr(dp, "message_handlers", None), "handlers", None)
    if cq is None or getattr(app, "_private_ui_recovery_v6", False):
        return False

    async def home(c, state):
        if not _private(c):
            raise CancelHandler()
        await _finish(state)
        from runtime.final_private_ui import start_keyboard
        try:
            await c.message.edit_text("🎭 <b>Mafia Nights</b>\n\nیک گزینه را انتخاب کنید:", reply_markup=start_keyboard(), parse_mode="HTML")
        except Exception:
            await c.message.answer("🎭 <b>Mafia Nights</b>\n\nیک گزینه را انتخاب کنید:", reply_markup=start_keyboard(), parse_mode="HTML")
        await c.answer()
        raise CancelHandler()

    async def profile(c, state):
        if not _private(c):
            raise CancelHandler()
        await _finish(state)
        enhancement = getattr(app, "profile_enhancements", None)
        if enhancement is not None:
            try:
                await enhancement.profile(c)
                raise CancelHandler()
            except CancelHandler:
                raise
            except Exception:
                logging.exception("private v6 profile enhancement failed")
        uid = int(c.from_user.id)
        row = {}
        if enhancement is not None:
            try:
                with enhancement._session() as s:
                    row = dict(s.execute(text("select id,username,first_name,last_name,nickname from public.mafia_players where id=:id"), {"id": uid}).mappings().first() or {})
            except Exception:
                logging.exception("private v6 profile fallback query failed")
        name = row.get("nickname") or " ".join(x for x in ((row.get("first_name") or c.from_user.first_name or "").strip(), (row.get("last_name") or c.from_user.last_name or "").strip()) if x) or c.from_user.full_name or "❓"
        kb = InlineKeyboardMarkup(row_width=2).add(
            InlineKeyboardButton("⚙️ تنظیمات پروفایل", callback_data="profile:settings"),
            InlineKeyboardButton("⬅️ پنل اصلی", callback_data="up:menu"),
        )
        await c.message.edit_text("👤 <b>پروفایل من</b>\n\n" f"نام: <b>{html.escape(str(name))}</b>\n" f"نام کاربری: @{html.escape(str(row.get('username'))) if row.get('username') else (html.escape(c.from_user.username) if c.from_user.username else '—')}\n" f"شناسه عددی: <code>{uid}</code>", reply_markup=kb, parse_mode="HTML")
        await c.answer()
        raise CancelHandler()

    async def up_menu(c, state):
        if not _private(c):
            raise CancelHandler()
        # The legacy main menu used up:menu for the profile button. Distinguish
        # that invocation from the profile's own "پنل اصلی" by the current text.
        current = (c.message.text or "") if c.message else ""
        if "Mafia Nights" in current and "یک گزینه را انتخاب کنید" in current:
            await profile(c, state)
        await home(c, state)

    async def profile_settings(c, state):
        if not _private(c):
            raise CancelHandler()
        await _finish(state)
        enhancement = getattr(app, "profile_enhancements", None)
        if enhancement is not None:
            try:
                await enhancement.settings(c)
                raise CancelHandler()
            except CancelHandler:
                raise
            except Exception:
                logging.exception("private v6 profile settings enhancement failed")
        uid = int(c.from_user.id)
        nickname = "تنظیم نشده"
        if enhancement is not None:
            try:
                with enhancement._session() as s:
                    row = s.execute(text("select nickname from public.mafia_players where id=:id"), {"id": uid}).mappings().first()
                    nickname = (row or {}).get("nickname") or nickname
            except Exception:
                pass
        kb = InlineKeyboardMarkup(row_width=1).add(
            InlineKeyboardButton("✏️ تغییر نام مستعار", callback_data="profile:nickname"),
            InlineKeyboardButton("🔁 انتقال حساب من", callback_data="profile:transfer"),
            InlineKeyboardButton("⬅️ پروفایل", callback_data="up:profile"),
            InlineKeyboardButton("⬅️ پنل اصلی", callback_data="up:menu"),
        )
        await c.message.edit_text("⚙️ <b>تنظیمات پروفایل</b>\n\n" f"نام مستعار: <b>{html.escape(str(nickname))}</b>", reply_markup=kb, parse_mode="HTML")
        await c.answer()
        raise CancelHandler()

    async def management_back(c, state):
        await _finish(state)
        from runtime.final_private_ui import management_report, management_keyboard
        try:
            await c.message.edit_text(management_report(app), reply_markup=management_keyboard(), parse_mode="HTML")
        except Exception:
            logging.exception("private v6 management back edit failed; sending fallback")
            await c.message.answer(management_report(app), reply_markup=management_keyboard(), parse_mode="HTML")
        await c.answer()
        raise CancelHandler()

    async def scenario_back(c, state):
        await home(c, state)

    async def scenario_keep(c, state):
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
        current = str(await state.get_state() or "")
        data = session.setdefault("data", {})
        if current.endswith(":name"):
            await c.message.answer("📖 توضیح سناریو را وارد کنید؛ برای حفظ مقدار فعلی دکمه «بدون تغییر» را بزنید.", reply_markup=manager.keep_kb()); await ScenarioForm.description.set()
        elif current.endswith(":description"):
            await c.message.answer("👥 حداقل تعداد بازیکنان را وارد کنید.", reply_markup=manager.keep_kb()); await ScenarioForm.min_players.set()
        elif current.endswith(":min_players"):
            data["min_players"] = int(data.get("min_players") or 1); await c.message.answer("👥 حداکثر تعداد بازیکنان را وارد کنید.", reply_markup=manager.keep_kb()); await ScenarioForm.max_players.set()
        elif current.endswith(":max_players"):
            data["max_players"] = int(data.get("max_players") or data.get("min_players") or 1); await c.message.answer("🎭 نقش و ساید را وارد کنید؛ برای حفظ مقدار فعلی دکمه «بدون تغییر» را بزنید.", reply_markup=manager.keep_kb()); await ScenarioForm.roles.set()
        elif current.endswith(":roles"):
            lines = list(data.get("role_lines") or [])
            roles, sides = [], {}
            for line in lines:
                p = str(line).rsplit(None, 1)
                if len(p) == 2:
                    role, side = p[0].strip(), p[1].strip()
                    roles.append(role); sides[role] = side
            data["roles"] = roles or list(data.get("roles") or [])
            data["sides"] = sides or dict(data.get("sides") or {})
            cfg = data.get("config") or {}; old = cfg.get("settings") or {}; settings = dict(manager.DEFAULTS)
            if isinstance(old, dict):
                for key in settings:
                    if key in old: settings[key] = bool(old[key])
            data["settings"] = settings
            await manager._show_settings(c.message, settings); await ScenarioForm.settings.set()
        else:
            await c.answer("⚠️ این دکمه در این مرحله قابل استفاده نیست.", show_alert=True); raise CancelHandler()
        await c.answer("بدون تغییر ثبت شد")
        raise CancelHandler()

    async def scenario_save(c, state):
        if not _private(c):
            raise CancelHandler()
        manager = getattr(app, "_private_scenario_manager", None)
        if manager is None:
            await c.answer("❌ مدیریت سناریو در دسترس نیست.", show_alert=True); raise CancelHandler()
        uid = int(c.from_user.id); session = getattr(manager, "sessions", {}).get(uid)
        if not session:
            await c.answer("⚠️ فرم منقضی شده است.", show_alert=True); raise CancelHandler()
        data = session.get("data") or {}
        roles = list(data.get("roles") or [])
        sides = dict(data.get("sides") or {})
        if not sides:
            for line in data.get("role_lines") or []:
                p = str(line).rsplit(None, 1)
                if len(p) == 2:
                    sides[p[0].strip()] = p[1].strip()
        missing = [r for r in roles if r not in sides]
        if missing:
            await c.answer("⚠️ ساید نقش‌ها کامل نیست.", show_alert=True); raise CancelHandler()
        mode = data.get("challenge_mode") or (data.get("config") or {}).get("challenge_mode") or "limited"
        settings = dict(data.get("settings") or manager.DEFAULTS)
        cfg = {"roles": {r: {"side": sides[r], "challenge": mode} for r in roles}, "sides": sides, "challenge_mode": mode, "challenge_limit": 1 if mode == "limited" else None, "settings": settings}
        try:
            if session.get("mode") == "edit":
                sid = manager.repo.update_by_id(session["id"], data.get("name"), data.get("description"), data.get("min_players"), data.get("max_players"), roles, cfg, True)
            else:
                sid = manager.repo.upsert(data.get("name"), data.get("description"), data.get("min_players"), data.get("max_players"), roles, cfg, True)
            manager.sessions.pop(uid, None); await state.finish()
            row = manager.repo.get_by_id(sid)
            await c.message.edit_text("✅ سناریو ذخیره شد.\n\n" + manager._summary(row), parse_mode="HTML")
            await c.answer("ذخیره شد")
        except Exception as exc:
            logging.exception("private v6 scenario save failed")
            await c.answer("❌ ذخیره سناریو انجام نشد.", show_alert=True)
            await c.message.answer("❌ ذخیره سناریو انجام نشد؛ خطای پایگاه‌داده یا ساختار داده رخ داد.")
        raise CancelHandler()

    async def nickname_save(message, state):
        enhancement = getattr(app, "profile_enhancements", None)
        if enhancement is None:
            return
        value = enhancement._normalize(message.text or "")
        if value == "حذف": nickname = None
        elif enhancement._valid_nickname(value): nickname = value
        else:
            await message.answer("❌ نام مستعار نامعتبر است. فقط حروف فارسی و فاصله مجاز است و حداکثر ۳۲ نویسه می‌تواند باشد."); return
        try:
            with enhancement._session() as s:
                s.execute(text("""insert into public.mafia_players
                    (id,username,first_name,last_name,nickname,created_at,updated_at)
                    values (:id,:username,:first_name,:last_name,:nickname,now(),now())
                    on conflict (id) do update set
                    username=coalesce(excluded.username,public.mafia_players.username),
                    first_name=coalesce(excluded.first_name,public.mafia_players.first_name),
                    last_name=coalesce(excluded.last_name,public.mafia_players.last_name),
                    nickname=excluded.nickname,updated_at=now()"""), {"id": int(message.from_user.id), "username": message.from_user.username, "first_name": message.from_user.first_name, "last_name": message.from_user.last_name, "nickname": nickname})
                s.commit()
            enhancement._invalidate(message.from_user.id); await state.finish()
            await message.answer("✅ نام مستعار ذخیره شد." if nickname else "✅ نام مستعار حذف شد.")
        except Exception:
            logging.exception("private v6 nickname save failed")
            await message.answer("❌ ذخیره نام مستعار انجام نشد. خطای پایگاه‌داده رخ داد.")

    regs = [
        (management_back, lambda c: c.data == "finalgm:back"),
        (up_menu, lambda c: c.data == "up:menu"),
        (profile, lambda c: c.data == "up:profile"),
        (profile_settings, lambda c: c.data == "profile:settings"),
        (scenario_back, lambda c: c.data == "final:start"),
        (scenario_keep, lambda c: c.data == "sm5:keep"),
        (scenario_save, lambda c: c.data == "sm5:save"),
    ]
    for fn, filt in regs:
        dp.register_callback_query_handler(fn, filt, state="*")
    dp.register_message_handler(nickname_save, state=getattr(__import__('runtime.profile_enhancements', fromlist=['ProfileStates']), 'ProfileStates').waiting_nickname)

    wanted = {fn for fn, _ in regs}
    current = list(cq)
    matches = [h for h in current if getattr(h, "handler", None) in wanted]
    cq[:] = matches + [h for h in current if h not in matches]
    if mh is not None:
        owned = [h for h in list(mh) if getattr(getattr(h, "handler", None), "__name__", "") == "nickname_save"]
        # Keep our FSM handler ahead of the generic profile FSM handler.
        if owned: mh[:] = owned + [h for h in mh if h not in owned]
    app._private_ui_recovery_v6 = True
    logging.info("PRIVATE UI RECOVERY V6 ACTIVE")
    return True
