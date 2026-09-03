"""Single authoritative round/turn engine for MafiaNights.

This module intentionally owns ALL next/start/challenge transitions. It is
installed last so legacy handlers cannot compete with it. A normal day is a
finite sequence: normal speakers -> explicitly selected extra turns -> day end.
The engine never starts a new normal round from NEXT; a new day is started only
by the existing start_new_day action.
"""
from __future__ import annotations

import asyncio
import html
import logging
import time
from aiogram.dispatcher.handler import CancelHandler
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


NEXT_PREFIX = "next_"
CHALLENGE_REQUEST_PREFIX = "challenge_request_"


def _handler(item):
    return getattr(item, "handler", None)


def _gid(main):
    for obj in (main, getattr(main, "addons", None)):
        for key in ("group_chat_id", "ALLOWED_GROUP_ID", "GROUP_ID", "group_id"):
            value = getattr(obj, key, None)
            if value:
                try:
                    return int(value)
                except (TypeError, ValueError):
                    pass
    return None


def _uid(main, seat):
    try:
        return (getattr(main, "player_slots", {}) or {}).get(int(seat))
    except Exception:
        return None


def _seat(main, uid):
    try:
        uid = int(uid)
    except Exception:
        return None
    for seat, player_uid in (getattr(main, "player_slots", {}) or {}).items():
        try:
            if int(player_uid) == uid:
                return int(seat)
        except Exception:
            pass
    return None


def _stored_name(main, uid):
    players = getattr(main, "players", {}) or {}
    try:
        value = players.get(uid)
    except Exception:
        value = None
    if isinstance(value, dict):
        return value.get("nickname") or value.get("full_name") or value.get("first_name")
    if value and str(value).strip() not in {"?", "❓", "None", "بازیکن"}:
        return str(value)
    return None


def _display_name(main, uid, fallback=None):
    # Nickname manager first.
    try:
        manager = getattr(main, "nicknames", None)
        for method in ("get_nick", "get"):
            fn = getattr(manager, method, None)
            if fn:
                value = fn(int(uid))
                if value and str(value).strip() not in {"?", "❓", "None", "بازیکن"}:
                    return str(value)
    except Exception:
        pass
    # Main display_name, but only accept real values.
    try:
        value = main.display_name(int(uid), fallback)
        if value and str(value).strip() not in {"?", "❓", "None", "بازیکن"}:
            return str(value)
    except Exception:
        pass
    value = _stored_name(main, uid)
    if value:
        return value
    if fallback and str(fallback).strip() not in {"?", "❓", "None", "بازیکن"}:
        return str(fallback)
    return None


async def _resolve_name(main, uid, fallback=None):
    """Resolve a real Telegram name before the first turn message.

    The old code could reach the turn message with a missing players entry and
    permanently render the generic fallback. We hydrate the canonical players
    mapping from Telegram before rendering whenever possible.
    """
    name = _display_name(main, uid, fallback)
    if name:
        return name
    gid = _gid(main)
    if gid and uid:
        try:
            member = await main.bot.get_chat_member(gid, int(uid))
            user = getattr(member, "user", None)
            name = getattr(user, "full_name", None) or getattr(user, "first_name", None)
            if name:
                players = getattr(main, "players", None)
                if isinstance(players, dict):
                    players[int(uid)] = name
                return str(name)
        except Exception as exc:
            logging.warning("stable round: unable to hydrate name for %s: %s", uid, exc)
    return f"بازیکن {int(_seat(main, uid) or 0)}"


def _active(main):
    try:
        return int(main.turn_order[main.current_turn_index])
    except Exception:
        return None


def _ensure(main):
    defaults = {
        "_stable_day_active": False,
        "_stable_day_ended": False,
        "_stable_phase": "normal",
        "_stable_extra_seats": set(),
        "_stable_extra_used": set(),
        "_stable_normal_order": [],
        "_stable_next_lock": 0.0,
        "_stable_challenge_used": set(),
        "_stable_challenge_locked": set(),
        "_stable_challenge_requests": {},
        "_stable_challenge_request_messages": {},
    }
    for key, value in defaults.items():
        if not hasattr(main, key):
            setattr(main, key, value.copy() if isinstance(value, (set, list, dict)) else value)


