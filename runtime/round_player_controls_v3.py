"""Authoritative round controls for mute, one-shot extra turns and challenges."""
from __future__ import annotations

import asyncio
import html
import logging
import time
from functools import wraps

from aiogram.dispatcher.handler import CancelHandler
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def _handler(item):
    return getattr(item, "handler", None)


def _gid(main):
    for key in ("group_chat_id", "ALLOWED_GROUP_ID", "GROUP_ID", "group_id"):
        value = getattr(main, key, None)
        if value:
            try:
                return int(value)
            except Exception:
                pass
    return None


def _players(main):
    slots = getattr(main, "player_slots", {}) or {}
    legacy = getattr(main, "players", {}) or {}
    pg = getattr(main, "players_in_game", {}) or {}
    out = []
    for raw_seat, raw_uid in slots.items():
        try:
            seat, uid = int(raw_seat), int(raw_uid)
        except Exception:
            continue
        info = pg.get(seat) or pg.get(str(seat)) or {}
        name = info.get("name") if isinstance(info, dict) else None
        if not name:
            try:
                name = main.display_name(uid, legacy.get(uid))
            except Exception:
                name = None
        value = legacy.get(uid)
        if not name or str(name).strip() in {"?", "❓", "None", "بازیکن"}:
            if isinstance(value, str):
                name = value
            elif isinstance(value, dict):
                name = value.get("nickname") or value.get("full_name") or value.get("first_name")
            else:
                name = getattr(value, "full_name", None) or getattr(value, "first_name", None)
        if not name or str(name).strip() in {"?", "❓", "None", "بازیکن"}:
            name = f"بازیکن {seat}"
        out.append((seat, uid, str(name)))
    return sorted(out)


def _ensure(main):
    if not isinstance(getattr(main, "_gm_muted_next_round", None), set):
        main._gm_muted_next_round = set()
    if not isinstance(getattr(main, "_gm_extra_next_round", None), set):
        main._gm_extra_next_round = set()
    if not isinstance(getattr(main, "_gm_extra_seats", None), set):
        main._gm_extra_seats = set()
    if not isinstance(getattr(main, "_gm_normal_order", None), list):
        main._gm_normal_order = []
    if not hasattr(main, "_gm_extra_phase"):
        main._gm_extra_phase = False
    if not hasattr(main, "_gm_extra_turn_active"):
        main._gm_extra_turn_active = False


def _active(main):
    try:
        return int(main.turn_order[main.current_turn_index])
    except Exception:
        return None


def _uid(main, seat):
    return (getattr(main, "player_slots", {}) or {}).get(seat)


def _name(main, seat):
    uid = _uid(main, seat)
    for s, u, name in _players(main):
        if int(s) == int(seat) and (uid is None or int(u) == int(uid)):
            return name
    return f"بازیکن {seat}"


def _clean_base(main):
    """Build a unique normal order and never let an extra seat leak into it."""
    _ensure(main)
    occupied = {s for s, _, _ in _players(main)}
    extras = {int(s) for s in main._gm_extra_seats}
    source = list(getattr(main, "turn_order", []) or []) or list(main._gm_normal_order or [])
    if not source:
        source = sorted(occupied)
    result, seen = [], set()
    for raw in source:
        try:
            seat = int(raw)
        except Exception:
            continue
        if seat in occupied and seat not in extras and seat not in seen:
            result.append(seat)
            seen.add(seat)
    for seat in sorted(occupied):
        if seat not in extras and seat not in seen:
            result.append(seat)
    return result


async def _is_admin(main, uid):
    if uid == getattr(main, "moderator_id", None):
        return True
    gid = _gid(main)
    if not gid:
        return False
    try:
        return any(getattr(getattr(x, "user", None), "id", None) == uid for x in await main.bot.get_chat_administrators(gid))
    except Exception:
        return False


def _front(reg, item):
    try:
        reg.insert(0, reg.pop(reg.index(item)))
    except ValueError:
        pass


