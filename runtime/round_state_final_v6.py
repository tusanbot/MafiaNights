"""Final round lifecycle authority.

Rules:
- A mute selected during a round applies to the NEXT normal round.
- A muted seat never receives a timed turn message; a short informational
  message is sent and the next eligible turn starts one second later.
- Extra turns run exactly once after the current normal round, have no timer
  challenge button, and never become part of the next normal order.
- After the extra phase, a clean normal round starts with muted players
  removed. When that normal round finishes, the legacy day-end behaviour is
  reproduced so the night button is shown.
"""
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
    for obj in (main, getattr(main, "addons", None)):
        for attr in ("group_chat_id", "ALLOWED_GROUP_ID", "GROUP_ID", "group_id"):
            value = getattr(obj, attr, None)
            if value:
                try:
                    return int(value)
                except (TypeError, ValueError):
                    pass
    return None


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
    if not hasattr(main, "_gm_round_initialized"):
        main._gm_round_initialized = False


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


def _normal_order(main):
    """Return the current round's real order, excluding one-shot extras."""
    _ensure(main)
    occupied = {s for s, _, _ in _players(main)}
    extras = {int(s) for s in main._gm_extra_seats}
    source = list(main._gm_normal_order or getattr(main, "turn_order", []) or [])
    result, seen = [], set()
    for raw in source:
        try:
            seat = int(raw)
        except (TypeError, ValueError):
            continue
        if seat in occupied and seat not in extras and seat not in seen:
            result.append(seat)
            seen.add(seat)
    for seat in sorted(occupied):
        if seat not in extras and seat not in seen:
            result.append(seat)
    return result


def _active(main):
    try:
        return int(main.turn_order[main.current_turn_index])
    except Exception:
        return None


def _is_moderator(main, uid):
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


async def _send_muted(main, seat):
    uid = _uid(main, seat)
    await _hydrate(main, uid)
    name = _name(main, seat)
    if uid:
        mention = f"<a href='tg://user?id={int(uid)}'>{html.escape(name)}</a>"
    else:
        mention = html.escape(name)
    await main.bot.send_message(
        _gid(main),
        f"🔇 {mention} این دور سکوت است و نوبت صحبت ندارد.",
        parse_mode="HTML",
    )


async def _cancel_timer(main):
    task = getattr(main, "turn_timer_task", None)
    if task and not task.done():
        task.cancel()


async def _delete_turn_message(main):
    message_id = getattr(main, "current_turn_message_id", None)
    if not message_id:
        return
    try:
        await main.bot.delete_message(_gid(main), int(message_id))
    except Exception:
        pass
    main.current_turn_message_id = None


async def _end_day(main):
    await _cancel_timer(main)
    main._gm_extra_turn_active = False
    main._gm_extra_phase = False
    main._gm_extra_seats.clear()
    main._gm_extra_next_round.clear()
    main._gm_normal_order = list(getattr(main, "turn_order", []) or [])
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton("🌙 شروع فاز شب", callback_data="start_night"))
    await main.bot.send_message(
        _gid(main),
        "✅ همه بازیکنا صحبت کردن. فاز روز تموم شد.",
        reply_markup=kb,
    )


