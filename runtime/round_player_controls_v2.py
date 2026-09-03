"""Authoritative player mute/extra-turn controls.

This patch intentionally sits at the end of the runtime stack. It fixes three
state-machine problems in the first implementation: player labels are
hydrated from Telegram, mute is applied to the next normal round, and an
extra-turn grant is consumed exactly once. Challenge requests are also bound
to the active player's normal turn and are disabled during extra turns.
"""
from __future__ import annotations

import html
import logging
from functools import wraps

from aiogram.dispatcher.handler import CancelHandler
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def _handler(item):
    return getattr(item, "handler", None)


def _callback(item):
    return getattr(item, "callback", None)


def _group_id(main):
    for attr in ("group_chat_id", "ALLOWED_GROUP_ID", "GROUP_ID", "group_id"):
        value = getattr(main, attr, None)
        if value:
            try:
                return int(value)
            except (TypeError, ValueError):
                pass
    return None


def _players(main):
    slots = getattr(main, "player_slots", {}) or {}
    names = getattr(main, "players", {}) or {}
    result = []
    for raw_seat, raw_uid in slots.items():
        try:
            seat = int(raw_seat)
            uid = int(raw_uid)
        except (TypeError, ValueError):
            continue
        name = None
        try:
            name = main.display_name(uid, names.get(uid))
        except Exception:
            pass
        if not name:
            value = names.get(uid)
            if isinstance(value, str):
                name = value
            elif isinstance(value, dict):
                name = value.get("nickname") or value.get("full_name") or value.get("first_name")
            else:
                name = getattr(value, "nickname", None) or getattr(value, "full_name", None) or getattr(value, "first_name", None)
        if not name or str(name).strip() in {"?", "❓", "بازیکن", "None"}:
            name = f"بازیکن {seat}"
        result.append((seat, uid, str(name)))
    return sorted(result, key=lambda x: x[0])


def _ensure_state(main):
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


def _active_seat(main):
    if getattr(main, "challenge_mode", False):
        active = list(getattr(main, "active_challenger_seats", set()) or set())
        return active[0] if len(active) == 1 else None
    try:
        return main.turn_order[main.current_turn_index]
    except Exception:
        return None


def _find_handler(registry, name):
    for item in registry:
        fn = _handler(item)
        if getattr(fn, "__name__", "") == name:
            return item
    return None


def _move_front(registry, item):
    if item in registry:
        registry.insert(0, registry.pop(registry.index(item)))


async def _can_manage(main, uid):
    if uid == getattr(main, "moderator_id", None):
        return True
    gid = _group_id(main)
    if not gid:
        return False
    try:
        admins = await main.bot.get_chat_administrators(gid)
        return any(getattr(getattr(a, "user", None), "id", None) == uid for a in admins)
    except Exception:
        return False


async def _hydrate_names(main):
    gid = _group_id(main)
    if not gid:
        return
    players = getattr(main, "players", None)
    if not isinstance(players, dict):
        return
    for _, uid, _ in _players(main):
        try:
            member = await main.bot.get_chat_member(gid, uid)
            user = getattr(member, "user", None)
            full_name = getattr(user, "full_name", None) or getattr(user, "first_name", None)
            if full_name:
                current = players.get(uid)
                if not current or str(current).strip() in {"?", "❓", "بازیکن", "None"}:
                    players[uid] = full_name
        except Exception:
            logging.debug("player name hydration failed for %s", uid, exc_info=True)


