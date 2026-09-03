"""Authoritative day/round lifecycle for speaking turns.

Lifecycle:
    start day -> prepare normal order -> normal turns -> one-shot extras -> day end

Mute is a NEXT-DAY rule. It is selected during the current day, survives the
current round/day-end reset, and is consumed when the next day's first normal
turn is prepared. Extra turns are a CURRENT-DAY rule: they are executed once,
after all normal speakers finish, and then the day ends.

The module intentionally keeps ``turn_order`` stable during a normal round.
It never inserts an extra turn into the normal order and never rewrites the
order in the middle of a round.
"""
from __future__ import annotations

import asyncio
import html
import time
from functools import wraps

from aiogram.dispatcher.handler import CancelHandler
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def _handler(item):
    return getattr(item, "handler", None)


def _gid(main):
    for obj in (main, getattr(main, "addons", None)):
        for attr in ("group_chat_id", "ALLOWED_GROUP_ID", "GROUP_ID", "group_id"):
            value = getattr(obj, attr, None)
            if value:
                try:
                    return int(value)
                except (TypeError, ValueError):
                    pass
    return None


def _players(main):
    slots = getattr(main, "player_slots", {}) or {}
    legacy = getattr(main, "players", {}) or {}
    out = []
    for raw_seat, raw_uid in slots.items():
        try:
            seat, uid = int(raw_seat), int(raw_uid)
        except (TypeError, ValueError):
            continue
        fallback = legacy.get(uid)
        try:
            name = main.display_name(uid, fallback)
        except Exception:
            name = fallback
        if isinstance(fallback, dict):
            name = name or fallback.get("nickname") or fallback.get("full_name") or fallback.get("first_name")
        if not name or str(name).strip() in {"?", "❓", "None", "بازیکن"}:
            name = fallback if isinstance(fallback, str) else None
        if not name:
            name = f"بازیکن {seat}"
        out.append((seat, uid, str(name)))
    return sorted(out)


def _uid(main, seat):
    try:
        return (getattr(main, "player_slots", {}) or {}).get(int(seat))
    except Exception:
        return None


def _name(main, seat):
    uid = _uid(main, seat)
    for s, u, name in _players(main):
        if int(s) == int(seat) and int(u) == int(uid):
            return name
    return f"بازیکن {seat}"


def _ensure(main):
    defaults = {
        "_gm_muted_next_round": set(),
        "_gm_extra_next_round": set(),
        "_gm_day_order": [],
        "_gm_extra_seats": set(),
        "_gm_extra_phase": False,
        "_gm_extra_turn_active": False,
        "_gm_day_prepared": False,
        "_gm_normal_round_finished": False,
        "_gm_last_next": 0.0,
    }
    for key, value in defaults.items():
        if not hasattr(main, key):
            setattr(main, key, value.copy() if isinstance(value, (set, list, dict)) else value)


def _active(main):
    try:
        return int(main.turn_order[main.current_turn_index])
    except Exception:
        return None


def _moderator(main, uid):
    try:
        uid = int(uid)
    except Exception:
        return False
    for obj in (main, getattr(main, "addons", None)):
        try:
            mid = getattr(obj, "moderator_id", None)
            if mid is not None and int(mid) == uid:
                return True
        except Exception:
            pass
    return False


async def _cancel_timer(main):
    task = getattr(main, "turn_timer_task", None)
    if task and not task.done():
        task.cancel()


async def _delete_turn_message(main):
    mid = getattr(main, "current_turn_message_id", None)
    gid = _gid(main)
    if not gid or not mid:
        return
    try:
        await main.bot.delete_message(gid, int(mid))
    except Exception:
        pass
    main.current_turn_message_id = None


async def _hydrate(main, uid):
    gid = _gid(main)
    if not gid or not uid:
        return
    try:
        member = await main.bot.get_chat_member(gid, int(uid))
        name = getattr(getattr(member, "user", None), "full_name", None)
        if name and isinstance(getattr(main, "players", None), dict):
            current = main.players.get(int(uid))
            if not current or str(current).strip() in {"?", "❓", "None", "بازیکن"}:
                main.players[int(uid)] = name
    except Exception:
        pass


async def _skip_muted(main, seat):
    uid = _uid(main, seat)
    await _hydrate(main, uid)
    name = _name(main, seat)
    mention = f"<a href='tg://user?id={int(uid)}'>{html.escape(name)}</a>" if uid else html.escape(name)
    await main.bot.send_message(_gid(main), f"🔇 {mention} این دور سکوت است و نوبت صحبت ندارد.", parse_mode="HTML")
    await asyncio.sleep(1)


def _clean_order(main, source=None):
    occupied = {s for s, _, _ in _players(main)}
    source = list(source if source is not None else getattr(main, "turn_order", []) or [])
    result, seen = [], set()
    for raw in source:
        try:
            seat = int(raw)
        except (TypeError, ValueError):
            continue
        if seat in occupied and seat not in seen:
            result.append(seat)
            seen.add(seat)
    for seat in sorted(occupied):
        if seat not in seen:
            result.append(seat)
    return result


