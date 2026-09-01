from __future__ import annotations

import html
import logging
from datetime import datetime, timezone
from typing import Any

from aiogram import types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def _front(dp, fn):
    handlers = getattr(getattr(dp, "callback_query_handlers", None), "handlers", None)
    if not isinstance(handlers, list):
        return
    for i, h in enumerate(handlers):
        if getattr(h, "callback", None) is fn:
            handlers.insert(0, handlers.pop(i))
            return


def _name(main, uid, fallback=None):
    try:
        value = main.display_name(int(uid), fallback)
    except Exception:
        value = fallback
    return value or str(uid)


def _mention(main, uid, fallback=None):
    return f'<a href="tg://user?id={int(uid)}">{html.escape(_name(main, uid, fallback))}</a>'


def _active(main):
    try:
        return main.persistent_runtime.state.active_game(int(main.group_chat_id))
    except Exception:
        return None


def _snapshot(main):
    try:
        return main.persistent_runtime.state.lobby.snapshot(_active(main)["id"])
    except Exception:
        return {"players": [], "seats": {}, "waiting": []}


def _sync_legacy(main, snap):
    main.player_slots.clear()
    main.players.clear()
    main.players_in_game.setdefault(main.group_chat_id, {}).clear()
    for row in snap.get("players", []):
        uid = int(row["player_id"])
        name = _name(main, uid, row.get("first_name") or row.get("username"))
        main.players[uid] = name
        seat = row.get("seat")
        if seat is not None and not row.get("is_substitute"):
            main.player_slots[int(seat)] = uid
            main.players_in_game.setdefault(main.group_chat_id, {})[int(seat)] = {
                "id": uid, "name": name, "role": row.get("role")
            }


def _config_keyboard(main):
    kb = InlineKeyboardMarkup(row_width=2)
    if main.selected_scenario:
        kb.add(InlineKeyboardButton(f"📝 سناریو: {main.selected_scenario}", callback_data="choose_scenario"))
    else:
        kb.add(InlineKeyboardButton("📝 انتخاب سناریو", callback_data="choose_scenario"))
    if main.moderator_id:
        kb.add(InlineKeyboardButton(f"🎩 گرداننده: {_name(main, main.moderator_id)}", callback_data="choose_moderator"))
    else:
        kb.add(InlineKeyboardButton("🎩 انتخاب گرداننده", callback_data="choose_moderator"))
    if main.selected_scenario and main.moderator_id:
        kb.add(InlineKeyboardButton("🚀 ایجاد بازی", callback_data="create_game"))
    return kb


def _lobby_keyboard(main, snap):
    kb = InlineKeyboardMarkup(row_width=3)
    players = snap.get("players", [])
    active = [r for r in players if not r.get("is_substitute")]
    reserved = [r for r in players if r.get("is_substitute")]
    active_ids = {int(r["player_id"]) for r in active}
    reserved_ids = {int(r["player_id"]) for r in reserved}
    max_seats = int(main.MAX_SEATS or len((main.scenarios.get(main.selected_scenario) or {}).get("roles", [])))

    # A shared group inline keyboard cannot have per-user labels. The handlers
    # therefore enforce membership; the private control message supplies the
    # user-specific exit/reserve controls after a click.
    if len(active) < max_seats:
        kb.add(InlineKeyboardButton("✅ ورود به بازی", callback_data="lobby_join"))
    else:
        kb.add(InlineKeyboardButton("🎟 رزرو", callback_data="lobby_reserve"))
    kb.add(InlineKeyboardButton("🚪 خروج از بازی", callback_data="lobby_leave"))

    for seat in range(1, max_seats + 1):
        row = next((r for r in active if r.get("seat") == seat), None)
        if row:
            kb.add(InlineKeyboardButton(f"🔴 {seat}: {_name(main, row['player_id'])}", callback_data=f"lobby_seat_info_{seat}"))
        else:
            kb.add(InlineKeyboardButton(f"⬜ صندلی {seat}", callback_data=f"lobby_seat_{seat}"))

    if len(active) >= max_seats:
        kb.add(InlineKeyboardButton("🎟 لیست رزرو", callback_data="lobby_reserve_list"))
        if all(r.get("seat") is not None for r in active):
            kb.add(InlineKeyboardButton("🎭 پخش نقش", callback_data="distribute_roles"))

    kb.add(InlineKeyboardButton("⚙️ مدیریت بازی", callback_data="lobby_manage"))
    return kb


