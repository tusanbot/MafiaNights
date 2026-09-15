"""Final private UI routing fixes.

This layer owns ambiguous private callbacks and keeps navigation in the
current Telegram message whenever possible. Profile actions are delegated to
the canonical profile/advanced-profile implementations.
"""
from __future__ import annotations

import html
import logging

from aiogram.dispatcher.handler import CancelHandler
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import text

from runtime.scenario_management_v2 import ScenarioForm


def _private(c):
    return bool(getattr(c, "message", None) and c.message.chat.type == "private")


async def _finish(state):
    try:
        await state.finish()
    except Exception:
        pass


async def _edit_or_answer(message, body, reply_markup=None, parse_mode="HTML"):
    try:
        await message.edit_text(body, reply_markup=reply_markup, parse_mode=parse_mode)
        return
    except Exception as exc:
        if "Message is not modified" in str(exc):
            return
        logging.exception("private UI edit failed")
        try:
            await message.answer(body, reply_markup=reply_markup, parse_mode=parse_mode)
        except Exception:
            logging.exception("private UI fallback message failed")


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
        await _edit_or_answer(c.message, "🎭 <b>Mafia Nights</b>\n\nیک گزینه را انتخاب کنید:", start_keyboard())
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
                logging.exception("private v6 profile renderer failed")
        uid = int(c.from_user.id)
        row = {}
        games = 0
        try:
            with enhancement._session() as s:
                row = dict(s.execute(text("select id,username,first_name,last_name,nickname,gender from public.mafia_players where id=:id"), {"id": uid}).mappings().first() or {})
                games = int(s.execute(text("select count(*) from public.mafia_game_players where player_id=:id"), {"id": uid}).scalar() or 0)
        except Exception:
            logging.exception("private v6 profile fallback query failed")
        name = row.get("nickname") or " ".join(x for x in ((row.get("first_name") or c.from_user.first_name or "").strip(), (row.get("last_name") or c.from_user.last_name or "").strip()) if x) or c.from_user.full_name or "❓"
        gender = "دختر 👩" if row.get("gender") == "female" else "پسر 👨" if row.get("gender") == "male" else "تعیین نشده"
        kb = InlineKeyboardMarkup(row_width=2).add(
            InlineKeyboardButton("📊 آمار و امتیازات", callback_data="profile:advanced"),
            InlineKeyboardButton("⚧ جنسیت", callback_data="profile:gender"),
            InlineKeyboardButton("⚙️ تنظیمات پروفایل", callback_data="profile:settings"),
            InlineKeyboardButton("⬅️ پنل اصلی", callback_data="up:menu"),
        )
        body = ("👤 <b>پروفایل من</b>\n\n"
                f"نام: <b>{html.escape(str(name))}</b>\n"
                f"جنسیت: <b>{gender}</b>\n"
                f"نام کاربری: @{html.escape(str(row.get('username'))) if row.get('username') else (html.escape(c.from_user.username) if c.from_user.username else '—')}\n"
                f"شناسه عددی: <code>{uid}</code>\n"
                f"تعداد بازی: <b>{games}</b>")
        await _edit_or_answer(c.message, body, kb)
        await c.answer()
        raise CancelHandler()

    async def up_menu(c, state):
        if not _private(c):
            raise CancelHandler()
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
                logging.exception("private v6 profile settings renderer failed")
        uid = int(c.from_user.id)
        nickname = "تنظیم نشده"
        gender = "تعیین نشده"
        try:
            with enhancement._session() as s:
                row = s.execute(text("select nickname,gender from public.mafia_players where id=:id"), {"id": uid}).mappings().first() or {}
                nickname = row.get("nickname") or nickname
                gender = "دختر 👩" if row.get("gender") == "female" else "پسر 👨" if row.get("gender") == "male" else gender
        except Exception:
            logging.exception("private v6 profile settings fallback failed")
        kb = InlineKeyboardMarkup(row_width=1).add(
            InlineKeyboardButton(f"⚧ جنسیت: {gender}", callback_data="profile:gender"),
            InlineKeyboardButton("✏️ تغییر نام مستعار", callback_data="profile:nickname"),
            InlineKeyboardButton("🔁 انتقال حساب من", callback_data="profile:transfer"),
            InlineKeyboardButton("⬅️ پروفایل", callback_data="up:profile"),
        )
        await _edit_or_answer(c.message, "⚙️ <b>تنظیمات پروفایل</b>\n\n" f"نام مستعار: <b>{html.escape(str(nickname))}</b>", kb)
        await c.answer()
        raise CancelHandler()

    async def management_back(c, state):
        await home(c, state)

    async def scenario_menu(c, state):
        if not _private(c):
            raise CancelHandler()
        await _finish(state)
        manager = getattr(app, "_private_scenario_manager", None)
        if manager is None:
            await c.answer("❌ مدیریت سناریو در دسترس نیست.", show_alert=True)
            raise CancelHandler()
        try:
            await manager.menu(c, state)
        except CancelHandler:
            raise
        except Exception:
            logging.exception("private v6 scenario menu failed")
            await c.answer("❌ بازگشت به مدیریت سناریو انجام نشد.", show_alert=True)
        raise CancelHandler()

    async def scenario_back(c, state):
        await scenario_menu(c, state)

    async def scenario_keep(c, state):
        if not _private(c):
            raise CancelHandler()
        manager = getattr(app, "_private_scenario_manager", None)
        if manager is None:
            await c.answer("❌ مدیریت سناریو در دسترس نیست.", show_alert=True); raise CancelHandler()
        uid = int(c.from_user.id)
        session = getattr(manager, "sessions", {}).get(uid)
        if not session or session.get("mode") != "edit":
            await c.answer("⚠️ فرم ویرایش منقضی شده است.", show_alert=True); raise CancelHandler()
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
                    role, side = p[0].strip(), p[1].strip(); roles.append(role); sides[role] = side
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
        await c.answer("بدون تغییر ثبت شد"); raise CancelHandler()

    async def scenario_save(c, state):
        if not _private(c):
            raise CancelHandler()
        manager = getattr(app, "_private_scenario_manager", None)
        if manager is None:
            await c.answer("❌ مدیریت سناریو در دسترس نیست.", show_alert=True); raise CancelHandler()
        uid = int(c.from_user.id); session = getattr(manager, "sessions", {}).get(uid)
        if not session:
            await c.answer("⚠️ فرم منقضی شده است.", show_alert=True); raise CancelHandler()
        data = session.get("data") or {}; roles = list(data.get("roles") or []); sides = dict(data.get("sides") or {})
        if not sides:
            for line in data.get("role_lines") or []:
                p = str(line).rsplit(None, 1)
                if len(p) == 2: sides[p[0].strip()] = p[1].strip()
        missing = [r for r in roles if r not in sides]
        if missing:
            await c.answer("⚠️ ساید نقش‌ها کامل نیست.", show_alert=True); raise CancelHandler()
        mode = data.get("challenge_mode") or (data.get("config") or {}).get("challenge_mode") or "limited"
        settings = dict(data.get("settings") or manager.DEFAULTS)
        old_cfg = data.get("config") or {}; old_limit = old_cfg.get("challenge_limit", 1) if isinstance(old_cfg, dict) else 1
        cfg = {"roles": {r: {"side": sides[r], "challenge": mode} for r in roles}, "sides": sides, "challenge_mode": mode, "challenge_limit": old_limit if mode == "limited" else None, "settings": settings}
        try:
            if session.get("mode") == "edit":
                sid = manager.repo.update_by_id(session["id"], data.get("name"), data.get("description"), data.get("min_players"), data.get("max_players"), roles, cfg, True)
            else:
                sid = manager.repo.upsert(data.get("name"), data.get("description"), data.get("min_players"), data.get("max_players"), roles, cfg, True)
            manager.sessions.pop(uid, None); await state.finish(); row = manager.repo.get_by_id(sid)
            kb = InlineKeyboardMarkup(row_width=1).add(InlineKeyboardButton("⚙️ مدیریت سناریو", callback_data="final:scenarios"), InlineKeyboardButton("⬅️ پنل اصلی", callback_data="final:start"))
            await _edit_or_answer(c.message, "✅ <b>سناریو ذخیره شد.</b>\n\n" + manager._summary(row), kb); await c.answer("ذخیره شد")
        except Exception:
            logging.exception("private v6 scenario save failed")
            await c.answer("❌ ذخیره سناریو انجام نشد.", show_alert=True)
        raise CancelHandler()

    async def advanced_dispatch(c, state):
        if not _private(c):
            raise CancelHandler()
        enhancement = getattr(app, "profile_enhancements", None)
        advanced = getattr(enhancement, "advanced_profile", None) if enhancement else None
        if advanced is None:
            await c.answer("❌ بخش آمار در دسترس نیست.", show_alert=True); raise CancelHandler()
        parts = c.data.split(":")
        method_name = "advanced" if len(parts) == 2 else parts[2]
        method = getattr(advanced, method_name, None)
        if method is None:
            await c.answer("❌ این بخش آمار در دسترس نیست.", show_alert=True); raise CancelHandler()
        try:
            await method(c)
        except Exception:
            logging.exception("private v6 advanced profile route failed: %s", c.data)
            await c.answer("❌ نمایش آمار انجام نشد.", show_alert=True)
        raise CancelHandler()

    async def delegate_callback(method_name, c, state):
        enhancement = getattr(app, "profile_enhancements", None)
        if enhancement is None:
            raise CancelHandler()
        method = getattr(enhancement, method_name, None)
        if method is None:
            await c.answer("❌ این گزینه در دسترس نیست.", show_alert=True); raise CancelHandler()
        try:
            await method(c, state) if method_name in {"nickname_prompt", "transfer_prompt"} else await method(c)
        except CancelHandler:
            raise
        except Exception:
            logging.exception("private v6 delegated callback failed: %s", method_name)
            await c.answer("❌ انجام عملیات ناموفق بود.", show_alert=True)
        raise CancelHandler()

    async def gender_menu(c, state): await delegate_callback("gender_menu", c, state)
    async def set_gender(c, state): await delegate_callback("set_gender", c, state)
    async def nickname_prompt(c, state): await delegate_callback("nickname_prompt", c, state)
    async def transfer_prompt(c, state): await delegate_callback("transfer_prompt", c, state)
    async def transfer_confirm(c, state): await delegate_callback("transfer_confirm", c, state)
    async def transfer_cancel(c, state): await delegate_callback("transfer_cancel", c, state)

    async def nickname_save(message, state):
        enhancement = getattr(app, "profile_enhancements", None)
        if enhancement is None: return
        value = enhancement._normalize(message.text or "")
        if value == "حذف": nickname = None
        elif enhancement._valid_nickname(value): nickname = value
        else:
            await message.answer("❌ نام مستعار نامعتبر است. فقط حروف فارسی و فاصله مجاز است و حداکثر ۳۲ نویسه می‌تواند باشد."); return
        try:
            with enhancement._session() as s:
                s.execute(text("""update public.mafia_players set nickname=:nickname,updated_at=now() where id=:id"""), {"id": int(message.from_user.id), "nickname": nickname})
                s.commit()
            enhancement._invalidate(message.from_user.id); await state.finish(); await message.answer("✅ نام مستعار ذخیره شد." if nickname else "✅ نام مستعار حذف شد.")
        except Exception:
            logging.exception("private v6 nickname save failed")
            try: await state.finish()
            except Exception: pass
            await message.answer("❌ ذخیره نام مستعار انجام نشد. خطای پایگاه‌داده رخ داد.")

    regs = [
        (management_back, lambda c: c.data == "finalgm:back"),
        (scenario_menu, lambda c: c.data == "sm2:menu"),
        (scenario_back, lambda c: c.data == "final:start"),
        (up_menu, lambda c: c.data == "up:menu"),
        (profile, lambda c: c.data == "up:profile"),
        (profile_settings, lambda c: c.data == "profile:settings"),
        (advanced_dispatch, lambda c: c.data == "profile:advanced" or c.data.startswith("profile:advanced:")),
        (gender_menu, lambda c: c.data == "profile:gender"),
        (set_gender, lambda c: c.data in {"profile:gender:female", "profile:gender:male"}),
        (nickname_prompt, lambda c: c.data == "profile:nickname"),
        (transfer_prompt, lambda c: c.data == "profile:transfer"),
        (transfer_confirm, lambda c: c.data == "profile:transfer:confirm"),
        (transfer_cancel, lambda c: c.data == "profile:transfer:cancel"),
        (scenario_keep, lambda c: c.data == "sm5:keep"),
        (scenario_save, lambda c: c.data == "sm5:save"),
    ]
    for fn, filt in regs:
        dp.register_callback_query_handler(fn, filt, state="*")
    try:
        from runtime.profile_enhancements import ProfileStates
        dp.register_message_handler(nickname_save, state=ProfileStates.waiting_nickname)
    except Exception:
        logging.exception("private v6 nickname handler registration failed")

    wanted = {fn for fn, _ in regs}; current = list(cq); matches = [h for h in current if getattr(h, "handler", None) in wanted]; cq[:] = matches + [h for h in current if h not in matches]
    if mh is not None:
        owned = [h for h in list(mh) if getattr(getattr(h, "handler", None), "__name__", "") == "nickname_save"]
        if owned: mh[:] = owned + [h for h in mh if h not in owned]
    app._private_ui_recovery_v6 = True
    logging.info("PRIVATE UI RECOVERY V6 ACTIVE")
    return True
