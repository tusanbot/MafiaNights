"""Terminal challenge authority for the v8 round lifecycle.

Rules:
- The current normal speaker is the challenge TARGET.
- Any other eligible player may request once per day/round.
- The target accepts BEFORE or AFTER, or rejects.
- BEFORE pauses the target, runs the challenger, then resumes the target.
- AFTER lets the target finish, then runs the challenger, then advances.
- A target can only have one accepted challenge in its turn.
- Muted-active and extra-turn players cannot request challenges.
- A mute scheduled for the NEXT day does not affect the current day.
- Extra turns never expose a challenge button.
"""
from __future__ import annotations

import html
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
    for raw_seat, raw_uid in (getattr(main, "player_slots", {}) or {}).items():
        try:
            if int(raw_uid) == uid:
                return int(raw_seat)
        except Exception:
            pass
    return None


def _players(main):
    out = []
    legacy = getattr(main, "players", {}) or {}
    for raw_seat, raw_uid in (getattr(main, "player_slots", {}) or {}).items():
        try:
            seat, uid = int(raw_seat), int(raw_uid)
        except Exception:
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
        out.append((seat, uid, str(name or f"بازیکن {seat}")))
    return sorted(out)


def _name(main, uid):
    for _, player_uid, name in _players(main):
        if int(player_uid) == int(uid):
            return name
    return f"بازیکن {uid}"


def _active(main):
    try:
        return int(main.turn_order[main.current_turn_index])
    except Exception:
        return None


def _ensure(main):
    if not isinstance(getattr(main, "challenge_target_locked", None), set):
        main.challenge_target_locked = set()
    if not isinstance(getattr(main, "challenge_request_messages", None), dict):
        main.challenge_request_messages = {}
    if not isinstance(getattr(main, "challenge_requests", None), dict):
        main.challenge_requests = {}
    if not isinstance(getattr(main, "_gm_challenge_used", None), set):
        main._gm_challenge_used = set()


async def _delete(main, message_id):
    gid = _gid(main)
    if not gid or not message_id:
        return
    try:
        await main.bot.delete_message(gid, int(message_id))
    except Exception:
        pass


async def _delete_all_requests(main, target_seat):
    _ensure(main)
    requests = main.challenge_requests.get(int(target_seat), {}) or {}
    for challenger_id in list(requests):
        mid = main.challenge_request_messages.pop((int(target_seat), int(challenger_id)), None)
        if mid:
            await _delete(main, mid)
    main.challenge_requests.pop(int(target_seat), None)


async def _lock_turn_button(main, target_seat):
    mid = getattr(main, "current_turn_message_id", None)
    gid = _gid(main)
    if not gid or not mid:
        return
    kb = InlineKeyboardMarkup(row_width=1).add(
        InlineKeyboardButton("⏭ نکست", callback_data=f"next_{int(target_seat)}")
    )
    try:
        await main.bot.edit_message_reply_markup(gid, int(mid), reply_markup=kb)
    except Exception:
        pass


def _eligible(main, requester_id, target_seat):
    _ensure(main)
    requester_id = int(requester_id)
    target_seat = int(target_seat)
    if not getattr(main, "game_running", False):
        return False, "⚠️ بازی در حال اجرا نیست."
    active = _active(main)
    if active != target_seat:
        return False, "⚠️ این نوبت دیگر فعال نیست."
    target_id = _uid(main, target_seat)
    if not target_id:
        return False, "⚠️ صاحب نوبت پیدا نشد."
    requester_seat = _seat(main, requester_id)
    if requester_seat is None:
        return False, "❌ فقط بازیکنان همین بازی می‌توانند درخواست چالش بدهند."
    if requester_id == int(target_id):
        return False, "❌ صاحب نوبت نمی‌تواند از خودش درخواست چالش بدهد."
    if requester_seat in {int(x) for x in getattr(main, "_gm_muted_active", set())}:
        return False, "🔇 بازیکن ساکت‌شده نمی‌تواند درخواست چالش بدهد."
    if getattr(main, "_gm_extra_turn_active", False) or getattr(main, "_gm_extra_phase", False):
        return False, "➕ در ترن اضافه امکان درخواست چالش وجود ندارد."
    if getattr(main, "challenge_mode", False):
        return False, "⚔️ یک چالش در حال اجراست."
    if not getattr(main, "challenge_active", False):
        return False, "⚔️ چالش در این بازی خاموش است."
    if target_seat in main.challenge_target_locked:
        return False, "⛔ برای این نوبت دیگر چالش پذیرفته نمی‌شود."
    if requester_id in main._gm_challenge_used:
        return False, "⚠️ هر بازیکن فقط یک بار در این دور می‌تواند درخواست چالش بدهد."
    return True, ""