def _base_order(main):
    occupied = set()
    for seat in (getattr(main, "player_slots", {}) or {}):
        try:
            occupied.add(int(seat))
        except Exception:
            pass
    source = list(getattr(main, "_stable_normal_order", []) or [])
    if not source:
        source = list(getattr(main, "turn_order", []) or [])
    result, seen = [], set()
    for raw in source:
        try:
            seat = int(raw)
        except Exception:
            continue
        if seat in occupied and seat not in seen:
            result.append(seat)
            seen.add(seat)
    for seat in sorted(occupied):
        if seat not in seen:
            result.append(seat)
    return result


async def _cancel_timer(main):
    task = getattr(main, "turn_timer_task", None)
    if task and not task.done():
        task.cancel()
    main.turn_timer_task = None


async def _delete_turn_message(main):
    gid = _gid(main)
    mid = getattr(main, "current_turn_message_id", None)
    if gid and mid:
        try:
            await main.bot.delete_message(gid, int(mid))
        except Exception:
            pass
    main.current_turn_message_id = None


def _keyboard(main, seat, is_challenge=False):
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton("⏭ نکست", callback_data=f"next_{int(seat)}"))
    if is_challenge or getattr(main, "_stable_phase", "normal") != "normal":
        return kb
    if not getattr(main, "challenge_active", False):
        return kb
    if int(seat) in getattr(main, "_stable_challenge_locked", set()):
        return kb
    kb.add(InlineKeyboardButton("⚔️ درخواست چالش", callback_data=f"challenge_request_{int(seat)}"))
    return kb


async def _start_turn(main, seat, duration=120, is_challenge=False):
    _ensure(main)
    try:
        seat = int(seat)
    except Exception:
        return None
    uid = _uid(main, seat)
    if not uid:
        logging.error("stable round: seat %s has no player", seat)
        return None
    if getattr(main, "_stable_day_ended", False) and not is_challenge:
        return None
    name = await _resolve_name(main, uid, _stored_name(main, uid))
    mention = f"<a href='tg://user?id={int(uid)}'>{html.escape(name)}</a>"
    await _cancel_timer(main)
    main.challenge_mode = bool(is_challenge)
    if is_challenge:
        main._stable_phase = "challenge"
    elif getattr(main, "_stable_phase", "normal") != "extra":
        main._stable_phase = "normal"
    prefix = "🟥" if is_challenge else "🟦"
    text = f"{prefix} ⏳ {duration//60:02d}:{duration%60:02d}\n🎙 نوبت صحبت {mention} است. ({duration} ثانیه)"
    msg = await main.bot.send_message(_gid(main), text, parse_mode="HTML", reply_markup=_keyboard(main, seat, is_challenge))
    main.current_turn_message_id = msg.message_id
    countdown = getattr(main, "countdown", None)
    if countdown:
        main.turn_timer_task = asyncio.create_task(countdown(seat, duration, msg.message_id, is_challenge))
    return msg.message_id


async def _start_extra(main, seat):
    _ensure(main)
    uid = _uid(main, seat)
    if not uid or seat in main._stable_extra_used:
        return await _advance(main)
    main._stable_extra_used.add(int(seat))
    main._stable_phase = "extra"
    name = await _resolve_name(main, uid, _stored_name(main, uid))
    mention = f"<a href='tg://user?id={int(uid)}'>{html.escape(name)}</a>"
    await _cancel_timer(main)
    main._gm_extra_turn_active = True
    main.challenge_mode = False
    msg = await main.bot.send_message(
        _gid(main),
        f"➕ <b>ترن اضافه</b>\n🎙 نوبت اضافه {mention} است.\n🚫 این ترن امکان چالش ندارد.",
        parse_mode="HTML",
        reply_markup=_keyboard(main, seat, True),
    )
    main.current_turn_message_id = msg.message_id
    countdown = getattr(main, "countdown", None)
    if countdown:
        main.turn_timer_task = asyncio.create_task(countdown(seat, 120, msg.message_id, False))
    return msg.message_id