async def install(main):
    _ensure(main)
    dp = main.dp
    reg = getattr(getattr(dp, "callback_query_handlers", None), "handlers", None)
    if reg is None:
        return False

    async def hydrate_names():
        gid = _gid(main)
        if not gid:
            return
        for seat, uid, _ in _players(main):
            try:
                member = await main.bot.get_chat_member(gid, uid)
                user = getattr(member, "user", None)
                full_name = getattr(user, "full_name", None) or getattr(user, "first_name", None)
                if full_name and isinstance(getattr(main, "players", None), dict):
                    old = main.players.get(uid)
                    if not old or str(old).strip() in {"?", "❓"}:
                        main.players[uid] = full_name
            except Exception:
                pass

    async def choose(callback, mode):
        if not await _is_admin(main, callback.from_user.id):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
            raise CancelHandler()
        if not getattr(main, "game_running", False):
            await callback.answer("⚠️ بازی در حال اجرا نیست.", show_alert=True)
            raise CancelHandler()
        await hydrate_names()
        target = main._gm_muted_next_round if mode == "mute" else main._gm_extra_next_round
        icon = "🔇" if mode == "mute" else "➕"
        title = "سکوت بازیکن" if mode == "mute" else "ترن اضافه"
        rows = []
        for seat, _, name in _players(main):
            mark = " ✅" if seat in target else ""
            rows.append([InlineKeyboardButton(f"{icon} صندلی {seat} — {name}{mark}", callback_data=f"gm3:{mode}:{seat}")])
        rows.append([InlineKeyboardButton("⬅️ مدیریت بازی", callback_data="manage_game")])
        note = "🔇 بازیکن انتخاب‌شده در ادامه این دور نوبت صحبت ندارد و چالش هم برایش بسته است." if mode == "mute" else "➕ دقیقاً یک ترن اضافه بعد از نوبت‌های عادی؛ بدون امکان چالش."
        await callback.message.edit_text(f"{icon} <b>{title}</b>\n\nبازیکن موردنظر را انتخاب کنید.\n{note}", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode="HTML")
        await callback.answer()
        raise CancelHandler()

    async def toggle(callback, mode):
        if not await _is_admin(main, callback.from_user.id):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
            raise CancelHandler()
        try:
            seat = int(str(callback.data).rsplit(":", 1)[1])
        except Exception:
            await callback.answer("⚠️ بازیکن نامعتبر است.", show_alert=True)
            raise CancelHandler()
        if seat not in {s for s, _, _ in _players(main)}:
            await callback.answer("⚠️ بازیکن دیگر در بازی نیست.", show_alert=True)
            raise CancelHandler()
        target = main._gm_muted_next_round if mode == "mute" else main._gm_extra_next_round
        opposite = main._gm_extra_next_round if mode == "mute" else main._gm_muted_next_round
        label = "سکوت" if mode == "mute" else "ترن اضافه"
        if seat in target:
            target.remove(seat)
            status = "لغو شد"
        else:
            target.add(seat)
            opposite.discard(seat)
            status = "فعال شد"
        await callback.answer(f"{label} صندلی {seat} {status}.")
        await choose(callback, mode)

    dp.register_callback_query_handler(lambda c: choose(c, "mute"), lambda c: c.data == "gm:mute", state="*")
    dp.register_callback_query_handler(lambda c: choose(c, "extra"), lambda c: c.data == "gm:extra", state="*")
    dp.register_callback_query_handler(lambda c: toggle(c, "mute"), lambda c: str(c.data or "").startswith("gm3:mute:"), state="*")
    dp.register_callback_query_handler(lambda c: toggle(c, "extra"), lambda c: str(c.data or "").startswith("gm3:extra:"), state="*")
    for item in list(reg)[-4:]:
        _front(reg, item)

    # Challenge keyboard: current speaker can request a challenge ONLY from other players.
    old_keyboard = getattr(main, "turn_keyboard", None)
    if old_keyboard is not None and not getattr(old_keyboard, "_gm3_keyboard", False):
        @wraps(old_keyboard)
        def turn_keyboard_v3(seat, is_challenge=False):
            _ensure(main)
            try:
                seat = int(seat)
            except Exception:
                return old_keyboard(seat, is_challenge)
            if is_challenge:
                return old_keyboard(seat, True)
            if seat in main._gm_extra_seats or seat in main._gm_muted_next_round:
                return InlineKeyboardMarkup(row_width=1).add(InlineKeyboardButton("⏭ نکست", callback_data=f"next_{seat}"))
            kb = InlineKeyboardMarkup(row_width=1)
            kb.add(InlineKeyboardButton("⏭ نکست", callback_data=f"next_{seat}"))
            if getattr(main, "challenge_active", False):
                for target_seat, _, target_name in _players(main):
                    if int(target_seat) == seat:
                        continue
                    kb.add(InlineKeyboardButton(f"⚔️ درخواست چالش از {target_name}", callback_data=f"challenge_request_{target_seat}"))
            return kb
        turn_keyboard_v3._gm3_keyboard = True
        main.turn_keyboard = turn_keyboard_v3

    old_next = getattr(main, "next_turn", None)
    if old_next is not None:
        reg[:] = [x for x in reg if getattr(_handler(x), "__name__", "") != "next_turn"]

        async def extra_turn(seat):
            uid = _uid(main, seat)
            if not uid:
                return
            name = _name(main, seat)
            mention = f"<a href='tg://user?id={uid}'>{html.escape(name)}</a>"
            if getattr(main, "turn_timer_task", None) and not main.turn_timer_task.done():
                main.turn_timer_task.cancel()
            main._gm_extra_turn_active = True
            main.challenge_mode = False
            duration = 120
            msg = await main.bot.send_message(_gid(main), f"➕ ⚔️ <b>ترن اضافه</b>\n🎙 نوبت اضافه {mention} است. ({duration} ثانیه)\n🚫 این ترن امکان چالش ندارد.", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(row_width=1).add(InlineKeyboardButton("⏭ نکست", callback_data=f"next_{seat}")))
            countdown = getattr(main, "countdown", None)
            if countdown:
                main.turn_timer_task = asyncio.create_task(countdown(seat, duration, msg.message_id, False))

        async def start_normal(seat):
            if seat not in main._gm_muted_next_round:
                return await main.start_turn(seat, duration=120, is_challenge=False)
            uid = _uid(main, seat)
            name = _name(main, seat)
            mention = f"<a href='tg://user?id={uid}'>{html.escape(name)}</a>" if uid else html.escape(name)
            if getattr(main, "turn_timer_task", None) and not main.turn_timer_task.done():
                main.turn_timer_task.cancel()
            await main.bot.send_message(_gid(main), f"🔇 {mention} این دور سکوت است و نوبت صحبت ندارد.")
            await asyncio.sleep(1)
            main.current_turn_index += 1
            return await advance()

        async def advance():
            while True:
                order = list(getattr(main, "turn_order", []) or [])
                idx = int(getattr(main, "current_turn_index", 0))
                if idx < len(order):
                    seat = int(order[idx])
                    if main._gm_extra_phase:
                        if seat in main._gm_extra_seats:
                            return await extra_turn(seat)
                        main.current_turn_index += 1
                        continue
                    return await start_normal(seat)

                # End of normal turns: consume pending extra selections once.
                if not main._gm_extra_phase:
                    base = _clean_base(main)
                    muted = {int(s) for s in main._gm_muted_next_round}
                    pending = {int(s) for s in main._gm_extra_next_round}
                    extras = [s for s in base if s in pending and s not in muted]
                    main._gm_extra_next_round.clear()
                    if extras:
                        main._gm_normal_order = list(base)
                        main._gm_extra_seats = set(extras)
                        main._gm_extra_phase = True
                        main.turn_order = list(base) + list(extras)
                        main.current_turn_index = len(base)
                        continue

                    next_order = [s for s in base if s not in muted]
                    main._gm_muted_next_round.clear()
                    main._gm_extra_seats.clear()
                    main._gm_extra_phase = False
                    main._gm_extra_turn_active = False
                    main._gm_normal_order = list(next_order)
                    main.turn_order = list(next_order)
                    main.current_turn_index = 0
                    if not next_order:
                        await main.bot.send_message(_gid(main), "⚠️ بازیکنی برای دور بعد باقی نمانده.")
                        return
                    return await start_normal(next_order[0])

                # End of extra phase: extras are now consumed; begin a clean normal round.
                base = list(main._gm_normal_order or _clean_base(main))
                muted = {int(s) for s in main._gm_muted_next_round}
                next_order = [s for s in base if s not in muted]
                main._gm_muted_next_round.clear()
                main._gm_extra_seats.clear()
                main._gm_extra_phase = False
                main._gm_extra_turn_active = False
                main._gm_normal_order = list(next_order)
                main.turn_order = list(next_order)
                main.current_turn_index = 0
                if not next_order:
                    await main.bot.send_message(_gid(main), "⚠️ بازیکنی برای دور بعد باقی نمانده.")
                    return
                return await start_normal(next_order[0])

        async def next_v3(callback):
            if getattr(getattr(callback, "message", None), "chat", None) and callback.message.chat.type == "private":
                await callback.answer("این عملیات فقط داخل گروه انجام می‌شود.", show_alert=True)
                raise CancelHandler()
            uid = callback.from_user.id
            active = _active(main)
            if active is None:
                await callback.answer("⚠️ نوبت فعالی وجود ندارد.", show_alert=True)
                raise CancelHandler()
            owner = _uid(main, active)
            if uid != getattr(main, "moderator_id", None) and uid != owner:
                await callback.answer("⛔ فقط صاحب نوبت یا گرداننده می‌تواند نکست بزند.", show_alert=True)
                raise CancelHandler()
            try:
                clicked = int(str(callback.data).split("_", 1)[1])
            except Exception:
                await callback.answer("⚠️ نوبت نامعتبر است.", show_alert=True)
                raise CancelHandler()
            if clicked != active:
                await callback.answer("⚠️ این نوبت دیگر فعال نیست.", show_alert=True)
                raise CancelHandler()
            if time.time() - getattr(main, "_gm3_last_next", 0) < 1:
                await callback.answer("⏳ لطفاً کمی صبر کنید.", show_alert=True)
                raise CancelHandler()
            main._gm3_last_next = time.time()
            task = getattr(main, "turn_timer_task", None)
            if task and not task.done():
                task.cancel()

            if getattr(main, "challenge_mode", False):
                main.challenge_mode = False
                if getattr(main, "paused_main_player", None) is not None:
                    if getattr(main, "post_challenge_advance", False):
                        main.current_turn_index += 1
                    main.post_challenge_advance = False
                    main.paused_main_player = None
                    main.paused_main_duration = None
                main._gm_extra_turn_active = False
            else:
                active_seat = int(active)
                pending = getattr(main, "pending_challenges", {})
                if not main._gm_extra_phase and active_seat not in main._gm_muted_next_round and active_seat in pending:
                    challenger_id = pending.pop(active_seat)
                    challenger_seat = next((s for s, u in (getattr(main, "player_slots", {}) or {}).items() if u == challenger_id), None)
                    if challenger_seat is not None:
                        main.paused_main_player = active_seat
                        main.paused_main_duration = 120
                        main.post_challenge_advance = True
                        main.challenge_mode = True
                        await main.start_turn(challenger_seat, duration=60, is_challenge=True)
                        await callback.answer()
                        return
                main.current_turn_index += 1

            await callback.answer()
            await advance()

        next_v3.__name__ = "next_turn"
        next_v3._gm3 = True
        dp.register_callback_query_handler(next_v3, lambda c: str(c.data or "").startswith("next_"), state="*")
        _front(reg, next_v3)

    async def challenge_guard(callback):
        requester = callback.from_user.id
        active = _active(main)
        requester_seat = next((s for s, u in (getattr(main, "player_slots", {}) or {}).items() if u == requester), None)
        if getattr(main, "_gm_extra_turn_active", False):
            await callback.answer("⛔ ترن اضافه امکان چالش ندارد.", show_alert=True)
            raise CancelHandler()
        if requester_seat is not None and int(requester_seat) in main._gm_muted_next_round:
            await callback.answer("⛔ این بازیکن در این دور سکوت است و نمی‌تواند چالش بگیرد.", show_alert=True)
            raise CancelHandler()
        if requester_seat is None or active is None or int(requester_seat) != int(active) or getattr(main, "challenge_mode", False):
            await callback.answer("⛔ فقط صاحب نوبت عادی می‌تواند درخواست چالش بدهد.", show_alert=True)
            raise CancelHandler()

    dp.register_callback_query_handler(challenge_guard, lambda c: str(c.data or "").startswith("challenge_request_"), state="*")
    for item in list(reg):
        if getattr(_handler(item), "__name__", "") == "challenge_guard":
            _front(reg, item)
            break

    old_start = getattr(main, "start_turn", None)
    if old_start is not None and not getattr(old_start, "_gm3_start", False):
        @wraps(old_start)
        async def start_v3(seat, duration=120, is_challenge=False):
            _ensure(main)
            try:
                seat = int(seat)
            except Exception:
                return await old_start(seat, duration=duration, is_challenge=is_challenge)
            if not is_challenge and seat in main._gm_extra_seats and main._gm_extra_phase:
                return await extra_turn(seat)
            if not is_challenge and seat in main._gm_muted_next_round and _active(main) == seat:
                uid = _uid(main, seat)
                name = _name(main, seat)
                mention = f"<a href='tg://user?id={uid}'>{html.escape(name)}</a>" if uid else html.escape(name)
                await main.bot.send_message(_gid(main), f"🔇 {mention} این دور سکوت است و نوبت صحبت ندارد.")
                await asyncio.sleep(1)
                main.current_turn_index += 1
                return await advance()
            main._gm_extra_turn_active = bool(not is_challenge and seat in main._gm_extra_seats and main._gm_extra_phase)
            return await old_start(seat, duration=duration, is_challenge=is_challenge)
        start_v3._gm3_start = True
        main.start_turn = start_v3

    main._gm3_installed = True
    logging.info("GM V3 authoritative controls installed")
    return True