def _selection_markup(main, mode):
    _ensure_state(main)
    active = main._gm_muted_next_round if mode == "mute" else main._gm_extra_next_round
    icon = "🔇" if mode == "mute" else "➕"
    rows = []
    for seat, _, name in _players(main):
        mark = " ✅" if seat in active else ""
        rows.append([InlineKeyboardButton(
            f"{icon} صندلی {seat} — {html.escape(name)}{mark}",
            callback_data=f"gm2:{mode}:{seat}",
        )])
    rows.append([InlineKeyboardButton("⬅️ مدیریت بازی", callback_data="manage_game")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _replace_with_next(main, seat):
    gid = _group_id(main)
    mid = getattr(main, "current_turn_message_id", None)
    if not gid or not mid:
        return
    kb = InlineKeyboardMarkup(row_width=1).add(
        InlineKeyboardButton("⏭ نکست", callback_data=f"next_{seat}")
    )
    try:
        await main.bot.edit_message_reply_markup(gid, mid, reply_markup=kb)
    except Exception:
        logging.debug("cannot replace challenge keyboard on extra turn", exc_info=True)


def install(main):
    _ensure_state(main)
    dp = main.dp
    registry = getattr(getattr(dp, "callback_query_handlers", None), "handlers", None)
    if registry is None:
        return False

    async def open_selection(callback, mode):
        if not await _can_manage(main, callback.from_user.id):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
            raise CancelHandler()
        if not getattr(main, "game_running", False):
            await callback.answer("⚠️ این گزینه فقط هنگام اجرای بازی قابل استفاده است.", show_alert=True)
            raise CancelHandler()
        await _hydrate_names(main)
        title = "سکوت بازیکن" if mode == "mute" else "ترن اضافه"
        text = f"{'🔇' if mode == 'mute' else '➕'} <b>{title}</b>\n\nبازیکن موردنظر را انتخاب کنید."
        if mode == "mute":
            text += "\n🔇 بازیکن انتخاب‌شده در <b>دور بعد</b> ترن عادی نخواهد داشت."
        else:
            text += "\n➕ بازیکن انتخاب‌شده فقط <b>یک ترن اضافه</b> بعد از پایان دور جاری خواهد داشت و آن ترن چالش ندارد."
        await callback.message.edit_text(text, reply_markup=_selection_markup(main, mode), parse_mode="HTML")
        await callback.answer()

    async def toggle(callback, mode):
        if not await _can_manage(main, callback.from_user.id):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
            raise CancelHandler()
        try:
            seat = int(str(callback.data).rsplit(":", 1)[1])
        except Exception:
            await callback.answer("⚠️ بازیکن نامعتبر است.", show_alert=True)
            raise CancelHandler()
        valid = {s for s, _, _ in _players(main)}
        if seat not in valid:
            await callback.answer("⚠️ این بازیکن دیگر در بازی نیست.", show_alert=True)
            raise CancelHandler()

        if mode == "mute":
            active = main._gm_muted_next_round
            other = main._gm_extra_next_round
        else:
            active = main._gm_extra_next_round
            other = main._gm_muted_next_round

        if seat in active:
            active.remove(seat)
            state = "لغو شد"
        else:
            active.add(seat)
            # A seat cannot simultaneously be muted and receive an extra turn.
            other.discard(seat)
            state = "فعال شد"

        await callback.message.edit_reply_markup(reply_markup=_selection_markup(main, mode))
        await callback.answer(f"{'سکوت' if mode == 'mute' else 'ترن اضافه'} صندلی {seat} {state}.")
        raise CancelHandler()

    # The legacy controls use gm:* callbacks. Give the corrected namespace
    # priority without deleting the old UI, so stale buttons remain harmless.
    dp.register_callback_query_handler(lambda c: open_selection(c, "mute"), lambda c: c.data == "gm:mute", state="*")
    dp.register_callback_query_handler(lambda c: open_selection(c, "extra"), lambda c: c.data == "gm:extra", state="*")
    dp.register_callback_query_handler(lambda c: toggle(c, "mute"), lambda c: str(c.data or "").startswith("gm2:mute:"), state="*")
    dp.register_callback_query_handler(lambda c: toggle(c, "extra"), lambda c: str(c.data or "").startswith("gm2:extra:"), state="*")

    new_handlers = getattr(dp.callback_query_handlers, "handlers", [])
    # Move our four handlers to the front in reverse order so their final
    # order is selection/toggle priority.
    for item in list(new_handlers):
        cb = _callback(item)
        if cb is None:
            continue
        name = getattr(cb, "__name__", "")
        if name == "<lambda>":
            # Lambdas are identified by their predicate; just move the last
            # four registrations by their object identity from the tail.
            pass
    for item in list(new_handlers)[-4:]:
        _move_front(new_handlers, item)

    # Install one authoritative Next handler. Keep main.next_turn() as the
    # actual legacy state-machine primitive.
    old_next = getattr(main, "next_turn", None)
    if old_next is not None:
        for item in list(registry):
            if getattr(_handler(item), "__name__", "") == "next_turn":
                registry.remove(item)

        async def next_authoritative(callback):
            if getattr(getattr(callback, "message", None), "chat", None) is not None and callback.message.chat.type == "private":
                await callback.answer("این عملیات فقط داخل گروه انجام می‌شود.", show_alert=True)
                raise CancelHandler()
            uid = getattr(getattr(callback, "from_user", None), "id", None)
            active = _active_seat(main)
            owner = (getattr(main, "player_slots", {}) or {}).get(active)
            if uid != getattr(main, "moderator_id", None) and uid != owner:
                await callback.answer("⛔ فقط صاحب نوبت یا گرداننده می‌تواند نکست بزند.", show_alert=True)
                raise CancelHandler()
            try:
                clicked = int(str(callback.data).split("_", 1)[1])
            except Exception:
                await callback.answer("⚠️ نوبت نامعتبر است.", show_alert=True)
                raise CancelHandler()
            if active is None or clicked != active:
                await callback.answer("⚠️ این نوبت دیگر فعال نیست.", show_alert=True)
                raise CancelHandler()

            _ensure_state(main)
            order = list(getattr(main, "turn_order", []) or [])
            try:
                idx = int(main.current_turn_index)
            except Exception:
                idx = -1

            # Capture the canonical normal order only at a normal-round start.
            if not main._gm_extra_phase and order and not main._gm_normal_order:
                main._gm_normal_order = list(order)

            if order and idx == len(order) - 1 and not main._gm_extra_phase:
                base = list(main._gm_normal_order or order)
                muted = set(main._gm_muted_next_round)
                extras = [s for s in base if s in main._gm_extra_next_round and s not in muted]
                # Consume the grant immediately. It can therefore never be
                # scheduled again by a second pass through the round boundary.
                main._gm_extra_next_round.clear()
                if extras:
                    main.turn_order = base + extras
                    main._gm_extra_seats = set(extras)
                    main._gm_extra_phase = True
                else:
                    main.turn_order = [s for s in base if s not in muted]
                    main._gm_muted_next_round.clear()
                    main._gm_extra_seats.clear()
                    main._gm_normal_order = list(main.turn_order)
                    main.current_turn_index = -1

            elif order and idx == len(order) - 1 and main._gm_extra_phase:
                base = list(main._gm_normal_order or order)
                muted = set(main._gm_muted_next_round)
                main.turn_order = [s for s in base if s not in muted]
                main._gm_muted_next_round.clear()
                main._gm_extra_seats.clear()
                main._gm_extra_phase = False
                main._gm_normal_order = list(main.turn_order)
                main.current_turn_index = -1

            gid = _group_id(main)
            old_id = getattr(main, "current_turn_message_id", None) or getattr(callback.message, "message_id", None)
            if gid and old_id:
                try:
                    await main.bot.delete_message(gid, old_id)
                except Exception:
                    pass
            main.current_turn_message_id = None
            return await old_next(callback)

        next_authoritative.__name__ = "next_turn"
        next_authoritative._gm_v2_next = True
        dp.register_callback_query_handler(next_authoritative, lambda c: str(c.data or "").startswith("next_"), state="*")
        _move_front(registry, next_authoritative)

    # Mark extra turns at the point where the turn is actually created, then
    # remove challenge controls from that turn's message.
    start = getattr(main, "start_turn", None)
    if start is not None and not getattr(start, "_gm_v2_start", False):
        @wraps(start)
        async def start_turn_v2(seat, duration=120, is_challenge=False):
            _ensure_state(main)
            main._gm_extra_turn_active = bool(not is_challenge and seat in main._gm_extra_seats and main._gm_extra_phase)
            result = await start(seat, duration=duration, is_challenge=is_challenge)
            if main._gm_extra_turn_active:
                await _replace_with_next(main, seat)
            return result
        start_turn_v2._gm_v2_start = True
        main.start_turn = start_turn_v2

    # Replace the already-registered challenge_request handler rather than
    # stacking another callback handler. This avoids the old 'spinner/loading'
    # behaviour caused by a lower-priority handler winning first.
    item = _find_handler(registry, "challenge_request")
    if item is not None:
        original = _handler(item)
        if not getattr(original, "_gm_v2_challenge", False):
            @wraps(original)
            async def challenge_request_v2(callback, _original=original):
                if getattr(main, "_gm_extra_turn_active", False):
                    await callback.answer("⛔ ترن اضافه امکان چالش ندارد.", show_alert=True)
                    raise CancelHandler()
                requester = getattr(getattr(callback, "from_user", None), "id", None)
                requester_seat = next((s for s, uid in (getattr(main, "player_slots", {}) or {}).items() if uid == requester), None)
                active = _active_seat(main)
                if requester_seat is None or active is None or int(requester_seat) != int(active):
                    await callback.answer("⛔ فقط بازیکنِ صاحب نوبت می‌تواند درخواست چالش بدهد.", show_alert=True)
                    raise CancelHandler()
                if requester_seat in getattr(main, "_gm_muted_next_round", set()):
                    await callback.answer("⛔ این بازیکن در این دور سکوت است و امکان چالش ندارد.", show_alert=True)
                    raise CancelHandler()
                return await _original(callback)
            challenge_request_v2._gm_v2_challenge = True
            item.handler = challenge_request_v2
            _move_front(registry, item)

    main._gm_round_controls_v2 = True
    logging.info("GM controls V2 installed: hydrated names, one-shot extra turns, next-round mute, strict challenge guard")
    return True