async def _end_day(main):
    _ensure(main)
    await _cancel_timer(main)
    await _delete_turn_message(main)
    main._gm_extra_turn_active = False
    main._gm_extra_phase = False
    main._gm_extra_seats.clear()
    # IMPORTANT: do not clear _gm_muted_next_round here. It belongs to the
    # next day and must survive reset_round_data()/end-of-day cleanup.
    main._gm_extra_next_round.clear()
    main._gm_normal_round_finished = True
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton("🌙 شروع فاز شب", callback_data="start_night"))
    await main.bot.send_message(_gid(main), "✅ همه بازیکنا صحبت کردن. فاز روز تموم شد.", reply_markup=kb)


def install(main):
    _ensure(main)
    dp = getattr(main, "dp", None)
    registry = getattr(getattr(dp, "callback_query_handlers", None), "handlers", None)
    if registry is None or getattr(main, "_round_state_final_v8", False):
        return False

    # Remove all stale Next handlers. V8 is the only round-advance authority.
    registry[:] = [x for x in registry if getattr(_handler(x), "__name__", "") not in {"next_turn", "next_v3", "next_v6", "next_v7"}]

    old_start = getattr(main, "start_turn", None)
    if old_start is None:
        return False

    async def start_normal(seat):
        _ensure(main)
        seat = int(seat)
        muted_active = {int(x) for x in getattr(main, "_gm_muted_active", set())}
        if seat in muted_active:
            await _cancel_timer(main)
            await _skip_muted(main, seat)
            main.current_turn_index += 1
            return await advance()
        main._gm_extra_turn_active = False
        return await old_start(seat, duration=120, is_challenge=False)

    async def start_extra(seat):
        _ensure(main)
        seat = int(seat)
        uid = _uid(main, seat)
        if not uid:
            main.current_turn_index += 1
            return await advance()
        await _hydrate(main, uid)
        name = _name(main, seat)
        await _cancel_timer(main)
        main._gm_extra_turn_active = True
        main.challenge_mode = False
        msg = await main.bot.send_message(
            _gid(main),
            f"➕ <b>ترن اضافه</b>\n🎙 نوبت اضافه <a href='tg://user?id={int(uid)}'>{html.escape(name)}</a> است.\n🚫 این ترن امکان چالش ندارد.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(row_width=1).add(
                InlineKeyboardButton("⏭ نکست", callback_data=f"next_{seat}")
            ),
        )
        main.current_turn_message_id = msg.message_id
        countdown = getattr(main, "countdown", None)
        if countdown:
            main.turn_timer_task = asyncio.create_task(countdown(seat, 120, msg.message_id, False))

    async def prepare_new_day_if_needed():
        _ensure(main)
        if main._gm_day_prepared:
            return
        # At this point reset_round_data() has normally run and the base order
        # for the new day has been created by the legacy flow.
        base = _clean_order(main)
        if not base:
            return
        main._gm_day_order = list(base)
        main.turn_order = list(base)
        main.current_turn_index = 0
        main._gm_extra_phase = False
        main._gm_extra_turn_active = False
        main._gm_extra_seats.clear()
        # Consume the pending mute only NOW, at the new day's boundary.
        main._gm_muted_active = {int(x) for x in getattr(main, "_gm_muted_next_round", set()) if int(x) in set(base)}
        main._gm_muted_next_round.clear()
        main._gm_day_prepared = True
        main._gm_normal_round_finished = False

    async def advance():
        _ensure(main)
        if not main._gm_day_prepared:
            await prepare_new_day_if_needed()
        while True:
            order = [int(x) for x in (getattr(main, "turn_order", []) or [])]
            idx = int(getattr(main, "current_turn_index", 0))
            if idx < len(order):
                seat = order[idx]
                if main._gm_extra_phase:
                    if seat in main._gm_extra_seats:
                        return await start_extra(seat)
                    main.current_turn_index += 1
                    continue
                return await start_normal(seat)

            if main._gm_extra_phase:
                # Extra phase is one-shot and always ends the day.
                return await _end_day(main)

            # Normal speaking round is complete. Extras selected for THIS day
            # execute once now; they are never appended to the normal order.
            base = list(main._gm_day_order or order)
            pending = {int(x) for x in getattr(main, "_gm_extra_next_round", set())}
            extras = [s for s in base if s in pending]
            main._gm_extra_next_round.clear()
            if extras:
                main._gm_extra_seats = set(extras)
                main._gm_extra_phase = True
                main._gm_extra_turn_active = False
                main.turn_order = list(extras)
                main.current_turn_index = 0
                return await advance()

            return await _end_day(main)

    async def start_v8(seat, duration=120, is_challenge=False):
        _ensure(main)
        seat = int(seat)
        # Challenge turns must always pass through the legacy challenge path.
        if is_challenge:
            return await old_start(seat, duration=duration, is_challenge=True)
        if not main._gm_day_prepared:
            await prepare_new_day_if_needed()
        if main._gm_extra_phase and seat in main._gm_extra_seats:
            return await start_extra(seat)
        muted_active = {int(x) for x in getattr(main, "_gm_muted_active", set())}
        if seat in muted_active:
            return await start_normal(seat)
        return await old_start(seat, duration=duration, is_challenge=False)

    start_v8._v8_start = True
    main.start_turn = start_v8

    async def next_v8(callback):
        if getattr(getattr(callback, "message", None), "chat", None) and callback.message.chat.type == "private":
            await callback.answer("این عملیات فقط داخل گروه انجام می‌شود.", show_alert=True)
            raise CancelHandler()
        active = _active(main)
        if active is None:
            await callback.answer("⚠️ نوبت فعالی وجود ندارد.", show_alert=True)
            raise CancelHandler()
        uid = int(callback.from_user.id)
        owner = _uid(main, active)
        # In challenge mode the actual actor is the challenger. The challenge
        # authority normally maps this state before reaching us; use the actor
        # set as a fallback for authorization.
        actors = {int(x) for x in getattr(main, "active_challenger_seats", set()) or set()}
        allowed_owner = int(owner or -1) == uid or _moderator(main, uid) or uid in {int(_uid(main, s) or -1) for s in actors}
        if not allowed_owner:
            await callback.answer("⛔ فقط صاحب نوبت، چالش‌گر یا گرداننده می‌تواند نکست بزند.", show_alert=True)
            raise CancelHandler()
        try:
            clicked = int(str(callback.data).split("_", 1)[1])
        except Exception:
            await callback.answer("⚠️ نوبت نامعتبر است.", show_alert=True)
            raise CancelHandler()
        # In challenge mode callback_data still identifies the paused target;
        # otherwise it must identify the current actor.
        if not getattr(main, "challenge_mode", False) and clicked != active:
            await callback.answer("⚠️ این نوبت دیگر فعال نیست.", show_alert=True)
            raise CancelHandler()
        now = time.time()
        if now - float(getattr(main, "_gm_last_next", 0.0)) < 0.8:
            await callback.answer("⏳ لطفاً کمی صبر کنید.", show_alert=True)
            raise CancelHandler()
        main._gm_last_next = now
        await _delete_turn_message(main)
        await _cancel_timer(main)

        if getattr(main, "challenge_mode", False):
            target = getattr(main, "paused_main_player", None)
            after = bool(getattr(main, "post_challenge_advance", False))
            main.challenge_mode = False
            main.paused_main_player = None
            main.paused_main_duration = None
            main.post_challenge_advance = False
            main.active_challenger_seats = set()
            if target is not None and not after:
                try:
                    main.current_turn_index = main.turn_order.index(int(target))
                except Exception:
                    pass
            elif after:
                main.current_turn_index += 1
            main._gm_extra_turn_active = False
            await callback.answer()
            return await advance()

        active_seat = int(active)
        pending = getattr(main, "pending_challenges", {}) or {}
        if not main._gm_extra_phase and active_seat in pending:
            challenger_id = pending.pop(active_seat)
            challenger_seat = next((int(s) for s, u in (getattr(main, "player_slots", {}) or {}).items() if int(u) == int(challenger_id)), None)
            if challenger_seat is not None:
                main.paused_main_player = active_seat
                main.paused_main_duration = 120
                main.challenge_mode = True
                main.post_challenge_advance = True
                main.active_challenger_seats = {challenger_seat}
                await callback.answer()
                return await old_start(challenger_seat, duration=60, is_challenge=True)

        main.current_turn_index += 1
        main._gm_extra_turn_active = False
        await callback.answer()
        return await advance()

    next_v8._v8_next = True
    dp.register_callback_query_handler(next_v8, lambda c: str(c.data or "").startswith("next_"), state="*")
    registry.insert(0, registry.pop())

    # New normal day detection: wrap reset_round_data without deleting the
    # pending mute selection. It only resets the transient challenge/turn data.
    old_reset = getattr(main, "reset_round_data", None)
    if old_reset is not None and not getattr(old_reset, "_v8_reset", False):
        @wraps(old_reset)
        def reset_v8(*args, **kwargs):
            result = old_reset(*args, **kwargs)
            _ensure(main)
            main._gm_day_prepared = False
            main._gm_day_order = []
            main._gm_extra_phase = False
            main._gm_extra_turn_active = False
            main._gm_extra_seats.clear()
            main._gm_muted_active = set()
            main._gm_normal_round_finished = False
            # _gm_muted_next_round intentionally survives.
            return result
        reset_v8._v8_reset = True
        main.reset_round_data = reset_v8

    main._round_state_final_v8 = True
    return True
