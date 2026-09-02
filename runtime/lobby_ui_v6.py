from __future__ import annotations

import html
import logging
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def install(main):
    """Authoritative lobby UI layer."""
    dp, bot = main.dp, main.bot
    original_menu = main.main_menu_keyboard
    main._lv6_change_scenario = False
    main._lv6_ready_players = set()

    def front_callback(fn):
        handlers = getattr(dp.callback_query_handlers, "handlers", [])
        for i, h in enumerate(handlers):
            if getattr(h, "callback", None) is fn:
                handlers.insert(0, handlers.pop(i))
                break

    def mention(uid):
        if not uid:
            return "---"
        try:
            name = main.display_name(uid, main.players.get(uid)) or main.players.get(uid) or str(uid)
        except Exception:
            name = main.players.get(uid) or str(uid)
        return f'<a href="tg://user?id={uid}"><b>{html.escape(str(name))}</b></a>'

    async def is_admin(uid):
        if not main.group_chat_id:
            return False
        try:
            return uid in {a.user.id for a in await bot.get_chat_administrators(main.group_chat_id)}
        except Exception:
            return False

    async def edit(message, text, kb=None):
        try:
            await message.edit_text(text, reply_markup=kb, parse_mode="HTML")
            return True
        except Exception as exc:
            logging.warning("lobby edit failed: %s", exc)
            return False

    def menu():
        try:
            src = original_menu()
        except Exception:
            src = InlineKeyboardMarkup()
        out = InlineKeyboardMarkup(row_width=2)
        found = False
        for row in getattr(src, "inline_keyboard", []):
            nr = []
            for b in row:
                text = str(getattr(b, "text", ""))
                if "لیست جدید" in text:
                    continue
                if "بازی جدید" in text:
                    nr.append(InlineKeyboardButton("🎮 بازی جدید", callback_data="lv6_new"))
                    found = True
                else:
                    nr.append(b)
            if nr:
                out.row(*nr)
        if not found:
            out.add(InlineKeyboardButton("🎮 بازی جدید", callback_data="lv6_new"))
        return out

    def scenario_kb(changing=False):
        kb = InlineKeyboardMarkup(row_width=1)
        for i, (scenario, cfg) in enumerate(main.scenarios.items()):
            cfg = cfg or {}
            roles = cfg.get("roles") or []
            kb.add(InlineKeyboardButton(
                f"📝 {scenario} ({cfg.get('min_players', 1)}-{len(roles)})",
                callback_data=f"lv6_s:{i}"
            ))
        kb.add(InlineKeyboardButton(
            "⬅️ بازگشت به لابی" if changing else "⬅️ بازگشت",
            callback_data="lv6_back_lobby" if changing else "lv6_home"
        ))
        return kb

    async def moderator_kb():
        kb = InlineKeyboardMarkup(row_width=1)
        for admin in await bot.get_chat_administrators(main.group_chat_id):
            kb.add(InlineKeyboardButton(admin.user.full_name, callback_data=f"lv6_m:{admin.user.id}"))
        kb.add(InlineKeyboardButton("⬅️ بازگشت به سناریو", callback_data="lv6_back_s"))
        return kb

    def lobby_text():
        cfg = main.scenarios.get(main.selected_scenario) or {}
        capacity = len(cfg.get("roles") or [])
        active = [u for u in main.players if u not in main.waiting_list]
        waiting = [u for u in main.waiting_list if u in main.players]
        lines = [
            "🎮 <b>لابی Mafia Nights</b>", "",
            f"📝 سناریو: <b>{html.escape(str(main.selected_scenario or '---'))}</b>",
            f"🎩 گرداننده: {mention(main.moderator_id) if main.moderator_id else '---'}",
            f"👥 بازیکنان: <b>{len(active)}/{capacity}</b>", "",
            "📋 <b>بازیکنان داخل بازی</b>",
        ]
        if active:
            for uid in sorted(active, key=lambda x: next((s for s, p in main.player_slots.items() if p == x), 999)):
                seat = next((s for s, p in main.player_slots.items() if p == uid), None)
                ready = " ✅" if uid in main._lv6_ready_players else ""
                lines.append(f"{seat:02d}. {mention(uid)}{ready}" if seat else f"▫️ {mention(uid)} — بدون صندلی{ready}")
        else:
            lines.append("— هنوز بازیکنی وارد نشده است.")
        if waiting:
            lines += ["", "🎟 <b>لیست رزرو</b>"]
            lines += [f"{i}. {mention(uid)}" for i, uid in enumerate(waiting, 1)]
        return "\n".join(lines)

    def lobby_kb():
        cfg = main.scenarios.get(main.selected_scenario) or {}
        capacity = len(cfg.get("roles") or [])
        active = [u for u in main.players if u not in main.waiting_list]
        full = capacity > 0 and len(active) >= capacity and all(
            any(p == uid and seat is not None for seat, p in main.player_slots.items()) for uid in active
        )
        kb = InlineKeyboardMarkup(row_width=2)
        kb.add(InlineKeyboardButton("🎮 ورود / خروج از بازی", callback_data="lv6_toggle"))
        kb.add(InlineKeyboardButton("💺 انتخاب صندلی", callback_data="lv6_seat_menu"))
        if full:
            kb.add(InlineKeyboardButton("🎟 رزرو / لغو رزرو", callback_data="lv6_reserve"))
            kb.add(InlineKeyboardButton("🎭 پخش نقش", callback_data="distribute_roles"))
        kb.add(InlineKeyboardButton("⚙️ مدیریت بازی", callback_data="lv6_manage"))
        return kb

    async def render(message):
        await edit(message, lobby_text(), lobby_kb())
        main.lobby_message_id = message.message_id

    async def new(callback):
        main.group_chat_id = callback.message.chat.id
        if main.game_running or main.round_active:
            await callback.answer("⚠️ بازی در حال اجراست.", show_alert=True)
            return
        main.lobby_active = True
        main.selected_scenario = None
        main.moderator_id = None
        main.MAX_SEATS = 0
        main.players.clear(); main.player_slots.clear(); main.waiting_list.clear()
        main._lv6_ready_players.clear()
        main._lv6_setup = True
        main._lv6_change_scenario = False
        await edit(callback.message, "📝 <b>انتخاب سناریو</b>\n\nابتدا سناریوی بازی را انتخاب کنید.", scenario_kb(False))
        await callback.answer()

    async def scenario(callback):
        try:
            index = int(callback.data.split(":", 1)[1])
            selected = list(main.scenarios)[index]
        except Exception:
            await callback.answer("سناریو نامعتبر است.", show_alert=True)
            return
        main.selected_scenario = selected
        main.MAX_SEATS = len((main.scenarios[selected] or {}).get("roles") or [])
        if main._lv6_change_scenario and main.moderator_id:
            main.players.clear(); main.player_slots.clear(); main.waiting_list.clear(); main._lv6_ready_players.clear()
            main._lv6_change_scenario = False
            main._lv6_setup = False
            main.lobby_active = True
            await render(callback.message)
            await callback.answer("✅ سناریو تغییر کرد و لابی به‌روزرسانی شد")
            return
        await edit(callback.message, f"📝 سناریو: <b>{html.escape(main.selected_scenario)}</b>\n\n🎩 <b>انتخاب گرداننده</b>", await moderator_kb())
        await callback.answer("✅ سناریو انتخاب شد")

    async def moderator(callback):
        uid = int(callback.data.split(":", 1)[1])
        if not await is_admin(uid):
            await callback.answer("گرداننده باید مدیر گروه باشد.", show_alert=True)
            return
        main.moderator_id = uid
        main._lv6_setup = False; main._lv6_change_scenario = False
        main.lobby_active = True; main.game_running = False; main.round_active = False
        await render(callback.message)
        await callback.answer("✅ لابی ایجاد شد")

    async def home(callback):
        main._lv6_setup = False; main.lobby_active = False
        await edit(callback.message, "🎮 <b>Mafia Nights</b>\n\nیک گزینه را انتخاب کنید.", menu())
        await callback.answer()

    async def back_s(callback):
        main._lv6_change_scenario = False
        await edit(callback.message, "📝 <b>انتخاب سناریو</b>", scenario_kb(False))
        await callback.answer()

    async def toggle(callback):
        uid = callback.from_user.id
        active = [u for u in main.players if u not in main.waiting_list]
        if uid in main.waiting_list:
            await callback.answer("🎟 شما در رزرو هستید؛ از دکمه رزرو برای لغو استفاده کنید.", show_alert=True); return
        if uid in main.players:
            seat = next((s for s, p in main.player_slots.items() if p == uid), None)
            main.players.pop(uid, None)
            if seat is not None: main.player_slots.pop(seat, None)
            main._lv6_ready_players.discard(uid)
            if main.waiting_list:
                promote = main.waiting_list.pop(0)
                main.player_slots[seat] = promote
            await render(callback.message); await callback.answer("🚪 از بازی خارج شدید"); return
        if len(active) >= int(main.MAX_SEATS or 0):
            await callback.answer("🎟 ظرفیت اصلی پر است؛ رزرو را انتخاب کنید.", show_alert=True); return
        main.players[uid] = callback.from_user.full_name
        await render(callback.message); await callback.answer("✅ وارد بازی شدید")

    async def seat_menu(callback):
        uid = callback.from_user.id
        if uid not in main.players or uid in main.waiting_list:
            await callback.answer("ابتدا وارد بازی شوید.", show_alert=True); return
        kb = InlineKeyboardMarkup(row_width=3)
        occupied = dict(main.player_slots)
        for seat in range(1, int(main.MAX_SEATS or 0) + 1):
            label = f"{seat:02d} " + ("🔒" if seat in occupied and occupied[seat] != uid else ("✅" if occupied.get(seat) == uid else "⬜"))
            kb.insert(InlineKeyboardButton(label, callback_data=f"lv6_seat:{seat}"))
        kb.add(InlineKeyboardButton("⬅️ بازگشت", callback_data="lv6_back_lobby"))
        await edit(callback.message, "💺 <b>انتخاب صندلی</b>", kb); await callback.answer()

    async def seat(callback):
        uid = callback.from_user.id; seat_number = int(callback.data.split(":", 1)[1])
        if uid not in main.players or uid in main.waiting_list:
            await callback.answer("ابتدا وارد بازی شوید.", show_alert=True); return
        occupied = main.player_slots.get(seat_number)
        if occupied is not None and occupied != uid:
            await callback.answer("این صندلی قبلاً گرفته شده است.", show_alert=True); return
        old = next((s for s, p in main.player_slots.items() if p == uid), None)
        if old is not None: main.player_slots.pop(old, None)
        main.player_slots[seat_number] = uid
        await render(callback.message); await callback.answer(f"✅ صندلی {seat_number} انتخاب شد")

    async def reserve(callback):
        uid = callback.from_user.id
        active = [u for u in main.players if u not in main.waiting_list]
        capacity = int(main.MAX_SEATS or 0)
        full = capacity > 0 and len(active) >= capacity and all(any(p == u and s is not None for s, p in main.player_slots.items()) for u in active)
        if not full:
            await callback.answer("رزرو پس از تکمیل بازیکنان و صندلی‌ها فعال است.", show_alert=True); return
        if uid in main.waiting_list:
            main.waiting_list.remove(uid); main.players.pop(uid, None); await render(callback.message); await callback.answer("❌ رزرو لغو شد"); return
        if uid in main.players:
            await callback.answer("شما در لیست اصلی هستید.", show_alert=True); return
        main.waiting_list.append(uid); main.players[uid] = callback.from_user.full_name
        await render(callback.message); await callback.answer("🎟 به لیست رزرو اضافه شدید")

    async def manage(callback):
        if not await is_admin(callback.from_user.id):
            await callback.answer("⛔ فقط مدیران.", show_alert=True); return
        kb = InlineKeyboardMarkup(row_width=1)
        for text, data in [
            ("🚫 لغو بازی", "lv6_cancel"), ("📝 تغییر سناریو", "lv6_change_s"),
            ("🎩 تغییر گرداننده", "lv6_change_m"), ("⚔️ وضعیت چالش", "lv6_challenge"),
            ("🗑 حذف بازیکن", "lv6_remove"), ("📢 حاضری / تگ لیست", "lv6_ready"),
            ("⬅️ بازگشت به لابی", "lv6_back_lobby")]:
            kb.add(InlineKeyboardButton(text, callback_data=data))
        await edit(callback.message, "⚙️ <b>مدیریت بازی</b>", kb); await callback.answer()

    async def cancel(callback):
        if callback.from_user.id != main.moderator_id and not await is_admin(callback.from_user.id):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        main.players.clear(); main.player_slots.clear(); main.waiting_list.clear(); main._lv6_ready_players.clear()
        main.lobby_active = False; main.game_running = False; main.round_active = False
        main.selected_scenario = None; main.moderator_id = None; main.MAX_SEATS = 0
        await edit(callback.message, "🚫 <b>بازی لغو شد.</b>", menu()); await callback.answer()

    async def back_lobby(callback):
        main._lv6_change_scenario = False; main._lv6_setup = False; main.lobby_active = True
        await render(callback.message); await callback.answer()

    async def change_s(callback):
        if not await is_admin(callback.from_user.id):
            await callback.answer("⛔ فقط مدیران.", show_alert=True); return
        main._lv6_change_scenario = True
        await edit(callback.message, "📝 <b>تغییر سناریو</b>\n\nسناریوی جدید را انتخاب کنید.", scenario_kb(True)); await callback.answer()

    async def change_m(callback):
        if not await is_admin(callback.from_user.id):
            await callback.answer("⛔ فقط مدیران.", show_alert=True); return
        main._lv6_change_scenario = False
        await edit(callback.message, "🎩 <b>تغییر گرداننده</b>", await moderator_kb()); await callback.answer()

    async def challenge(callback):
        if not await is_admin(callback.from_user.id) and callback.from_user.id != main.moderator_id:
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        status = "روشن" if getattr(main, "challenge_active", True) else "خاموش"
        kb = InlineKeyboardMarkup(row_width=1)
        kb.add(InlineKeyboardButton(f"🔄 تغییر وضعیت (فعلاً {status})", callback_data="lv6_challenge_toggle"))
        kb.add(InlineKeyboardButton("⬅️ بازگشت به مدیریت", callback_data="lv6_manage"))
        await edit(callback.message, f"⚔️ <b>وضعیت چالش</b>\n\nوضعیت فعلی: <b>{status}</b>", kb); await callback.answer()

    async def challenge_toggle(callback):
        if callback.from_user.id != main.moderator_id and not await is_admin(callback.from_user.id):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        main.challenge_active = not getattr(main, "challenge_active", True)
        await challenge(callback)

    async def remove_menu(callback):
        if not await is_admin(callback.from_user.id):
            await callback.answer("⛔ فقط مدیران.", show_alert=True); return
        if not main.player_slots:
            kb = InlineKeyboardMarkup().add(InlineKeyboardButton("⬅️ بازگشت به مدیریت", callback_data="lv6_manage"))
            await edit(callback.message, "🗑 <b>حذف بازیکن</b>\n\nبازیکنی با صندلی مشخص وجود ندارد.", kb); await callback.answer(); return
        kb = InlineKeyboardMarkup(row_width=1)
        for seat, uid in sorted(main.player_slots.items()):
            kb.add(InlineKeyboardButton(f"🗑 {seat:02d}. {main.display_name(uid, main.players.get(uid))}", callback_data=f"lv6_remove:{uid}"))
        kb.add(InlineKeyboardButton("⬅️ بازگشت به مدیریت", callback_data="lv6_manage"))
        await edit(callback.message, "🗑 <b>انتخاب بازیکن برای حذف</b>", kb); await callback.answer()

    async def remove_player(callback):
        if not await is_admin(callback.from_user.id):
            await callback.answer("⛔ فقط مدیران.", show_alert=True); return
        uid = int(callback.data.split(":", 1)[1])
        seat = next((s for s, p in main.player_slots.items() if p == uid), None)
        if seat is None or uid not in main.players:
            await callback.answer("بازیکن پیدا نشد.", show_alert=True); return
        name = main.players.pop(uid, str(uid)); main.player_slots.pop(seat, None); main._lv6_ready_players.discard(uid)
        if uid in main.waiting_list: main.waiting_list.remove(uid)
        await render(callback.message); await callback.answer(f"✅ {name} حذف شد")

    def ready_text():
        active = [u for u in main.players if u not in main.waiting_list]
        lines = ["📢 <b>حاضری بازیکنان</b>", ""]
        if not active:
            lines.append("— بازیکنی در لیست اصلی نیست.")
        else:
            for uid in sorted(active, key=lambda x: next((s for s, p in main.player_slots.items() if p == x), 999)):
                seat = next((s for s, p in main.player_slots.items() if p == uid), None)
                mark = "✅" if uid in main._lv6_ready_players else "⬜"
                lines.append(f"{mark} {seat:02d}. {mention(uid)}" if seat else f"{mark} {mention(uid)}")
        return "\n".join(lines)

    async def ready_menu(callback):
        if not await is_admin(callback.from_user.id):
            await callback.answer("⛔ فقط مدیران.", show_alert=True); return
        kb = InlineKeyboardMarkup(row_width=1)
        kb.add(InlineKeyboardButton("🙋‍♂️ آماده‌ام", callback_data="lv6_ready_click"))
        kb.add(InlineKeyboardButton("⬅️ بازگشت به مدیریت", callback_data="lv6_manage"))
        await edit(callback.message, ready_text(), kb); await callback.answer()

    async def ready_click(callback):
        uid = callback.from_user.id
        active = [u for u in main.players if u not in main.waiting_list]
        if uid not in active:
            await callback.answer("⛔ فقط بازیکنان داخل بازی می‌توانند حاضری بزنند.", show_alert=True); return
        main._lv6_ready_players.add(uid)
        kb = InlineKeyboardMarkup(row_width=1)
        kb.add(InlineKeyboardButton("🙋‍♂️ آماده‌ام", callback_data="lv6_ready_click"))
        kb.add(InlineKeyboardButton("⬅️ بازگشت به مدیریت", callback_data="lv6_manage"))
        await edit(callback.message, ready_text(), kb); await callback.answer("✅ حاضری شما ثبت شد")

    async def tag_list(message):
        if message.chat.type not in ("group", "supergroup") or not message.text or message.text.strip() != "تگ لیست":
            return
        if not main.lobby_active and not main.game_running:
            await message.reply("⚠️ بازی فعالی وجود ندارد."); return
        active = [u for u in main.players if u not in main.waiting_list]
        if not active:
            await message.reply("👥 هیچ بازیکنی در بازی نیست."); return
        tags = []
        for uid in sorted(active, key=lambda x: next((s for s, p in main.player_slots.items() if p == x), 999)):
            name = main.display_name(uid, main.players.get(uid)) or str(uid)
            tags.append(f'<a href="tg://user?id={uid}">{html.escape(str(name))}</a>')
        await message.reply("📢 <b>تگ بازیکنان حاضر:</b>\n" + " ".join(tags), parse_mode="HTML")

    async def distribute(callback):
        if callback.from_user.id != main.moderator_id:
            await callback.answer("❌ فقط گرداننده می‌تواند نقش‌ها را پخش کند.", show_alert=True); return
        if not main.selected_scenario or not main.player_slots:
            await callback.answer("❌ سناریو یا صندلی‌ها مشخص نشده‌اند.", show_alert=True); return
        try:
            mapping = await main.distribute_roles()
            main.last_role_map = mapping or getattr(main, "last_role_map", {})
        except Exception as exc:
            logging.exception("role distribution failed: %s", exc)
            await callback.answer("❌ خطا در پخش نقش‌ها.", show_alert=True); return
        lines = []
        for seat, uid in sorted(main.player_slots.items()):
            name = main.display_name(uid, main.players.get(uid, "❓"))
            role = main.last_role_map.get(uid, "❓")
            lines.append(f"{seat:02d}. <a href='tg://user?id={uid}'><b>{html.escape(str(name))}</b></a> — {html.escape(str(role))}")
        try:
            await bot.send_message(main.moderator_id, "༄\n    <b>Mafia Nights</b>\n\n"
                f"📆 Date : {html.escape(str(main.get_jalali_today()))}\n"
                f"🗓 Scenario : {html.escape(str(main.selected_scenario))}\n"
                f"👮‍♂ God : {html.escape(str(main.display_name(main.moderator_id, main.players.get(main.moderator_id, '---'))))}\n\n"
                "~ ~ ~ ~ ~ ~ ~ ~ ~ ~\n        <b>لیست بازیکنان و نقش‌ها</b>\n~ ~ ~ ~ ~ ~ ~ ~ ~ ~\n\n"
                + "\n".join(lines), parse_mode="HTML")
        except Exception:
            logging.exception("failed to send complete moderator role list")
        main.game_running = True; main.lobby_active = False; main.round_active = False; main._lv6_setup = False
        public_lines = "\n".join(f"{seat:02d}. <a href='tg://user?id={uid}'>{html.escape(str(main.display_name(uid, main.players.get(uid, '❓'))))}</a>" for seat, uid in sorted(main.player_slots.items()))
        kb = InlineKeyboardMarkup(row_width=1)
        kb.add(InlineKeyboardButton("👑 انتخاب سر صحبت", callback_data="choose_head"))
        kb.add(InlineKeyboardButton("⚔ وضعیت چالش", callback_data="lv6_challenge"))
        kb.add(InlineKeyboardButton("▶ شروع دور", callback_data="start_round"))
        await edit(callback.message, "🎭 <b>نقش‌ها پخش شد!</b>\n\n👥 <b>لیست بازیکنان:</b>\n" + public_lines + "\n\nℹ️ نقش‌ها در پیوی ارسال شدند.", kb)
        await callback.answer("✅ نقش‌ها پخش شد")

    async def start_round(callback):
        if callback.from_user.id != main.moderator_id:
            await callback.answer("❌ فقط گرداننده می‌تواند دور را شروع کند.", show_alert=True); return
        if not main.turn_order:
            if main.player_slots:
                main.turn_order = sorted(main.player_slots.keys()); main.current_turn_index = 0
            else:
                await callback.answer("⚠️ ترتیب نوبت‌ها مشخص نشده.", show_alert=True); return
        main.current_turn_index = 0
        first_seat = main.turn_order[0]
        try: await callback.message.delete()
        except Exception as exc: logging.warning("could not delete round-start message: %s", exc)
        await main.start_turn(first_seat); await callback.answer("✅ دور شروع شد")

    async def start_turn_from_day(callback):
        if callback.from_user.id != main.moderator_id:
            await callback.answer("❌ فقط گرداننده می‌تواند دور را شروع کند.", show_alert=True); return
        if not main.turn_order:
            await callback.answer("⚠️ ابتدا سر صحبت را انتخاب کنید.", show_alert=True); return
        main.current_turn_index = 0
        try: await callback.message.delete()
        except Exception as exc: logging.warning("could not delete start-new-day message: %s", exc)
        await main.start_turn(main.turn_order[0]); await callback.answer("✅ دور شروع شد")

    async def noop_roles_list(*args, **kwargs):
        return None
    # distribute_roles() resolves this helper from main1's module globals.
    main.show_roles_list = noop_roles_list

    handlers = [
        (new, lambda c: c.data == "lv6_new"),
        (scenario, lambda c: str(c.data).startswith("lv6_s:")),
        (moderator, lambda c: str(c.data).startswith("lv6_m:")),
        (home, lambda c: c.data == "lv6_home"),
        (back_s, lambda c: c.data == "lv6_back_s"),
        (toggle, lambda c: c.data == "lv6_toggle"),
        (seat_menu, lambda c: c.data == "lv6_seat_menu"),
        (seat, lambda c: str(c.data).startswith("lv6_seat:")),
        (reserve, lambda c: c.data == "lv6_reserve"),
        (manage, lambda c: c.data == "lv6_manage"),
        (cancel, lambda c: c.data == "lv6_cancel"),
        (back_lobby, lambda c: c.data == "lv6_back_lobby"),
        (change_s, lambda c: c.data == "lv6_change_s"),
        (change_m, lambda c: c.data == "lv6_change_m"),
        (challenge, lambda c: c.data == "lv6_challenge"),
        (challenge_toggle, lambda c: c.data == "lv6_challenge_toggle"),
        (remove_menu, lambda c: c.data == "lv6_remove"),
        (remove_player, lambda c: str(c.data).startswith("lv6_remove:")),
        (ready_menu, lambda c: c.data == "lv6_ready"),
        (ready_click, lambda c: c.data == "lv6_ready_click"),
        (distribute, lambda c: c.data == "distribute_roles"),
        (start_round, lambda c: c.data == "start_round"),
        (start_turn_from_day, lambda c: c.data == "start_turn"),
    ]
    for fn, flt in handlers:
        dp.register_callback_query_handler(fn, flt); front_callback(fn)

    dp.register_message_handler(tag_list, lambda m: bool(m.text) and m.text.strip() == "تگ لیست")
    try:
        mhandlers = getattr(dp.message_handlers, "handlers", [])
        for i, h in enumerate(mhandlers):
            if getattr(h, "callback", None) is tag_list:
                mhandlers.insert(0, mhandlers.pop(i)); break
    except Exception:
        pass

    main.main_menu_keyboard = menu