def _lobby_text(main, snap):
    game = _active(main) or {}
    players = [r for r in snap.get("players", []) if not r.get("is_substitute")]
    reserved = [r for r in snap.get("players", []) if r.get("is_substitute")]
    max_seats = int(main.MAX_SEATS or 0)
    lines = [
        "🎮 <b>لابی بازی مافیا</b>",
        "",
        f"📝 سناریو: <b>{html.escape(str(main.selected_scenario or game.get('scenario_id') or '---'))}</b>",
        f"🎩 گرداننده: {_mention(main, main.moderator_id) if main.moderator_id else '---'}",
        f"👥 بازیکنان: <b>{len(players)}/{max_seats}</b>",
        "",
        "<b>بازیکنان داخل بازی:</b>",
    ]
    if players:
        for i, r in enumerate(players, 1):
            seat = r.get("seat")
            lines.append(f"{seat if seat is not None else '—'}. {_mention(main, r['player_id'])}")
    else:
        lines.append("— هنوز بازیکنی وارد نشده است.")
    if reserved:
        lines += ["", f"🎟 <b>رزرو: {len(reserved)}</b>"]
        for i, r in enumerate(reserved, 1):
            lines.append(f"{i}. {_mention(main, r['player_id'])}")
    if len(players) >= max_seats and all(r.get("seat") is not None for r in players):
        lines += ["", "✅ ظرفیت و صندلی‌ها کامل است؛ امکان پخش نقش فعال شد."]
    return "\n".join(lines)


async def _edit(callback, text, markup):
    try:
        await callback.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    except Exception:
        try:
            await callback.message.edit_reply_markup(reply_markup=markup)
        except Exception:
            pass