async def _end_day(main):
    _ensure(main)
    if main._stable_day_ended:
        return
    main._stable_day_ended = True
    main._stable_day_active = False
    main._stable_phase = "ended"
    main._gm_extra_turn_active = False
    main._gm_extra_phase = False
    await _cancel_timer(main)
    await _delete_turn_message(main)
    main.challenge_mode = False
    main.pending_challenges = {}
    main.active_challenger_seats = set()
    main.current_turn_index = len(getattr(main, "turn_order", []) or [])
    gid = _gid(main)
    if gid:
        await main.bot.send_message(
            gid,
            "✅ همه بازیکنا صحبت کردن. فاز روز تموم شد.",
            reply_markup=InlineKeyboardMarkup(row_width=1).add(
                InlineKeyboardButton("🌙 شروع فاز شب", callback_data="start_night")
            ),
        )


async def _advance(main):
    _ensure(main)
    if main._stable_day_ended:
        return
    while True:
        order = [int(x) for x in (getattr(main, "turn_order", []) or [])]
        idx = int(getattr(main, "current_turn_index", 0))
        if idx < len(order):
            seat = order[idx]
            if main._stable_phase == "extra":
                if seat in main._stable_extra_seats:
                    return await _start_extra(main, seat)
                main.current_turn_index += 1
                continue
            # Normal phase.
            muted = {int(x) for x in getattr(main, "_gm_muted_active", set()) or set()}
            if seat in muted:
                await _cancel_timer(main)
                uid = _uid(main, seat)
                name = await _resolve_name(main, uid)
                await main.bot.send_message(_gid(main), f"🔇 {html.escape(name)} این دور سکوت است و نوبت صحبت ندارد.")
                main.current_turn_index += 1
                continue
            return await _start_turn(main, seat, 120, False)

        # End of normal speakers: consume explicitly selected extras once.
        if main._stable_phase == "normal":
            pending = {int(x) for x in getattr(main, "_gm_extra_next_round", set()) or set()}
            base = list(main._stable_normal_order or _base_order(main))
            extras = [seat for seat in base if seat in pending]
            main._gm_extra_next_round.clear()
            if extras:
                main._stable_extra_seats = set(extras)
                main._stable_extra_used.clear()
                main._stable_phase = "extra"
                main._gm_extra_phase = True
                main._gm_extra_turn_active = False
                main.turn_order = list(extras)
                main.current_turn_index = 0
                continue
            return await _end_day(main)

        # Extra phase can only finish the current day. It can NEVER start a new
        # normal round here.
        return await _end_day(main)


def _clear_legacy_handlers(reg):
    """Remove all old transition handlers; stable engine is sole authority."""
    kept = []
    for item in list(reg):
        fn = _handler(item)
        name = getattr(fn, "__name__", "")
        if (
            name in {
                "next_turn", "next_v3", "next_v6", "next_v7", "next_authoritative",
                "next_terminal", "next_turn_day_end_guard", "start_round_handler",
                "handle_start_turn", "challenge_request", "challenge_choice",
                "handle_challenge_response",
            }
            or getattr(fn, "_v5_next", False)
            or getattr(fn, "_v8_next", False)
            or getattr(fn, "_v10_next", False)
            or getattr(fn, "_day_end_guard", False)
            or getattr(fn, "_callback_prefix", "") in {
                CHALLENGE_REQUEST_PREFIX, "accept_", "reject_"
            }
        ):
            continue
        kept.append(item)
    reg[:] = kept


