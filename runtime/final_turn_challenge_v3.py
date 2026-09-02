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


async def _delete_message(main, message_id):
    if not message_id or not getattr(main, "group_chat_id", None):
        return
    try:
        await main.bot.delete_message(main.group_chat_id, message_id)
    except Exception:
        pass


async def _replace_turn_keyboard_with_next(main, message_id, seat):
    if not message_id or seat is None or not getattr(main, "group_chat_id", None):
        return False
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton("⏭ نکست", callback_data=f"next_{seat}"))
    try:
        await main.bot.edit_message_reply_markup(
            chat_id=main.group_chat_id,
            message_id=message_id,
            reply_markup=kb,
        )
        return True
    except Exception:
        logging.debug("V3: could not replace turn keyboard", exc_info=True)
        return False


async def _remove_turn_keyboard(main, message_id):
    if not message_id or not getattr(main, "group_chat_id", None):
        return False
    try:
        await main.bot.edit_message_reply_markup(
            chat_id=main.group_chat_id,
            message_id=message_id,
            reply_markup=None,
        )
        return True
    except Exception:
        return False


async def _delete_request_messages(main, target_seat):
    requests = getattr(main, "challenge_requests", {}) or {}
    pending = requests.get(target_seat, {}) or {}
    message_map = getattr(main, "challenge_request_messages", {}) or {}
    for challenger_id in list(pending.keys()):
        key = (int(target_seat), int(challenger_id))
        message_id = message_map.pop(key, None)
        if message_id:
            await _delete_message(main, message_id)
    requests.pop(target_seat, None)


def _name(main, uid):
    try:
        value = main.display_name(uid, main.players.get(uid, None))
        if value and str(value).strip() not in {"بازیکن", "❓", "None"}:
            return str(value)
    except Exception:
        pass
    try:
        value = main.players.get(uid)
        if value and str(value).strip() not in {"بازیکن", "❓", "None"}:
            return str(value)
    except Exception:
        pass
    return f"بازیکن {uid}"


async def _hydrate_name(main, uid):
    """Refresh the visible player name from Telegram without overwriting nicknames."""
    try:
        member = await main.bot.get_chat_member(main.group_chat_id, uid)
        full_name = getattr(getattr(member, "user", None), "full_name", None)
        if full_name and isinstance(getattr(main, "players", None), dict):
            # Only replace placeholders here; nickname resolution remains in
            # display_name(). V4 performs an unconditional refresh as well.
            current = main.players.get(uid)
            if not current or str(current).strip() in {"بازیکن", "❓", "None"}:
                main.players[uid] = full_name
            return full_name
    except Exception:
        pass
    return None


def _turn_text_fix(text, visible_name):
    """Replace only the generic player label in a freshly-created turn message."""
    if not text or not visible_name:
        return text
    value = str(text)
    # Legacy start_turn uses the literal generic label in some paths. Replace
    # only standalone labels; do not touch user names containing this word.
    for old in ("<b>بازیکن</b>", "بازیکن:", "بازیکن —", "بازیکن -"):
        if old in value:
            value = value.replace(old, old.replace("بازیکن", html.escape(str(visible_name))), 1)
    # The simplest legacy form is a line containing just "بازیکن".
    value = value.replace("\nبازیکن\n", f"\n{html.escape(str(visible_name))}\n", 1)
    return value


async def _capture_start_turn_message(main, original, seat, duration, is_challenge):
    """Run legacy start_turn while reliably capturing the actual turn message id."""
    original_send = main.bot.send_message
    captured = []

    async def send_message_capture(*args, **kwargs):
        msg = await original_send(*args, **kwargs)
        try:
            chat_id = kwargs.get("chat_id", args[0] if args else None)
            if chat_id == main.group_chat_id and _is_turn_keyboard(msg):
                captured.append(msg)
        except Exception:
            pass
        return msg

    main.bot.send_message = send_message_capture
    try:
        result = await original(seat, duration=duration, is_challenge=is_challenge)
    finally:
        main.bot.send_message = original_send

    if captured:
        msg = captured[-1]
        main.current_turn_message_id = msg.message_id
        uid = (getattr(main, "player_slots", {}) or {}).get(seat)
        if uid:
            visible_name = _name(main, uid)
            fixed = _turn_text_fix(getattr(msg, "text", None), visible_name)
            if fixed and fixed != getattr(msg, "text", None):
                try:
                    await main.bot.edit_message_text(
                        chat_id=main.group_chat_id,
                        message_id=msg.message_id,
                        text=fixed,
                        parse_mode="HTML",
                        reply_markup=getattr(msg, "reply_markup", None),
                    )
                except Exception:
                    logging.debug("V3: could not repair generic turn name", exc_info=True)
    return result


def _is_turn_keyboard(message):
    markup = getattr(message, "reply_markup", None)
    rows = getattr(markup, "inline_keyboard", None) or []
    data = [str(getattr(btn, "callback_data", "") or "") for row in rows for btn in row]
    return any(x.startswith("next_") for x in data) or any(x.startswith("challenge_request_") for x in data)


