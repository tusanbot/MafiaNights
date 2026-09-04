"""Final import-time router for private navigation on webhook runtimes.

This module is the webhook-safe authority for private navigation. It deliberately
keeps navigation independent from the async startup hook and avoids delegating
simple back actions to competing legacy handlers.
"""
from __future__ import annotations

import html
import logging

from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.handler import CancelHandler
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


class EditScenario(StatesGroup):
    waiting_for_roles = State()
    waiting_for_min_players = State()


def install(app):
    dp = app.dp
    cq = getattr(getattr(dp, "callback_query_handlers", None), "handlers", [])
    mh = getattr(getattr(dp, "message_handlers", None), "handlers", [])

    if getattr(app, "_private_navigation_authority_installed", False):
        return False

    def is_private(item):
        return bool(item.message and item.message.chat.type == "private")

    def handler_fn(item):
        return getattr(item, "handler", None) or getattr(item, "callback", None)

    async def allowed(callback):
        """Authorize using cached group/moderator data first.

        Never query Telegram with a possibly stale/private group id when cached
        authorization is already available. This also avoids the recurring
        `There are no administrators in the private chat` failure.
        """
        if not is_private(callback):
            raise CancelHandler()
        uid = int(callback.from_user.id)

        moderator = getattr(app, "moderator_id", None)
        if moderator is not None and uid == int(moderator):
            return True

        cached = set()
        for obj in (app, getattr(app, "addons", None)):
            for key in ("admins", "group_admins"):
                value = getattr(obj, key, None)
                if value:
                    try:
                        cached.update(int(x) for x in value)
                    except (TypeError, ValueError):
                        pass
        if uid in cached:
            return True

        # Only use the configured group id as a last resort. Never use a
        # runtime group_chat_id here because it can be contaminated by private UI.
        gid = getattr(app, "ALLOWED_GROUP_ID", None)
        if gid:
            try:
                admins = await app.bot.get_chat_administrators(int(gid))
                if uid in {int(a.user.id) for a in admins}:
                    return True
            except Exception:
                logging.exception("private navigation: configured-group admin lookup failed")

        await callback.answer("⛔ فقط گرداننده یا مدیر گروه دسترسی دارد.", show_alert=True)
        raise CancelHandler()

    def start_keyboard():
        from runtime.final_private_ui import start_keyboard as _start_keyboard
        return _start_keyboard()

    def management_keyboard():
        from runtime.final_private_ui import management_keyboard as _management_keyboard
        return _management_keyboard()

    def scenario_keyboard():
        kb = InlineKeyboardMarkup(row_width=1)
        kb.add(
            InlineKeyboardButton("➕ افزودن سناریو", callback_data="private_scenario:add"),
            InlineKeyboardButton("➖ حذف سناریو", callback_data="private_scenario:remove"),
            InlineKeyboardButton("✏️ ویرایش سناریو", callback_data="private_scenario:edit"),
            InlineKeyboardButton("📋 لیست سناریوها", callback_data="private_scenario:list"),
            InlineKeyboardButton("⬅️ بازگشت", callback_data="private:start"),
        )
        return kb

    def render_scenarios_text():
        scenarios = getattr(app, "scenarios", {}) or {}
        if not scenarios:
            return "📋 <b>لیست سناریوها</b>\n\nهیچ سناریویی ثبت نشده است."
        lines = ["📋 <b>لیست سناریوها</b>", ""]
        for i, name in enumerate(scenarios.keys(), 1):
            lines.append(f"{i}. {html.escape(str(name))}")
        return "\n".join(lines)

    async def edit_message_or_ignore(message, text, reply_markup=None):
        try:
            await message.edit_text(text, reply_markup=reply_markup, parse_mode="HTML")
        except Exception as exc:
            # Navigation must not fail just because Telegram reports that the
            # requested content is already identical.
            if exc.__class__.__name__ != "MessageNotModified":
                raise

    async def scenarios(callback):
        await allowed(callback)
        await edit_message_or_ignore(
            callback.message,
            "⚙️ <b>مدیریت سناریو</b>\n\nیک گزینه را انتخاب کنید:",
            scenario_keyboard(),
        )
        await callback.answer()
        raise CancelHandler()

    async def private_start(callback):
        if not is_private(callback):
            raise CancelHandler()
        await edit_message_or_ignore(
            callback.message,
            "🎭 <b>Mafia Nights</b>\n\nیک گزینه را انتخاب کنید:",
            start_keyboard(),
        )
        await callback.answer()
        raise CancelHandler()

    async def manage_game_back(callback):
        await allowed(callback)
        await edit_message_or_ignore(
            callback.message,
            "🎭 <b>Mafia Nights</b>\n\nیک گزینه را انتخاب کنید:",
            start_keyboard(),
        )
        await callback.answer()
        raise CancelHandler()

    async def addons_back(callback):
        # The user has already reached the add-ons screen; going back is a pure
        # navigation action and must not perform another admin lookup.
        if not is_private(callback):
            raise CancelHandler()
        await edit_message_or_ignore(
            callback.message,
            "🎭 <b>Mafia Nights</b>\n\nیک گزینه را انتخاب کنید:",
            start_keyboard(),
        )
        await callback.answer()
        raise CancelHandler()

    async def scenario_list(callback):
        await allowed(callback)
        await edit_message_or_ignore(callback.message, render_scenarios_text(), scenario_keyboard())
        await callback.answer()
        raise CancelHandler()

    async def scenario_add(callback):
        await allowed(callback)
        fn = getattr(app, "add_scenario_start", None)
        if not fn:
            await callback.answer("⚠️ افزودن سناریو در runtime فعال نیست.", show_alert=True)
            raise CancelHandler()
        state = await dp.current_state(user=callback.from_user.id, chat=callback.message.chat.id)
        await fn(callback, state)
        await callback.answer()
        raise CancelHandler()

    async def scenario_remove(callback):
        await allowed(callback)
        scenarios = getattr(app, "scenarios", {}) or {}
        if not scenarios:
            await edit_message_or_ignore(
                callback.message,
                "⚠️ هیچ سناریویی ثبت نشده است.",
                scenario_keyboard(),
            )
            await callback.answer()
            raise CancelHandler()
        if len(scenarios) == 1:
            await callback.answer("⚠️ حداقل یک سناریو باید باقی بماند.", show_alert=True)
            raise CancelHandler()
        kb = InlineKeyboardMarkup(row_width=1)
        for i, name in enumerate(scenarios.keys()):
            kb.add(InlineKeyboardButton(str(name), callback_data=f"private_scenario:delete:{i}"))
        kb.add(InlineKeyboardButton("⬅️ مدیریت سناریو", callback_data="final:scenarios"))
        await edit_message_or_ignore(callback.message, "سناریوی موردنظر را برای حذف انتخاب کنید:", kb)
        await callback.answer()
        raise CancelHandler()

    async def scenario_delete(callback):
        await allowed(callback)
        scenarios = getattr(app, "scenarios", {}) or {}
        try:
            index = int(str(callback.data).rsplit(":", 1)[1])
            name = list(scenarios.keys())[index]
        except Exception:
            await callback.answer("⚠️ سناریو نامعتبر است.", show_alert=True)
            raise CancelHandler()
        if len(scenarios) <= 1:
            await callback.answer("⚠️ حداقل یک سناریو باید باقی بماند.", show_alert=True)
            raise CancelHandler()
        if getattr(app, "lobby_active", False) or getattr(app, "game_running", False):
            await callback.answer("⛔ هنگام فعال بودن بازی/لابی حذف سناریو مجاز نیست.", show_alert=True)
            raise CancelHandler()
        scenarios.pop(name, None)
        saver = getattr(app, "save_scenarios", None)
        if saver:
            try:
                saver()
            except OSError:
                logging.warning("scenario delete: persistent file is read-only; keeping in-memory state")
        if getattr(app, "selected_scenario", None) == name:
            app.selected_scenario = None
        await edit_message_or_ignore(
            callback.message,
            f"✅ سناریو «{html.escape(str(name))}» حذف شد.",
            scenario_keyboard(),
        )
        await callback.answer()
        raise CancelHandler()

    async def scenario_edit(callback):
        await allowed(callback)
        scenarios = getattr(app, "scenarios", {}) or {}
        if not scenarios:
            await callback.answer("⚠️ هیچ سناریویی برای ویرایش وجود ندارد.", show_alert=True)
            raise CancelHandler()
        kb = InlineKeyboardMarkup(row_width=1)
        for i, name in enumerate(scenarios.keys()):
            kb.add(InlineKeyboardButton(str(name), callback_data=f"private_scenario:edit:{i}"))
        kb.add(InlineKeyboardButton("⬅️ مدیریت سناریو", callback_data="final:scenarios"))
        await edit_message_or_ignore(callback.message, "سناریوی موردنظر را برای ویرایش انتخاب کنید:", kb)
        await callback.answer()
        raise CancelHandler()

    async def scenario_edit_pick(callback):
        await allowed(callback)
        scenarios = getattr(app, "scenarios", {}) or {}
        try:
            index = int(str(callback.data).rsplit(":", 1)[1])
            name = list(scenarios.keys())[index]
            current_roles = scenarios[name].get("roles", []) if isinstance(scenarios[name], dict) else []
        except Exception:
            await callback.answer("⚠️ سناریوی نامعتبر.", show_alert=True)
            raise CancelHandler()
        state = await dp.current_state(user=callback.from_user.id, chat=callback.message.chat.id)
        await state.update_data(edit_scenario_name=name)
        await state.set_state(EditScenario.waiting_for_roles)
        roles_text = ", ".join(str(x) for x in current_roles)
        await callback.message.answer(
            f"✏️ ویرایش «{html.escape(str(name))}»\n\n"
            f"نقش‌های جدید را با کاما جدا کنید.\n"
            f"نقش‌های فعلی: {html.escape(roles_text)}"
        )
        await callback.answer()
        raise CancelHandler()

    async def scenario_edit_roles(message, state: FSMContext):
        roles = [r.strip() for r in (message.text or "").split(",") if r.strip()]
        if not roles:
            await message.answer("⚠️ حداقل یک نقش وارد کنید.")
            return
        await state.update_data(edit_roles=roles)
        await message.answer("🔢 حداقل تعداد بازیکنان را وارد کنید:")
        await state.set_state(EditScenario.waiting_for_min_players)

    async def scenario_edit_min_players(message, state: FSMContext):
        text = (message.text or "").strip()
        if not text.isdigit() or int(text) < 1:
            await message.answer("⚠️ یک عدد معتبر بزرگ‌تر از صفر وارد کنید.")
            return
        data = await state.get_data()
        name = data.get("edit_scenario_name")
        roles = data.get("edit_roles") or []
        scenarios = getattr(app, "scenarios", {}) or {}
        if not name or name not in scenarios:
            await message.answer("⚠️ سناریوی موردنظر دیگر وجود ندارد.")
            await state.finish()
            return
        min_players = int(text)
        scenarios[name] = {
            **(scenarios.get(name) if isinstance(scenarios.get(name), dict) else {}),
            "roles": roles,
            "min_players": min_players,
            "max_players": len(roles),
        }
        saver = getattr(app, "save_scenarios", None)
        persistence_warning = ""
        if saver:
            try:
                saver()
            except OSError:
                persistence_warning = "\n⚠️ فایل روی Vercel قابل‌نوشتن نیست؛ تغییر فعلاً در حافظه runtime اعمال شد."
                logging.warning("scenario edit: persistent file is read-only; keeping in-memory state")
        await message.answer(
            f"✅ سناریو «{html.escape(str(name))}» ویرایش شد.\n\n"
            f"👥 نقش‌ها: {html.escape(', '.join(roles))}\n"
            f"🔢 بازیکنان: {min_players} تا {len(roles)}"
            f"{persistence_warning}"
        )
        await state.finish()

    async def dispatch_final(callback):
        """Materialize final_private_ui and dispatch once without recursive routing."""
        if not is_private(callback):
            raise CancelHandler()
        from runtime import final_private_ui
        await final_private_ui.install(app)

        own = [h for h in list(cq) if handler_fn(h) in {
            dispatch_final, scenarios, private_start, manage_game_back, addons_back,
            scenario_list, scenario_add, scenario_remove, scenario_delete,
            scenario_edit, scenario_edit_pick,
        }]
        try:
            for h in own:
                if h in cq:
                    cq.remove(h)
            await dp.callback_query_handlers.notify(callback)
        finally:
            for h in reversed(own):
                cq.insert(0, h)
        raise CancelHandler()

    async def group_start(message):
        if message.chat.type not in ("group", "supergroup"):
            return
        try:
            app.group_chat_id = int(message.chat.id)
        except Exception:
            return
        try:
            keyboard = app.main_menu_keyboard()
        except Exception:
            keyboard = InlineKeyboardMarkup().add(
                InlineKeyboardButton("🎮 بازی جدید", callback_data="new_game")
            )
        await message.answer(
            "🎭 <b>Mafia Nights</b>\n\nبرای شروع بازی از دکمه زیر استفاده کنید:",
            reply_markup=keyboard,
            parse_mode="HTML",
        )
        raise CancelHandler()

    async def message_edit_roles(message):
        state = await dp.current_state(user=message.from_user.id, chat=message.chat.id)
        current = await state.get_state()
        if current == EditScenario.waiting_for_roles.state:
            await scenario_edit_roles(message, state)
            raise CancelHandler()

    async def message_edit_min_players(message):
        state = await dp.current_state(user=message.from_user.id, chat=message.chat.id)
        current = await state.get_state()
        if current == EditScenario.waiting_for_min_players.state:
            await scenario_edit_min_players(message, state)
            raise CancelHandler()

    # Callback routes owned by this authority.
    registrations = [
        (scenarios, lambda c: c.data == "final:scenarios"),
        (private_start, lambda c: c.data == "private:start"),
        (manage_game_back, lambda c: c.data in {"back_manage_game", "back_main"}),
        (addons_back, lambda c: c.data == "addons:back"),
        (scenario_list, lambda c: c.data == "private_scenario:list"),
        (scenario_add, lambda c: c.data == "private_scenario:add"),
        (scenario_remove, lambda c: c.data == "private_scenario:remove"),
        (scenario_delete, lambda c: str(c.data or "").startswith("private_scenario:delete:")),
        (scenario_edit, lambda c: c.data == "private_scenario:edit"),
        (scenario_edit_pick, lambda c: str(c.data or "").startswith("private_scenario:edit:")),
        (dispatch_final, lambda c: str(c.data or "").startswith("finalgm:") and c.data != "finalgm:back"),
    ]
    for fn, filt in registrations:
        dp.register_callback_query_handler(fn, filt, state="*")

    dp.register_message_handler(message_edit_roles, state=EditScenario.waiting_for_roles)
    dp.register_message_handler(message_edit_min_players, state=EditScenario.waiting_for_min_players)
    dp.register_message_handler(group_start, commands=["start"], state="*")

    owned_callbacks = {
        scenarios, private_start, manage_game_back, addons_back,
        scenario_list, scenario_add, scenario_remove, scenario_delete,
        scenario_edit, scenario_edit_pick, dispatch_final,
    }
    for i in range(len(cq) - 1, -1, -1):
        if handler_fn(cq[i]) in owned_callbacks:
            cq.insert(0, cq.pop(i))
    for i in range(len(mh) - 1, -1, -1):
        if handler_fn(mh[i]) in {group_start, message_edit_roles, message_edit_min_players}:
            mh.insert(0, mh.pop(i))

    app._private_navigation_authority_installed = True
    logging.info("Private navigation authority installed: callbacks=%d messages=%d", len(cq), len(mh))
    return True