def install(main):
    _ensure(main)
    dp = getattr(main, "dp", None)
    reg = getattr(getattr(dp, "callback_query_handlers", None), "handlers", None)
    if reg is None or getattr(main, "_stable_round_engine_installed", False):
        return False
    _clear_legacy_handlers(reg)

    async def start_round(callback):
        if callback.message and callback.message.chat.type == "private":
            await callback.answer("این عملیات فقط داخل گروه انجام می‌شود.", show_alert=True)
            raise CancelHandler()
        if callback.from_user.id != getattr(main, "moderator_id", None):
            await callback.answer("⛔ فقط گرداننده می‌تواند دور را شروع کند.", show_alert=True)
            raise CancelHandler()
        if not getattr(main, "game_running", False):
            await callback.answer("⚠️ بازی در حال اجرا نیست.", show_alert=True)
            raise CancelHandler()
        _ensure(main)
        if main._stable_day_active and not main._stable_day_ended:
            await callback.answer("⚠️ این دور قبلاً شروع شده است.", show_alert=True)
            raise CancelHandler()
        base = _base_order(main)
        if not base:
            await callback.answer("⚠️ بازیکنی برای شروع نوبت وجود ندارد.", show_alert=True)
            raise CancelHandler()
        main._stable_day_active = True
        main._stable_day_ended = False
        main._stable_phase = "normal"
        main._stable_normal_order = list(base)
        main._stable_extra_seats = set()
        main._stable_extra_used = set()
        main._stable_challenge_used = set()
        main._stable_challenge_locked = set()
        main._stable_challenge_requests = {}
        main._stable_challenge_request_messages = {}
        main.challenge_mode = False
        main.pending_challenges = {}
        main.active_challenger_seats = set()
        main.turn_order = list(base)
        main.current_turn_index = 0
        main._gm_extra_phase = False
        main._gm_extra_turn_active = False
        main._gm_extra_seats = set()
        main._gm_normal_order = list(base)
        await _advance(main)
        await callback.answer("✅ دور شروع شد.")
        raise CancelHandler()

    async def next_handler(callback):
        _ensure(main)
        if callback.message and callback.message.chat.type == "private":
            await callback.answer("این عملیات فقط داخل گروه انجام می‌شود.", show_alert=True)
            raise CancelHandler()
        if main._stable_day_ended:
            await callback.answer("ℹ️ فاز روز قبلاً تمام شده است.", show_alert=True)
            raise CancelHandler()
        active = _active(main)
        if active is None:
            await callback.answer("⚠️ نوبت فعالی وجود ندارد.", show_alert=True)
            raise CancelHandler()
        try:
            clicked = int(str(callback.data).split("_", 1)[1])
        except Exception:
            await callback.answer("⚠️ نوبت نامعتبر است.", show_alert=True)
            raise CancelHandler()
        if clicked != active and not getattr(main, "challenge_mode", False):
            await callback.answer("⚠️ این نوبت دیگر فعال نیست.", show_alert=True)
            raise CancelHandler()
        uid = int(callback.from_user.id)
        owner = _uid(main, active)
        challenger_seats = {int(x) for x in getattr(main, "active_challenger_seats", set()) or set()}
        challenger_uids = {int(_uid(main, s) or -1) for s in challenger_seats}
        if uid != int(getattr(main, "moderator_id", -1) or -1) and uid != int(owner or -1) and uid not in challenger_uids:
            await callback.answer("⛔ فقط صاحب نوبت، چالش‌گر یا گرداننده می‌تواند نکست بزند.", show_alert=True)
            raise CancelHandler()
        now = time.time()
        if now - float(getattr(main, "_stable_next_lock", 0.0)) < 0.8:
            await callback.answer("⏳ لطفاً کمی صبر کنید.", show_alert=True)
            raise CancelHandler()
        main._stable_next_lock = now
        await callback.answer()
        await _cancel_timer(main)
        await _delete_turn_message(main)

        # A challenge turn is not a normal turn transition.
        if getattr(main, "challenge_mode", False):
            target = getattr(main, "paused_main_player", None)
            after = bool(getattr(main, "post_challenge_advance", False))
            main.challenge_mode = False
            main.active_challenger_seats = set()
            main._stable_phase = "normal"
            main._gm_extra_turn_active = False
            main.paused_main_player = None
            main.paused_main_duration = None
            main.post_challenge_advance = False
            if target is not None:
                if after:
                    main.current_turn_index += 1
                else:
                    try:
                        main.current_turn_index = main.turn_order.index(int(target))
                    except ValueError:
                        pass
            return await _advance(main)

        # AFTER challenge: current speaker finishes, then challenger runs once.
        pending = getattr(main, "pending_challenges", {}) or {}
        if main._stable_phase == "normal" and active in pending:
            challenger_id = pending.pop(active)
            challenger_seat = _seat(main, challenger_id)
            if challenger_seat is not None:
                main.paused_main_player = active
                main.paused_main_duration = 120
                main.post_challenge_advance = True
                main.challenge_mode = True
                main.active_challenger_seats = {int(challenger_seat)}
                main._stable_phase = "challenge"
                return await _start_turn(main, challenger_seat, 60, True)

        # Normal/extra next: advance exactly one index. At the end _advance()
        # either runs explicitly selected extras or terminates the day.
        main.current_turn_index += 1
        return await _advance(main)

    async def challenge_request(callback):
        _ensure(main)
        try:
            target = int(str(callback.data).split("_", 2)[2])
        except Exception:
            await callback.answer("⚠️ درخواست نامعتبر است.", show_alert=True)
            raise CancelHandler()
        active = _active(main)
        requester = int(callback.from_user.id)
        requester_seat = _seat(main, requester)
        if active != target or requester_seat is None or requester == int(_uid(main, target) or -1):
            await callback.answer("⛔ درخواست چالش در این نوبت مجاز نیست.", show_alert=True)
            raise CancelHandler()
        if not getattr(main, "challenge_active", False) or getattr(main, "_stable_phase", "normal") != "normal":
            await callback.answer("⚔️ چالش در این نوبت فعال نیست.", show_alert=True)
            raise CancelHandler()
        if requester in main._stable_challenge_used:
            await callback.answer("⚠️ هر بازیکن فقط یک بار در این دور می‌تواند درخواست چالش بدهد.", show_alert=True)
            raise CancelHandler()
        if target in main._stable_challenge_locked:
            await callback.answer("⛔ برای این نوبت دیگر چالش پذیرفته نمی‌شود.", show_alert=True)
            raise CancelHandler()
        main._stable_challenge_used.add(requester)
        reqs = main._stable_challenge_requests.setdefault(target, {})
        reqs[requester] = "pending"
        target_id = int(_uid(main, target))
        challenger_name = await _resolve_name(main, requester)
        target_name = await _resolve_name(main, target_id)
        kb = InlineKeyboardMarkup(row_width=2).add(
            InlineKeyboardButton("✅ قبول (قبل)", callback_data=f"accept_before_{requester}_{target_id}"),
            InlineKeyboardButton("✅ قبول (بعد)", callback_data=f"accept_after_{requester}_{target_id}"),
            InlineKeyboardButton("❌ رد", callback_data=f"reject_{requester}_{target_id}"),
        )
        msg = await main.bot.send_message(
            _gid(main),
            f"⚔️ {html.escape(challenger_name)} از {html.escape(target_name)} درخواست چالش کرد.",
            reply_markup=kb,
            parse_mode="HTML",
        )
        main._stable_challenge_request_messages[(target, requester)] = msg.message_id
        await callback.answer("⏳ درخواست چالش ارسال شد.")
        raise CancelHandler()

    async def challenge_response(callback):
        _ensure(main)
        parts = str(callback.data or "").split("_")
        if parts[0] == "reject" and len(parts) == 3:
            timing = None
        elif parts[0] == "accept" and len(parts) == 4 and parts[1] in {"before", "after"}:
            timing = parts[1]
        else:
            await callback.answer("⚠️ درخواست نامعتبر است.", show_alert=True)
            raise CancelHandler()
        challenger_id, target_id = int(parts[-2]), int(parts[-1])
        target_seat = _seat(main, target_id)
        challenger_seat = _seat(main, challenger_id)
        if target_seat is None or challenger_seat is None or _active(main) != target_seat:
            await callback.answer("⚠️ این نوبت دیگر فعال نیست.", show_alert=True)
            raise CancelHandler()
        if int(callback.from_user.id) != target_id:
            await callback.answer("❌ فقط صاحب نوبت می‌تواند درخواست را مدیریت کند.", show_alert=True)
            raise CancelHandler()
        reqs = main._stable_challenge_requests.get(target_seat, {})
        if reqs.get(challenger_id) != "pending":
            await callback.answer("⚠️ این درخواست دیگر فعال نیست.", show_alert=True)
            raise CancelHandler()
        target_name = await _resolve_name(main, target_id)
        challenger_name = await _resolve_name(main, challenger_id)
        if timing is None:
            reqs.pop(challenger_id, None)
            await main.bot.send_message(_gid(main), f"🚫 {html.escape(target_name)} درخواست چالش {html.escape(challenger_name)} را رد کرد.", parse_mode="HTML")
            await callback.answer("❌ درخواست رد شد.")
            raise CancelHandler()
        # Accept exactly one challenge for this target.
        reqs.clear()
        main._stable_challenge_request_messages.clear()
        main._stable_challenge_locked.add(target_seat)
        await _cancel_timer(main)
        if timing == "before":
            main.paused_main_player = target_seat
            main.paused_main_duration = 120
            main.post_challenge_advance = False
            main.challenge_mode = True
            main.active_challenger_seats = {int(challenger_seat)}
            main._stable_phase = "challenge"
            await main.bot.send_message(_gid(main), f"⚔️ {html.escape(target_name)} چالش {html.escape(challenger_name)} را قبل از صحبت پذیرفت.", parse_mode="HTML")
            await _start_turn(main, challenger_seat, 60, True)
        else:
            main.pending_challenges[target_seat] = challenger_id
            await main.bot.send_message(_gid(main), f"⚔️ {html.escape(target_name)} چالش {html.escape(challenger_name)} را بعد از صحبت پذیرفت.", parse_mode="HTML")
        await callback.answer("✅ چالش پذیرفته شد.")
        raise CancelHandler()

    async def manage(callback, mode):
        if callback.from_user.id != getattr(main, "moderator_id", None):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
            raise CancelHandler()
        _ensure(main)
        target = main._gm_muted_next_round if mode == "mute" else main._gm_extra_next_round
        icon = "🔇" if mode == "mute" else "➕"
        title = "سکوت بازیکن" if mode == "mute" else "ترن اضافه"
        rows = []
        for seat in sorted((getattr(main, "player_slots", {}) or {})):
            uid = _uid(main, seat)
            name = await _resolve_name(main, uid)
            mark = " ✅" if int(seat) in target else ""
            rows.append([InlineKeyboardButton(f"{icon} صندلی {seat} — {name}{mark}", callback_data=f"stable:{mode}:{seat}")])
        rows.append([InlineKeyboardButton("⬅️ مدیریت بازی", callback_data="manage_game")])
        await callback.message.edit_text(
            f"{icon} <b>{title}</b>\n\nبازیکن موردنظر را انتخاب کنید.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
            parse_mode="HTML",
        )
        await callback.answer()
        raise CancelHandler()

    async def toggle_manage(callback, mode):
        if callback.from_user.id != getattr(main, "moderator_id", None):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
            raise CancelHandler()
        try:
            seat = int(str(callback.data).rsplit(":", 1)[1])
        except Exception:
            await callback.answer("⚠️ صندلی نامعتبر است.", show_alert=True)
            raise CancelHandler()
        target = main._gm_muted_next_round if mode == "mute" else main._gm_extra_next_round
        opposite = main._gm_extra_next_round if mode == "mute" else main._gm_muted_next_round
        if seat in target:
            target.remove(seat)
            status = "لغو شد"
        else:
            target.add(seat)
            opposite.discard(seat)
            status = "فعال شد"
        await callback.answer(f"{('سکوت' if mode == 'mute' else 'ترن اضافه')} {status}.")
        await manage(callback, mode)

    dp.register_callback_query_handler(start_round, lambda c: c.data in {"start_round", "start_turn"}, state="*")
    dp.register_callback_query_handler(next_handler, lambda c: str(c.data or "").startswith(NEXT_PREFIX), state="*")
    dp.register_callback_query_handler(challenge_request, lambda c: str(c.data or "").startswith(CHALLENGE_REQUEST_PREFIX), state="*")
    dp.register_callback_query_handler(challenge_response, lambda c: str(c.data or "").startswith(("accept_before_", "accept_after_", "reject_")), state="*")
    dp.register_callback_query_handler(lambda c: manage(c, "mute"), lambda c: c.data == "gm:mute", state="*")
    dp.register_callback_query_handler(lambda c: manage(c, "extra"), lambda c: c.data == "gm:extra", state="*")
    dp.register_callback_query_handler(lambda c: toggle_manage(c, "mute"), lambda c: str(c.data or "").startswith("stable:mute:"), state="*")
    dp.register_callback_query_handler(lambda c: toggle_manage(c, "extra"), lambda c: str(c.data or "").startswith("stable:extra:"), state="*")

    # Stable keyboard replaces every previous turn keyboard implementation.
    main.turn_keyboard = lambda seat, is_challenge=False: _keyboard(main, seat, is_challenge)
    main._stable_round_engine_installed = True
    logging.info("Stable round engine installed: one next authority, finite day lifecycle, hydrated names")
    return True
