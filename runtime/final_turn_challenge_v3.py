from __future__ import annotations

import html
import logging
from functools import wraps

from aiogram.dispatcher.handler import CancelHandler
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def _handler(item):
    return getattr(item, "handler", None)


def _find(registry, name):
    for item in registry:
        fn = _handler(item)
        if getattr(fn, "__name__", "") == name:
            return item
    return None


async def _edit_turn_to_next_only(main, message_id, seat):
    if not message_id or seat is None or not getattr(main, "group_chat_id", None):
        return
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton("⏭ نکست", callback_data=f"next_{seat}"))
    try:
        await main.bot.edit_message_reply_markup(
            chat_id=main.group_chat_id,
            message_id=message_id,
            reply_markup=kb,
        )
    except Exception:
        logging.debug("V3: could not remove challenge button from turn message", exc_info=True)


async def _delete_request_messages(main, target_seat):
    requests = getattr(main, "challenge_requests", {}) or {}
    pending = requests.get(target_seat, {}) or {}
    message_map = getattr(main, "challenge_request_messages", {}) or {}
    for challenger_id in list(pending.keys()):
        message_id = message_map.pop((target_seat, int(challenger_id)), None)
        if message_id:
            try:
                await main.bot.delete_message(main.group_chat_id, message_id)
            except Exception:
                pass
    requests.pop(target_seat, None)


def _name(main, uid):
    try:
        return main.display_name(uid, main.players.get(uid, "❓"))
    except Exception:
        return main.players.get(uid, "❓") if isinstance(getattr(main, "players", None), dict) else "❓"


def install(main):
    dp = main.dp
    registry = getattr(getattr(dp, "callback_query_handlers", None), "handlers", None)
    if registry is None:
        logging.error("V3: callback registry unavailable")
        return

    if not isinstance(getattr(main, "challenge_target_locked", None), set):
        main.challenge_target_locked = set()

    # Reset target locks at the beginning of every new round.
    item = _find(registry, "start_round_clean")
    if item is not None:
        original = _handler(item)
        if not getattr(original, "_v3_round_reset", False):
            @wraps(original)
            async def start_round_v3(callback, _original=original):
                main.challenge_target_locked.clear()
                return await _original(callback)
            start_round_v3._v3_round_reset = True
            item.handler = start_round_v3

    # Challenge request: a target that has already accepted/rejected a request
    # in this turn is permanently locked until the next round.
    item = _find(registry, "challenge_request")
    if item is not None:
        original = _handler(item)
        if not getattr(original, "_v3_challenge_request", False):
            @wraps(original)
            async def challenge_request_v3(callback, _original=original):
                try:
                    target_seat = int(str(callback.data).split("_", 2)[2])
                except Exception:
                    return await _original(callback)
                if target_seat in main.challenge_target_locked:
                    await callback.answer(
                        "⛔ برای این بازیکن در این نوبت چالش دیگری قابل ثبت نیست.",
                        show_alert=True,
                    )
                    raise CancelHandler()
                return await _original(callback)
            challenge_request_v3._v3_challenge_request = True
            item.handler = challenge_request_v3

    # Challenge response: the accept callbacks are handled by the existing
    # authoritative handler. Reject is implemented here because the historical
    # callback format is reject_<challenger>_<target> (three segments), while
    # the old final handler incorrectly required four segments.
    item = _find(registry, "handle_challenge_response")
    if item is not None:
        original = _handler(item)
        if not getattr(original, "_v3_challenge_response", False):
            @wraps(original)
            async def challenge_response_v3(callback, _original=original):
                data = str(getattr(callback, "data", "") or "")
                parts = data.split("_")
                action = parts[0] if parts else ""

                if action == "reject" and len(parts) == 3:
                    try:
                        challenger_id = int(parts[1])
                        target_id = int(parts[2])
                    except ValueError:
                        await callback.answer("⚠️ داده چالش نامعتبر است.", show_alert=True)
                        raise CancelHandler()

                    target_seat = next(
                        (seat for seat, uid in (getattr(main, "player_slots", {}) or {}).items() if uid == target_id),
                        None,
                    )
                    if target_seat is None:
                        await callback.answer("⚠️ بازیکن هدف یافت نشد.", show_alert=True)
                        raise CancelHandler()

                    if callback.from_user.id not in {target_id, getattr(main, "moderator_id", None)}:
                        await callback.answer("❌ فقط صاحب نوبت یا گرداننده می‌تواند تصمیم بگیرد.", show_alert=True)
                        raise CancelHandler()

                    active = getattr(main, "challenge_requests", {}) or {}
                    if challenger_id not in active.get(target_seat, {}):
                        await callback.answer("⚠️ این درخواست دیگر فعال نیست.", show_alert=True)
                        raise CancelHandler()

                    original_turn_message_id = getattr(main, "current_turn_message_id", None)
                    if original_turn_message_id is None:
                        original_turn_message_id = getattr(main, "game_message_id", None)

                    target_name = _name(main, target_id)
                    challenger_name = _name(main, challenger_id)

                    await _delete_request_messages(main, target_seat)
                    main.challenge_target_locked.add(target_seat)

                    try:
                        await main.bot.send_message(
                            main.group_chat_id,
                            f"🚫 {html.escape(str(target_name))} درخواست چالش {html.escape(str(challenger_name))} را رد کرد.",
                            parse_mode="HTML",
                        )
                    except Exception:
                        pass

                    await _edit_turn_to_next_only(main, original_turn_message_id, target_seat)
                    await callback.answer("❌ درخواست رد شد.")
                    raise CancelHandler()

                # Accept-before / accept-after use the authoritative handler.
                if len(parts) < 4:
                    return await _original(callback)

                try:
                    target_id = int(parts[3])
                except ValueError:
                    return await _original(callback)

                target_seat = next(
                    (seat for seat, uid in (getattr(main, "player_slots", {}) or {}).items() if uid == target_id),
                    None,
                )
                original_turn_message_id = getattr(main, "current_turn_message_id", None)
                if original_turn_message_id is None:
                    original_turn_message_id = getattr(main, "game_message_id", None)

                result = await _original(callback)

                if parts[0] == "accept" and target_seat is not None:
                    main.challenge_target_locked.add(target_seat)
                    await _edit_turn_to_next_only(main, original_turn_message_id, target_seat)
                return result
            challenge_response_v3._v3_challenge_response = True
            item.handler = challenge_response_v3

    # Hard security boundary: Next is never a player action in this runtime.
    item = _find(registry, "next_turn")
    if item is not None:
        original = _handler(item)
        if not getattr(original, "_v3_next_guard", False):
            @wraps(original)
            async def next_v3(callback, _original=original):
                user_id = getattr(getattr(callback, "from_user", None), "id", None)
                if user_id != getattr(main, "moderator_id", None):
                    try:
                        admins = await main.bot.get_chat_administrators(main.group_chat_id)
                        is_admin = any(a.user.id == user_id for a in admins)
                    except Exception:
                        is_admin = False
                    if not is_admin:
                        await callback.answer(
                            "⛔ فقط گرداننده یا مدیر گروه می‌تواند نکست بزند.",
                            show_alert=True,
                        )
                        raise CancelHandler()
                return await _original(callback)
            next_v3._v3_next_guard = True
            item.handler = next_v3

    for wanted in ("next_turn", "handle_challenge_response", "challenge_request", "start_round_clean"):
        item = _find(registry, wanted)
        if item is not None:
            registry.insert(0, registry.pop(registry.index(item)))

    main._final_turn_challenge_v3 = True
    logging.info("V3 turn/challenge authority installed")