def install(main):
    dp = main.dp
    registry = getattr(getattr(dp, "callback_query_handlers", None), "handlers", None)
    if registry is None:
        logging.error("V3: callback registry unavailable")
        return

    if not isinstance(getattr(main, "challenge_target_locked", None), set):
        main.challenge_target_locked = set()
    if not isinstance(getattr(main, "challenge_request_messages", None), dict):
        main.challenge_request_messages = {}

    original_start_turn = getattr(main, "start_turn", None)
    if original_start_turn is not None and not getattr(original_start_turn, "_v3_capture", False):
        @wraps(original_start_turn)
        async def start_turn_v3(seat, duration=120, is_challenge=False):
            uid = (getattr(main, "player_slots", {}) or {}).get(seat)
            if uid:
                await _hydrate_name(main, uid)
            return await _capture_start_turn_message(main, original_start_turn, seat, duration, is_challenge)
        start_turn_v3._v3_capture = True
        main.start_turn = start_turn_v3

    item = _find(registry, "start_round_clean")
    if item is not None:
        original = _handler(item)
        if not getattr(original, "_v3_round_reset", False):
            @wraps(original)
            async def start_round_v3(callback, _original=original):
                main.challenge_target_locked.clear()
                main.challenge_request_messages.clear()
                return await _original(callback)
            start_round_v3._v3_round_reset = True
            item.handler = start_round_v3

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
                    await callback.answer("⛔ برای این بازیکن دیگر چالش قابل ثبت نیست.", show_alert=True)
                    raise CancelHandler()
                return await _original(callback)
            challenge_request_v3._v3_challenge_request = True
            item.handler = challenge_request_v3

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
                        challenger_id = int(parts[1]); target_id = int(parts[2])
                    except ValueError:
                        await callback.answer("⚠️ داده چالش نامعتبر است.", show_alert=True)
                        raise CancelHandler()
                    target_seat = next((s for s, uid in (getattr(main, "player_slots", {}) or {}).items() if uid == target_id), None)
                    if target_seat is None:
                        await callback.answer("⚠️ بازیکن هدف یافت نشد.", show_alert=True)
                        raise CancelHandler()
                    if callback.from_user.id not in {target_id, getattr(main, "moderator_id", None)}:
                        await callback.answer("❌ فقط صاحب نوبت یا گرداننده می‌تواند تصمیم بگیرد.", show_alert=True)
                        raise CancelHandler()
                    if challenger_id not in getattr(main, "challenge_requests", {}).get(target_seat, {}):
                        await callback.answer("⚠️ این درخواست دیگر فعال نیست.", show_alert=True)
                        raise CancelHandler()
                    target_name = _name(main, target_id); challenger_name = _name(main, challenger_id)
                    turn_id = getattr(main, "current_turn_message_id", None)
                    await _delete_request_messages(main, target_seat)
                    main.challenge_target_locked.add(target_seat)
                    await _replace_turn_keyboard_with_next(main, turn_id, target_seat)
                    try:
                        await main.bot.send_message(main.group_chat_id, f"🚫 {html.escape(target_name)} درخواست چالش {html.escape(challenger_name)} را رد کرد.", parse_mode="HTML")
                    except Exception:
                        pass
                    await callback.answer("❌ درخواست رد شد.")
                    raise CancelHandler()

                if len(parts) < 4:
                    return await _original(callback)
                try:
                    target_id = int(parts[3])
                except ValueError:
                    return await _original(callback)
                target_seat = next((s for s, uid in (getattr(main, "player_slots", {}) or {}).items() if uid == target_id), None)
                turn_id = getattr(main, "current_turn_message_id", None)
                result = await _original(callback)
                if parts[0] == "accept" and target_seat is not None:
                    main.challenge_target_locked.add(target_seat)
                    await _delete_request_messages(main, target_seat)
                    timing = parts[1] if len(parts) > 1 else ""
                    if timing == "after":
                        await _replace_turn_keyboard_with_next(main, turn_id, target_seat)
                    else:
                        await _delete_message(main, turn_id)
                return result
            challenge_response_v3._v3_challenge_response = True
            item.handler = challenge_response_v3

    item = _find(registry, "next_turn")
    if item is not None:
        original = _handler(item)
        if not getattr(original, "_v3_next_guard", False):
            @wraps(original)
            async def next_v3(callback, _original=original):
                # V4 performs the definitive actor check. V3 intentionally does
                # not duplicate an admin check here, otherwise a normal player
                # would be rejected after V4 authorizes the active turn owner.
                try:
                    clicked_seat = int(str(callback.data).split("_", 1)[1])
                except Exception:
                    await callback.answer("⚠️ نوبت نامعتبر است.", show_alert=True)
                    raise CancelHandler()

                expected_seat = None
                try:
                    expected_seat = main.turn_order[main.current_turn_index]
                except Exception:
                    pass
                if expected_seat is not None and not getattr(main, "challenge_mode", False) and clicked_seat != expected_seat:
                    await callback.answer("⚠️ این نوبت دیگر فعال نیست.", show_alert=True)
                    raise CancelHandler()

                old_turn_id = getattr(main, "current_turn_message_id", None) or getattr(callback.message, "message_id", None)
                await _delete_message(main, old_turn_id)
                main.current_turn_message_id = None
                return await _original(callback)
            next_v3._v3_next_guard = True
            item.handler = next_v3

    for wanted in ("next_turn", "handle_challenge_response", "challenge_request", "start_round_clean"):
        item = _find(registry, wanted)
        if item is not None:
            registry.insert(0, registry.pop(registry.index(item)))

    main._final_turn_challenge_v3 = True
    logging.info("V3 turn/challenge authority installed: lifecycle + names + challenge UI + next guard")