def install(main):
    _ensure(main)
    dp = getattr(main, "dp", None)
    registry = getattr(getattr(dp, "callback_query_handlers", None), "handlers", None)
    if registry is None:
        return False
    if getattr(main, "_round_state_final_v6", False):
        return True

    # Capture the base order whenever a fresh normal round is explicitly started.
    for item in list(registry):
        fn = _handler(item)
        if getattr(fn, "__name__", "") == "start_round_handler" and not getattr(fn, "_v6_round", False):
            original = fn
            @wraps(original)
            async def start_round_v6(callback, _original=original):
                _ensure(main)
                main._gm_extra_phase = False
                main._gm_extra_turn_active = False
                main._gm_extra_seats.clear()
                main._gm_normal_order = []
                main._gm_round_initialized = True
                result = await _original(callback)
                main._gm_normal_order = [int(x) for x in (getattr(main, "turn_order", []) or [])]
                return result
            start_round_v6._v6_round = True
            item.handler = start_round_v6
            registry.insert(0, registry.pop(registry.index(item)))
            break

    # Remove every older next handler. This layer is terminal.
    registry[:] = [x for x in registry if getattr(_handler(x), "__name__", "") != "next_turn"]

    old_start = getattr(main, "start_turn", None)
    if old_start is None:
        return False

    async def start_normal(seat):
        seat = int(seat)
        if seat in main._gm_muted_next_round and not main._gm_extra_phase:
            await _cancel_timer(main)
            await _send_muted(main, seat)
            await asyncio.sleep(1)
            main.current_turn_index += 1
            return await advance()
        main._gm_extra_turn_active = False
        return await old_start(seat, duration=120, is_challenge=False)

    async def start_extra(seat):
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
            f"➕ <b>ترن اضافه</b>\n🎙 نوبت اضافه <a href='tg://user?id={uid}'>{html.escape(name)}</a> است.\n🚫 این ترن امکان چالش ندارد.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(row_width=1).add(
                InlineKeyboardButton("⏭ نکست", callback_data=f"next_{seat}")
            ),
        )
        main.current_turn_message_id = msg.message_id
        countdown = getattr(main, "countdown", None)
        if countdown:
            main.turn_timer_task = asyncio.create_task(countdown(seat, 120, msg.message_id, False))

    async def begin_next_normal_round():
        # The mute set is consumed here, exactly once, for the next normal round.
        base = list(main._gm_normal_order or _normal_order(main))
        muted = {int(x) for x in main._gm_muted_next_round}
        next_order = [s for s in base if s not in muted]
        main._gm_muted_next_round.clear()
        main._gm_extra_next_round.clear()
        main._gm_extra_seats.clear()
        main._gm_extra_phase = False
        main._gm_extra_turn_active = False
        main._gm_normal_order = list(next_order)
        main.turn_order = list(next_order)
        main.current_turn_index = 0
        if not next_order:
            return await _end_day(main)
        return await start_normal(next_order[0])

    async def advance():
        _ensure(main)
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
                # All one-shot extras have finished. Start a clean next normal round.
                return await begin_next_normal_round()

            # Normal round finished. Consume extra selections once, before the next round.
            base = list(main._gm_normal_order or _normal_order(main))
            pending = {int(x) for x in main._gm_extra_next_round}
            muted = {int(x) for x in main._gm_muted_next_round}
            extras = [s for s in base if s in pending and s not in muted]
            if extras:
                main._gm_normal_order = list(base)
                main._gm_extra_seats = set(extras)
                main._gm_extra_next_round.clear()
                main._gm_extra_phase = True
                main._gm_extra_turn_active = False
                main.turn_order = list(extras)
                main.current_turn_index = 0
                return await advance()

            # No extras: the current normal round is the day's last round.
            return await _end_day(main)

    async def start_v6(seat, duration=120, is_challenge=False):
        _ensure(main)
        seat = int(seat)
        if not is_challenge and main._gm_extra_phase and seat in main._gm_extra_seats:
            return await start_extra(seat)
        if not is_challenge and seat in main._gm_muted_next_round:
            return await start_normal(seat)
        return await old_start(seat, duration=duration, is_challenge=is_challenge)

    start_v6._v6_start = True
    main.start_turn = start_v6

    async def next_v6(callback):
        if getattr(getattr(callback, "message", None), "chat", None) and callback.message.chat.type == "private":
            await callback.answer("این عملیات فقط داخل گروه انجام می‌شود.", show_alert=True)
            raise CancelHandler()
        active = _active(main)
        if active is None:
            await callback.answer("⚠️ نوبت فعالی وجود ندارد.", show_alert=True)
            raise CancelHandler()
        uid = callback.from_user.id
        owner = _uid(main, active)
        if not _is_moderator(main, uid) and int(uid) != int(owner or -1):
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
        now = time.time()
        if now - getattr(main, "_gm6_last_next", 0) < 1:
            await callback.answer("⏳ لطفاً کمی صبر کنید.", show_alert=True)
            raise CancelHandler()
        main._gm6_last_next = now
        await _delete_turn_message(main)
        await _cancel_timer(main)

        # Challenge turn: return to its paused main turn (before) or advance (after).
        if getattr(main, "challenge_mode", False):
            main.challenge_mode = False
            target = getattr(main, "paused_main_player", None)
            after = bool(getattr(main, "post_challenge_advance", False))
            main.paused_main_player = None
            main.paused_main_duration = None
            main.post_challenge_advance = False
            if target is not None and not after:
                # Before-challenge: target still has to speak.
                try:
                    active_index = main.turn_order.index(int(target))
                    main.current_turn_index = active_index
                except Exception:
                    pass
            elif after:
                main.current_turn_index += 1
            main._gm_extra_turn_active = False
            await callback.answer()
            return await advance()

        # An AFTER challenge is accepted by the target and executed when the target presses Next.
        active_seat = int(active)
        pending = getattr(main, "pending_challenges", {}) or {}
        if not main._gm_extra_phase and active_seat in pending:
            challenger_id = pending.pop(active_seat)
            challenger_seat = next((int(s) for s, u in (getattr(main, "player_slots", {}) or {}).items() if int(u) == int(challenger_id)), None)
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
        return await advance()

    next_v6.__name__ = "next_turn"
    next_v6._v6_next = True
    dp.register_callback_query_handler(next_v6, lambda c: str(getattr(c, "data", "") or "").startswith("next_"), state="*")
    for item in list(registry):
        if _handler(item) is next_v6:
            registry.insert(0, registry.pop(registry.index(item)))
            break

    # Remove the obsolete V3 challenge guard; final_challenge_moderator_fix owns request auth.
    registry[:] = [x for x in registry if getattr(_handler(x), "__name__", "") != "challenge_guard"]

    main._round_state_final_v6 = True
    logging.info("V6: final mute/extra/round lifecycle installed")
    return True