def install(main):
    _ensure(main)
    dp = getattr(main, "dp", None)
    reg = getattr(getattr(dp, "callback_query_handlers", None), "handlers", None)
    if reg is None or getattr(main, "_round_challenge_final_v9", False):
        return False

    # Remove older challenge request/response callbacks by their callback data
    # prefixes. The terminal handlers below must be the first matching ones.
    prefixes = ("challenge_request_", "accept_before_", "accept_after_", "reject_")
    reg[:] = [x for x in reg if not any(str(getattr(_handler(x), "_callback_prefix", "")).startswith(p) for p in prefixes)]

    old_keyboard = getattr(main, "turn_keyboard", None)
    if old_keyboard is not None:
        @wraps(old_keyboard)
        def turn_keyboard_v9(seat, is_challenge=False):
            _ensure(main)
            try:
                seat = int(seat)
            except Exception:
                return old_keyboard(seat, is_challenge)
            if is_challenge or getattr(main, "_gm_extra_turn_active", False) or seat in {int(x) for x in getattr(main, "_gm_extra_seats", set())} or seat in {int(x) for x in getattr(main, "_gm_muted_active", set())}:
                return InlineKeyboardMarkup(row_width=1).add(
                    InlineKeyboardButton("⏭ نکست", callback_data=f"next_{seat}")
                )
            kb = InlineKeyboardMarkup(row_width=1)
            kb.add(InlineKeyboardButton("⏭ نکست", callback_data=f"next_{seat}"))
            if getattr(main, "challenge_active", False) and seat not in main.challenge_target_locked:
                kb.add(InlineKeyboardButton("⚔️ درخواست چالش", callback_data=f"challenge_request_{seat}"))
            return kb
        turn_keyboard_v9._v9_keyboard = True
        main.turn_keyboard = turn_keyboard_v9

    async def request(callback):
        _ensure(main)
        try:
            target_seat = int(str(callback.data).split("_", 2)[2])
        except Exception:
            await callback.answer("⚠️ درخواست نامعتبر است.", show_alert=True)
            raise CancelHandler()
        requester_id = int(callback.from_user.id)
        ok, reason = _eligible(main, requester_id, target_seat)
        if not ok:
            await callback.answer(reason, show_alert=True)
            raise CancelHandler()
        target_id = int(_uid(main, target_seat))
        requests = main.challenge_requests.setdefault(target_seat, {})
        if requester_id in requests:
            await callback.answer("⚠️ درخواست شما قبلاً ثبت شده است.", show_alert=True)
            raise CancelHandler()
        # Once per round means a rejected request is also consumed.
        main._gm_challenge_used.add(requester_id)
        requests[requester_id] = "pending"
        challenger_name = _name(main, requester_id)
        target_name = _name(main, target_id)
        kb = InlineKeyboardMarkup(row_width=2).add(
            InlineKeyboardButton("✅ قبول (قبل)", callback_data=f"accept_before_{requester_id}_{target_id}"),
            InlineKeyboardButton("✅ قبول (بعد)", callback_data=f"accept_after_{requester_id}_{target_id}"),
            InlineKeyboardButton("❌ رد", callback_data=f"reject_{requester_id}_{target_id}"),
        )
        msg = await main.bot.send_message(
            _gid(main),
            f"⚔️ {html.escape(challenger_name)} از {html.escape(target_name)} درخواست چالش کرد.",
            reply_markup=kb,
            parse_mode="HTML",
        )
        main.challenge_request_messages[(target_seat, requester_id)] = msg.message_id
        await callback.answer("⏳ درخواست چالش برای صاحب نوبت ارسال شد.")
        raise CancelHandler()

    async def response(callback):
        _ensure(main)
        parts = str(callback.data or "").split("_")
        if parts[0] == "reject":
            if len(parts) != 3:
                await callback.answer("⚠️ درخواست نامعتبر است.", show_alert=True)
                raise CancelHandler()
            timing = None
        elif len(parts) == 4 and parts[0] == "accept":
            timing = parts[1]
        else:
            await callback.answer("⚠️ درخواست نامعتبر است.", show_alert=True)
            raise CancelHandler()
        try:
            challenger_id = int(parts[-2])
            target_id = int(parts[-1])
        except Exception:
            await callback.answer("⚠️ بازیکن نامعتبر است.", show_alert=True)
            raise CancelHandler()
        target_seat = _seat(main, target_id)
        challenger_seat = _seat(main, challenger_id)
        if target_seat is None or challenger_seat is None:
            await callback.answer("⚠️ یکی از بازیکنان دیگر در بازی نیست.", show_alert=True)
            raise CancelHandler()
        if _active(main) != target_seat:
            await callback.answer("⚠️ این نوبت دیگر فعال نیست.", show_alert=True)
            raise CancelHandler()
        if int(callback.from_user.id) != target_id:
            await callback.answer("❌ فقط صاحب نوبت می‌تواند درخواست را مدیریت کند.", show_alert=True)
            raise CancelHandler()
        requests = main.challenge_requests.get(target_seat, {}) or {}
        if requests.get(challenger_id) != "pending":
            await callback.answer("⚠️ این درخواست دیگر فعال نیست.", show_alert=True)
            raise CancelHandler()
        target_name = _name(main, target_id)
        challenger_name = _name(main, challenger_id)
        if parts[0] == "reject":
            requests.pop(challenger_id, None)
            mid = main.challenge_request_messages.pop((target_seat, challenger_id), None)
            if mid:
                await _delete(main, mid)
            await main.bot.send_message(_gid(main), f"🚫 {html.escape(target_name)} درخواست چالش {html.escape(challenger_name)} را رد کرد.", parse_mode="HTML")
            await callback.answer("❌ درخواست رد شد.")
            raise CancelHandler()

        await _delete_all_requests(main, target_seat)
        main.challenge_target_locked.add(target_seat)
        await _lock_turn_button(main, target_seat)
        if timing == "before":
            main.paused_main_player = target_seat
            main.paused_main_duration = 120
            main.challenge_mode = True
            main.post_challenge_advance = False
            main.active_challenger_seats = {challenger_seat}
            try:
                if main.turn_timer_task and not main.turn_timer_task.done():
                    main.turn_timer_task.cancel()
            except Exception:
                pass
            await main.bot.send_message(_gid(main), f"⚔️ {html.escape(target_name)} به {html.escape(challenger_name)} چالش داد (قبل از صحبت).", parse_mode="HTML")
            await main.start_turn(challenger_seat, duration=60, is_challenge=True)
        else:
            main.pending_challenges[target_seat] = challenger_id
            await main.bot.send_message(_gid(main), f"⚔️ {html.escape(target_name)} چالش {html.escape(challenger_name)} را برای بعد از صحبت پذیرفت.", parse_mode="HTML")
        await callback.answer("✅ چالش پذیرفته شد.")
        raise CancelHandler()

    request._callback_prefix = "challenge_request_"
    response._callback_prefix = "accept_"
    reg.append(type("HandlerWrap", (), {"handler": request})()) if False else None
    dp.register_callback_query_handler(request, lambda c: str(c.data or "").startswith("challenge_request_"), state="*")
    dp.register_callback_query_handler(response, lambda c: str(c.data or "").startswith(("accept_before_", "accept_after_", "reject_")), state="*")
    # aiogram appends registrations; move the two terminal handlers to front.
    for fn in (request, response):
        for item in list(reg):
            if _handler(item) is fn:
                try:
                    reg.insert(0, reg.pop(reg.index(item)))
                except ValueError:
                    pass
                break

    old_reset = getattr(main, "reset_round_data", None)
    if old_reset is not None and not getattr(old_reset, "_v9_reset", False):
        @wraps(old_reset)
        def reset_v9(*args, **kwargs):
            result = old_reset(*args, **kwargs)
            _ensure(main)
            main._gm_challenge_used.clear()
            main.challenge_target_locked.clear()
            main.challenge_requests.clear()
            main.challenge_request_messages.clear()
            main.pending_challenges = {}
            main.active_challenger_seats = set()
            return result
        reset_v9._v9_reset = True
        main.reset_round_data = reset_v9

    main._round_challenge_final_v9 = True
    return True