def install(main):
    dp = main.dp
    bot = main.bot

    # Remove the deprecated "لیست جدید" from all newly rendered main menus.
    def clean_main_menu():
        kb = InlineKeyboardMarkup(row_width=1)
        kb.add(InlineKeyboardButton("🎮 بازی جدید", callback_data="new_game"))
        return kb
    main.main_menu_keyboard = clean_main_menu

    async def new_game(c: types.CallbackQuery):
        await c.answer()
        if c.message.chat.id != main.ALLOWED_GROUP_ID:
            await c.answer("❌ این ربات فقط در گروه اصلی کار می‌کند.", show_alert=True)
            return
        active = _active(main)
        if active:
            await c.answer("⚠️ یک بازی فعال وجود دارد. ابتدا آن را لغو کنید.", show_alert=True)
            return
        main.group_chat_id = c.message.chat.id
        main.selected_scenario = None
        main.moderator_id = None
        main.MAX_SEATS = 0
        main.players.clear()
        main.player_slots.clear()
        await _edit(c, "🎮 <b>ایجاد بازی جدید</b>\n\nمرحله اول: سناریو را انتخاب کنید.", _scenario_keyboard(main))

    def _scenario_keyboard(main):
        kb = InlineKeyboardMarkup(row_width=1)
        for i, scen in enumerate(main.scenarios):
            kb.add(InlineKeyboardButton(str(scen), callback_data=f"lobby_scenario_{i}"))
        kb.add(InlineKeyboardButton("⬅️ بازگشت", callback_data="back_main"))
        return kb

    async def choose_scenario(c: types.CallbackQuery):
        await c.answer()
        await _edit(c, "📝 <b>انتخاب سناریو</b>", _scenario_keyboard(main))

    async def scenario(c: types.CallbackQuery):
        try:
            index = int(str(c.data).removeprefix("lobby_scenario_"))
            selected = list(main.scenarios.keys())[index]
        except Exception:
            await c.answer("⚠️ سناریو نامعتبر است.", show_alert=True)
            return
        main.selected_scenario = selected
        main.set_max_seats_from_scenario(selected)
        await c.answer("✅ سناریو انتخاب شد")
        await _edit(c, f"📝 سناریو: <b>{html.escape(selected)}</b>\n\nمرحله بعد: گرداننده را انتخاب کنید.", _moderator_keyboard(main))

    def _moderator_keyboard(main):
        kb = InlineKeyboardMarkup(row_width=1)
        kb.add(InlineKeyboardButton("🎩 انتخاب گرداننده", callback_data="choose_moderator"))
        if main.moderator_id:
            kb.add(InlineKeyboardButton(f"🎩 فعلی: {_name(main, main.moderator_id)}", callback_data="choose_moderator"))
        kb.add(InlineKeyboardButton("⬅️ بازگشت به سناریو", callback_data="choose_scenario"))
        return kb

    async def choose_moderator(c: types.CallbackQuery):
        await c.answer()
        if not main.selected_scenario:
            await c.answer("⚠️ ابتدا سناریو را انتخاب کنید.", show_alert=True)
            return
        admins = await bot.get_chat_administrators(main.group_chat_id)
        kb = InlineKeyboardMarkup(row_width=1)
        for m in admins:
            uid = m.user.id
            kb.add(InlineKeyboardButton(_name(main, uid, m.user.full_name), callback_data=f"lobby_moderator_{uid}"))
        kb.add(InlineKeyboardButton("⬅️ بازگشت", callback_data="choose_scenario"))
        await _edit(c, "🎩 <b>انتخاب گرداننده</b>", kb)

    async def moderator(c: types.CallbackQuery):
        try:
            uid = int(str(c.data).removeprefix("lobby_moderator_"))
        except ValueError:
            await c.answer("⚠️ گرداننده نامعتبر است.", show_alert=True)
            return
        main.moderator_id = uid
        try:
            main.addons.register(moderator_id=uid, group_id=main.group_chat_id)
        except Exception:
            pass
        await c.answer("✅ گرداننده انتخاب شد")
        await _edit(c, f"🎩 گرداننده: <b>{html.escape(_name(main, uid))}</b>\n\nهر دو تنظیم کامل شد. برای ساخت لابی «ایجاد بازی» را بزنید.", _config_keyboard(main))

    async def create_game(c: types.CallbackQuery):
        if not main.selected_scenario or not main.moderator_id:
            await c.answer("⚠️ ابتدا سناریو و گرداننده را انتخاب کنید.", show_alert=True)
            return
        try:
            existing = _active(main)
            if existing:
                await c.answer("⚠️ بازی فعال دیگری وجود دارد.", show_alert=True)
                return
            game = main.persistent_runtime.state.ensure_lobby(main.group_chat_id, main.moderator_id, main.selected_scenario)
            main.group_chat_id = c.message.chat.id
            main.lobby_active = True
            main.game_running = False
            main.game_message_id = c.message.message_id
            snap = _snapshot(main)
            _sync_legacy(main, snap)
            await c.answer("✅ بازی ایجاد شد")
            await _edit(c, _lobby_text(main, snap), _lobby_keyboard(main, snap))
        except Exception:
            logging.exception("lobby creation failed")
            await c.answer("❌ ایجاد بازی انجام نشد.", show_alert=True)

    async def join(c: types.CallbackQuery):
        uid = c.from_user.id
        game = _active(main)
        if not game or not main.selected_scenario:
            await c.answer("⚠️ لابی فعالی وجود ندارد.", show_alert=True)
            return
        snap = _snapshot(main)
        active = [r for r in snap.get("players", []) if not r.get("is_substitute")]
        reserved = [r for r in snap.get("players", []) if r.get("is_substitute")]
        if any(int(r["player_id"]) == uid for r in active):
            await c.answer("ℹ️ شما در بازی هستید. برای انتخاب صندلی از دکمه صندلی استفاده کنید.", show_alert=True)
            return
        if any(int(r["player_id"]) == uid for r in reserved):
            await c.answer("ℹ️ شما در لیست رزرو هستید.", show_alert=True)
            return
        max_seats = int(main.MAX_SEATS)
        if len(active) >= max_seats:
            await c.answer("🎟 ظرفیت اصلی پر است؛ از رزرو استفاده کنید.", show_alert=True)
            return
        try:
            main.persistent_runtime.join(main.group_chat_id, uid, None, main.moderator_id, main.selected_scenario, substitute=False)
            main.players[uid] = _name(main, uid, c.from_user.full_name)
            await c.answer("✅ وارد بازی شدید")
            await render(c)
        except Exception as e:
            await c.answer(str(e), show_alert=True)

    async def leave(c: types.CallbackQuery):
        uid = c.from_user.id
        game = _active(main)
        if not game:
            await c.answer("⚠️ لابی فعالی وجود ندارد.", show_alert=True)
            return
        snap = _snapshot(main)
        active = [r for r in snap.get("players", []) if not r.get("is_substitute")]
        reserved = [r for r in snap.get("players", []) if r.get("is_substitute")]
        if any(int(r["player_id"]) == uid for r in reserved) and not any(int(r["player_id"]) == uid for r in active):
            main.persistent_runtime.state.games.remove_player(game["id"], uid)
            await c.answer("✅ رزرو شما لغو شد")
        elif any(int(r["player_id"]) == uid for r in active):
            row = next(r for r in active if int(r["player_id"]) == uid)
            seat = row.get("seat")
            main.persistent_runtime.state.games.remove_player(game["id"], uid)
            if seat is not None:
                promoted = main.persistent_runtime.state.lobby.promote_waiting_player(game["id"], seat)
                if promoted:
                    await bot.send_message(main.group_chat_id, f"🔄 {_mention(main, promoted['player_id'])} از لیست رزرو وارد بازی شد.")
            await c.answer("✅ از بازی خارج شدید")
        else:
            await c.answer("ℹ️ شما در بازی نیستید.", show_alert=True)
        await render(c)

    async def reserve(c: types.CallbackQuery):
        uid = c.from_user.id
        game = _active(main)
        if not game:
            await c.answer("⚠️ لابی فعال نیست.", show_alert=True)
            return
        snap = _snapshot(main)
        active = [r for r in snap.get("players", []) if not r.get("is_substitute")]
        if len(active) < int(main.MAX_SEATS):
            await c.answer("ℹ️ هنوز ظرفیت بازی پر نشده است؛ می‌توانید وارد بازی شوید.", show_alert=True)
            return
        if any(int(r["player_id"]) == uid for r in snap.get("players", [])):
            await c.answer("ℹ️ شما از قبل در یکی از لیست‌ها هستید.", show_alert=True)
            return
        main.persistent_runtime.join(main.group_chat_id, uid, None, main.moderator_id, main.selected_scenario, substitute=True)
        await c.answer("🎟 به لیست رزرو اضافه شدید")
        await render(c)

    async def seat(c: types.CallbackQuery):
        try:
            seat_no = int(str(c.data).removeprefix("lobby_seat_"))
        except ValueError:
            await c.answer("⚠️ صندلی نامعتبر است.", show_alert=True)
            return
        uid = c.from_user.id
        game = _active(main)
        snap = _snapshot(main)
        row = next((r for r in snap.get("players", []) if int(r["player_id"]) == uid and not r.get("is_substitute")), None)
        if not row:
            await c.answer("⚠️ ابتدا وارد بازی شوید.", show_alert=True)
            return
        occupied = next((r for r in snap.get("players", []) if r.get("seat") == seat_no and not r.get("is_substitute")), None)
        if occupied and int(occupied["player_id"]) != uid:
            await c.answer("❌ این صندلی قبلاً انتخاب شده است.", show_alert=True)
            return
        try:
            main.persistent_runtime.state.lobby.assign_seat(game["id"], uid, seat_no)
            await c.answer(f"💺 صندلی {seat_no} برای شما ثبت شد")
            await render(c)
        except Exception as e:
            await c.answer(str(e), show_alert=True)

    async def seat_info(c: types.CallbackQuery):
        await c.answer("💺 این صندلی قبلاً انتخاب شده است.", show_alert=True)

    async def reserve_list(c: types.CallbackQuery):
        snap = _snapshot(main)
        reserved = [r for r in snap.get("players", []) if r.get("is_substitute")]
        text = "🎟 <b>لیست رزرو</b>\n\n" + ("\n".join(f"{i}. {_mention(main, r['player_id'])}" for i, r in enumerate(reserved, 1)) if reserved else "لیست رزرو خالی است.")
        kb = InlineKeyboardMarkup().add(InlineKeyboardButton("⬅️ بازگشت به لابی", callback_data="lobby_back"))
        await c.answer()
        await _edit(c, text, kb)

    async def manage(c: types.CallbackQuery):
        if not await _is_admin(main, c):
            await c.answer("⛔ فقط مدیران گروه می‌توانند مدیریت بازی را انجام دهند.", show_alert=True)
            return
        kb = InlineKeyboardMarkup(row_width=2)
        kb.add(
            InlineKeyboardButton("🚫 لغو بازی", callback_data="cancel_game"),
            InlineKeyboardButton("📝 تغییر سناریو", callback_data="lobby_manage_scenario"),
            InlineKeyboardButton("🎩 تغییر گرداننده", callback_data="lobby_manage_mod"),
            InlineKeyboardButton(f"⚔️ چالش: {'فعال' if main.challenge_active else 'غیرفعال'}", callback_data="lobby_toggle_challenge"),
            InlineKeyboardButton("🗑 حذف بازیکن", callback_data="lobby_remove_player"),
            InlineKeyboardButton("📣 حاضری", callback_data="lobby_attendance"),
            InlineKeyboardButton("⬅️ بازگشت", callback_data="lobby_back"),
        )
        await c.answer()
        await _edit(c, "⚙️ <b>مدیریت بازی</b>", kb)

    async def toggle_challenge(c: types.CallbackQuery):
        if not await _is_admin(main, c):
            await c.answer("⛔ دسترسی ندارید.", show_alert=True); return
        main.challenge_active = not main.challenge_active
        await c.answer("✅ تنظیم شد")
        await manage(c)

    async def remove_player(c: types.CallbackQuery):
        if not await _is_admin(main, c):
            await c.answer("⛔ دسترسی ندارید.", show_alert=True); return
        snap = _snapshot(main)
        kb = InlineKeyboardMarkup(row_width=1)
        for r in snap.get("players", []):
            if not r.get("is_substitute"):
                kb.add(InlineKeyboardButton(_name(main, r["player_id"]), callback_data=f"lobby_remove_uid_{r['player_id']}"))
        kb.add(InlineKeyboardButton("⬅️ بازگشت", callback_data="lobby_manage"))
        await c.answer(); await _edit(c, "🗑 بازیکنی را برای حذف انتخاب کنید:", kb)

    async def remove_uid(c: types.CallbackQuery):
        if not await _is_admin(main, c):
            await c.answer("⛔ دسترسی ندارید.", show_alert=True); return
        try: uid = int(str(c.data).removeprefix("lobby_remove_uid_"))
        except ValueError: await c.answer("⚠️ نامعتبر", show_alert=True); return
        game = _active(main)
        snap = _snapshot(main)
        row = next((r for r in snap.get("players", []) if int(r["player_id"]) == uid), None)
        if not row: await c.answer("بازیکن پیدا نشد.", show_alert=True); return
        seat_no = row.get("seat")
        main.persistent_runtime.state.games.remove_player(game["id"], uid)
        if seat_no is not None:
            main.persistent_runtime.state.lobby.promote_waiting_player(game["id"], seat_no)
        await c.answer("✅ بازیکن حذف شد")
        await render(c)

    async def attendance(c: types.CallbackQuery):
        if not await _is_admin(main, c):
            await c.answer("⛔ دسترسی ندارید.", show_alert=True); return
        snap = _snapshot(main)
        state = (next(iter([r for r in snap.get("players", []) if not r.get("is_substitute")]), None) and {}) or {}
        game = _active(main)
        ready = set((game or {}).get("state", {}).get("ready", []))
        lines = ["📣 <b>حاضری بازیکنان</b>", ""]
        kb = InlineKeyboardMarkup(row_width=1)
        for r in [r for r in snap.get("players", []) if not r.get("is_substitute")]:
            uid = int(r["player_id"]); mark = "✅" if uid in ready else "⬜"
            lines.append(f"{mark} {_mention(main, uid)}")
        kb.add(InlineKeyboardButton("🙋 آماده‌ام", callback_data="lobby_ready"))
        kb.add(InlineKeyboardButton("⬅️ بازگشت", callback_data="lobby_manage"))
        await c.answer(); await _edit(c, "\n".join(lines), kb)

    async def ready(c: types.CallbackQuery):
        game = _active(main)
        if not game: await c.answer("⚠️ لابی فعال نیست.", show_alert=True); return
        snap = _snapshot(main)
        ids = {int(r["player_id"]) for r in snap.get("players", []) if not r.get("is_substitute")}
        if c.from_user.id not in ids:
            await c.answer("⛔ فقط بازیکنان داخل بازی می‌توانند حاضری بزنند.", show_alert=True); return
        state = dict(game.get("state") or {}); ready_ids = set(state.get("ready", [])); ready_ids.add(c.from_user.id); state["ready"] = list(ready_ids)
        main.persistent_runtime.state.games.update_game(game["id"], state=state)
        await c.answer("✅ حاضری شما ثبت شد")
        await attendance(c)

    async def manage_scenario(c: types.CallbackQuery):
        if not await _is_admin(main, c): await c.answer("⛔ دسترسی ندارید.", show_alert=True); return
        await c.answer(); await _edit(c, "📝 سناریوی جدید را انتخاب کنید:", _scenario_keyboard(main))

    async def manage_mod(c: types.CallbackQuery):
        if not await _is_admin(main, c): await c.answer("⛔ دسترسی ندارید.", show_alert=True); return
        await choose_moderator(c)

    async def back(c: types.CallbackQuery):
        await c.answer(); snap = _snapshot(main); await _edit(c, _lobby_text(main, snap), _lobby_keyboard(main, snap))

    async def render(c):
        snap = _snapshot(main); _sync_legacy(main, snap); await _edit(c, _lobby_text(main, snap), _lobby_keyboard(main, snap))

    async def _is_admin(main, c):
        if c.from_user.id == main.moderator_id: return True
        try:
            m = await bot.get_chat_member(main.group_chat_id, c.from_user.id)
            return m.status in {"administrator", "creator"}
        except Exception:
            return False

    registrations = [
        (new_game, lambda c: c.data == "new_game"),
        (choose_scenario, lambda c: c.data == "choose_scenario"),
        (scenario, lambda c: str(c.data or "").startswith("lobby_scenario_")),
        (choose_moderator, lambda c: c.data == "choose_moderator"),
        (moderator, lambda c: str(c.data or "").startswith("lobby_moderator_")),
        (create_game, lambda c: c.data == "create_game"),
        (join, lambda c: c.data == "lobby_join"),
        (leave, lambda c: c.data == "lobby_leave"),
        (reserve, lambda c: c.data == "lobby_reserve"),
        (seat, lambda c: str(c.data or "").startswith("lobby_seat_") and not str(c.data).startswith("lobby_seat_info_")),
        (seat_info, lambda c: str(c.data or "").startswith("lobby_seat_info_")),
        (reserve_list, lambda c: c.data == "lobby_reserve_list"),
        (manage, lambda c: c.data == "lobby_manage"),
        (toggle_challenge, lambda c: c.data == "lobby_toggle_challenge"),
        (remove_player, lambda c: c.data == "lobby_remove_player"),
        (remove_uid, lambda c: str(c.data or "").startswith("lobby_remove_uid_")),
        (attendance, lambda c: c.data == "lobby_attendance"),
        (ready, lambda c: c.data == "lobby_ready"),
        (manage_scenario, lambda c: c.data == "lobby_manage_scenario"),
        (manage_mod, lambda c: c.data == "lobby_manage_mod"),
        (back, lambda c: c.data == "lobby_back"),
    ]
    for fn, filt in registrations:
        dp.register_callback_query_handler(fn, filt)
        _front(dp, fn)
