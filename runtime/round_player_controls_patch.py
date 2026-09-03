"""Player-list, silence and extra-turn controls for the private game menu.

Silence/extra-turn flags are intentionally scoped to the current in-memory
match. They are management controls, not user-facing permissions. A silence
flag skips that player's next round; an extra-turn flag schedules one extra
non-challenge turn after the normal round finishes.
"""
from __future__ import annotations

import html
import logging
from functools import wraps

from aiogram.dispatcher.handler import CancelHandler
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def _players(main):
    slots = getattr(main, "player_slots", {}) or {}
    names = getattr(main, "players", {}) or {}
    result = []
    for raw_seat, uid in slots.items():
        try:
            seat = int(raw_seat)
            uid = int(uid)
        except (TypeError, ValueError):
            continue
        name = names.get(uid) or f"بازیکن {seat}"
        result.append((seat, uid, str(name)))
    return sorted(result, key=lambda x: x[0])


def _ensure_state(main):
    if not isinstance(getattr(main, "_gm_muted_next_round", None), set):
        main._gm_muted_next_round = set()
    if not isinstance(getattr(main, "_gm_extra_next_round", None), set):
        main._gm_extra_next_round = set()
    if not isinstance(getattr(main, "_gm_extra_seats", None), set):
        main._gm_extra_seats = set()
    if not isinstance(getattr(main, "_gm_base_turn_order", None), list):
        main._gm_base_turn_order = []
    if not hasattr(main, "_gm_extra_phase"):
        main._gm_extra_phase = False
    if not hasattr(main, "_gm_extra_turn_active"):
        main._gm_extra_turn_active = False


def _menu(main):
    _ensure_state(main)
    kb = InlineKeyboardMarkup(row_width=1)
    for seat, uid, name in _players(main):
        flags = []
        if seat in main._gm_muted_next_round:
            flags.append("🔇")
        if seat in main._gm_extra_next_round:
            flags.append("➕")
        suffix = " " + " ".join(flags) if flags else ""
        kb.add(InlineKeyboardButton(
            f"💺 {seat} — {html.escape(name)}{suffix}",
            callback_data=f"gm:noop:{seat}",
        ))
    kb.add(InlineKeyboardButton("⬅️ مدیریت بازی", callback_data="manage_game"))
    return kb


def _selection_menu(main, mode):
    _ensure_state(main)
    kb = InlineKeyboardMarkup(row_width=1)
    active = main._gm_muted_next_round if mode == "mute" else main._gm_extra_next_round
    icon = "🔇" if mode == "mute" else "➕"
    title = "سکوت" if mode == "mute" else "ترن اضافه"
    for seat, uid, name in _players(main):
        mark = " ✅" if seat in active else ""
        kb.add(InlineKeyboardButton(
            f"{icon} صندلی {seat} — {html.escape(name)}{mark}",
            callback_data=f"gm:{mode}:{seat}",
        ))
    kb.add(InlineKeyboardButton("⬅️ مدیریت بازی", callback_data="manage_game"))
    return kb, title


def _handler(item):
    return getattr(item, "handler", None)


def _active_seat(main):
    if getattr(main, "challenge_mode", False):
        active = list(getattr(main, "active_challenger_seats", set()) or set())
        return active[0] if len(active) == 1 else None
    try:
        return main.turn_order[main.current_turn_index]
    except Exception:
        return None


async def _delete_message(main, message_id):
    if not message_id or not getattr(main, "group_chat_id", None):
        return
    try:
        await main.bot.delete_message(main.group_chat_id, message_id)
    except Exception:
        pass


async def _disable_challenge_keyboard(main, seat):
    message_id = getattr(main, "current_turn_message_id", None)
    gid = getattr(main, "group_chat_id", None)
    if not message_id or not gid or seat is None:
        return
    kb = InlineKeyboardMarkup(row_width=1).add(
        InlineKeyboardButton("⏭ نکست", callback_data=f"next_{seat}")
    )
    try:
        await main.bot.edit_message_reply_markup(gid, message_id, reply_markup=kb)
    except Exception:
        logging.debug("GM controls: cannot remove challenge buttons", exc_info=True)


def install(main):
    _ensure_state(main)
    dp = main.dp

    async def players_menu(callback):
        if not await _can_manage(main, callback.from_user.id):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
            return
        rows = _players(main)
        if not rows:
            body = "👥 <b>لیست بازیکنان</b>\n\nدر حال حاضر بازیکنی در بازی ثبت نشده است."
        else:
            body = "👥 <b>لیست بازیکنان</b>\n\n" + "\n".join(
                f"💺 <b>{seat}</b> — {html.escape(name)}" for seat, _, name in rows
            )
            body += f"\n\n👥 تعداد بازیکنان: <b>{len(rows)}</b>"
        kb = InlineKeyboardMarkup(row_width=1).add(
            InlineKeyboardButton("⬅️ مدیریت بازی", callback_data="manage_game")
        )
        await callback.message.edit_text(body, reply_markup=kb, parse_mode="HTML")
        await callback.answer()

    async def select_mode(callback, mode):
        if not await _can_manage(main, callback.from_user.id):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
            return
        if not getattr(main, "game_running", False):
            await callback.answer("⚠️ این گزینه فقط هنگام اجرای بازی قابل استفاده است.", show_alert=True)
            return
        kb, title = _selection_menu(main, mode)
        body = (
            f"{'🔇' if mode == 'mute' else '➕'} <b>{title} بازیکن</b>\n\n"
            "بازیکن موردنظر را انتخاب کنید."
        )
        if mode == "mute":
            body += "\n🔇 این انتخاب برای <b>دور بعد</b> اعمال می‌شود و بازیکن آن دور ترن عادی ندارد."
        else:
            body += "\n➕ این انتخاب بعد از پایان دور جاری، یک ترن اضافه بدون چالش ایجاد می‌کند."
        await callback.message.edit_text(body, reply_markup=kb, parse_mode="HTML")
        await callback.answer()

    async def toggle_player(callback, mode):
        if not await _can_manage(main, callback.from_user.id):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
            return
        try:
            seat = int(str(callback.data).rsplit(":", 1)[1])
        except Exception:
            await callback.answer("⚠️ بازیکن نامعتبر است.", show_alert=True)
            return
        valid = {s for s, _, _ in _players(main)}
        if seat not in valid:
            await callback.answer("⚠️ این بازیکن دیگر در بازی نیست.", show_alert=True)
            return
        active = main._gm_muted_next_round if mode == "mute" else main._gm_extra_next_round
        if seat in active:
            active.remove(seat)
            msg = "لغو شد"
        else:
            active.add(seat)
            msg = "فعال شد"
        kb, title = _selection_menu(main, mode)
        await callback.message.edit_reply_markup(reply_markup=kb)
        await callback.answer(f"{title} برای صندلی {seat} {msg}.")

    async def noop(callback):
        await callback.answer()

    async def _can_manage_local(uid):
        return await _can_manage(main, uid)

    async def challenge_block(callback):
        if getattr(main, "_gm_extra_turn_active", False):
            await callback.answer("⛔ ترن اضافه امکان چالش ندارد.", show_alert=True)
            raise CancelHandler()

    async def custom_next(callback):
        if getattr(callback.message, "chat", None) is not None and callback.message.chat.type == "private":
            await callback.answer("این عملیات فقط در جریان بازی و توسط صاحب نوبت/گرداننده انجام می‌شود.", show_alert=True)
            raise CancelHandler()

        uid = getattr(getattr(callback, "from_user", None), "id", None)
        active_seat = _active_seat(main)
        moderator = getattr(main, "moderator_id", None)
        owner = (getattr(main, "player_slots", {}) or {}).get(active_seat)
        if uid != moderator and uid != owner:
            await callback.answer("⛔ فقط صاحب نوبت یا گرداننده می‌تواند نکست بزند.", show_alert=True)
            raise CancelHandler()
        try:
            clicked = int(str(callback.data).split("_", 1)[1])
        except Exception:
            await callback.answer("⚠️ نوبت نامعتبر است.", show_alert=True)
            raise CancelHandler()
        if active_seat is None or clicked != active_seat:
            await callback.answer("⚠️ این نوبت دیگر فعال نیست.", show_alert=True)
            raise CancelHandler()

        core = getattr(main, "next_turn", None)
        if core is None:
            await callback.answer("⚠️ موتور نوبت در دسترس نیست.", show_alert=True)
            raise CancelHandler()

        _ensure_state(main)
        order = list(getattr(main, "turn_order", []) or [])
        try:
            idx = int(main.current_turn_index)
        except Exception:
            idx = -1

        if not main._gm_base_turn_order or not main._gm_extra_phase:
            if not main._gm_base_turn_order and order:
                main._gm_base_turn_order = list(order)

        # The normal round is ending. Append scheduled extra turns before
        # rebuilding the next normal round. This keeps the legacy turn engine
        # intact while giving extra turns a deterministic place in the order.
        if order and idx == len(order) - 1 and not main._gm_extra_phase:
            base = list(main._gm_base_turn_order or order)
            muted = set(main._gm_muted_next_round)
            extras = [
                seat for seat in base
                if seat in main._gm_extra_next_round and seat not in muted
            ]
            if extras:
                main.turn_order = base + extras
                main._gm_extra_seats = set(extras)
                main._gm_extra_phase = True
                main._gm_base_turn_order = base
            else:
                next_order = [seat for seat in base if seat not in muted]
                main._gm_muted_next_round.clear()
                main._gm_extra_next_round.clear()
                main._gm_extra_seats.clear()
                main._gm_base_turn_order = list(next_order)
                main.turn_order = next_order
                main.current_turn_index = -1

        elif order and idx == len(order) - 1 and main._gm_extra_phase:
            # Extra phase finished: consume the flags and start the next
            # normal round, skipping players silenced for that round.
            base = list(main._gm_base_turn_order or order)
            muted = set(main._gm_muted_next_round)
            next_order = [seat for seat in base if seat not in muted]
            main._gm_muted_next_round.clear()
            main._gm_extra_next_round.clear()
            main._gm_extra_seats.clear()
            main._gm_extra_phase = False
            main.turn_order = next_order
            main._gm_base_turn_order = list(next_order)
            main.current_turn_index = -1

        old_id = getattr(main, "current_turn_message_id", None) or getattr(callback.message, "message_id", None)
        await _delete_message(main, old_id)
        main.current_turn_message_id = None
        return await core(callback)

    # Wrap start_turn so an extra turn is explicitly marked and its challenge
    # UI is removed after the legacy engine renders the turn message.
    start = getattr(main, "start_turn", None)
    if start is not None and not getattr(start, "_gm_round_controls", False):
        @wraps(start)
        async def start_turn_controls(seat, duration=120, is_challenge=False):
            _ensure_state(main)
            main._gm_extra_turn_active = bool(
                not is_challenge and seat in getattr(main, "_gm_extra_seats", set())
            )
            result = await start(seat, duration=duration, is_challenge=is_challenge)
            if main._gm_extra_turn_active:
                await _disable_challenge_keyboard(main, seat)
            return result
        start_turn_controls._gm_round_controls = True
        main.start_turn = start_turn_controls

    # Replace all previous Next handlers with this terminal handler.
    registry = getattr(dp.callback_query_handlers, "handlers", [])
    registry[:] = [
        item for item in registry
        if getattr(_handler(item), "__name__", "") != "next_turn"
    ]
    custom_next.__name__ = "next_turn"
    custom_next._gm_next_authority = True
    dp.register_callback_query_handler(
        custom_next,
        lambda c: str(getattr(c, "data", "") or "").startswith("next_"),
        state="*",
    )

    dp.register_callback_query_handler(players_menu, lambda c: c.data == "gm:players", state="*")
    dp.register_callback_query_handler(lambda c: select_mode(c, "mute"), lambda c: c.data == "gm:mute", state="*")
    dp.register_callback_query_handler(lambda c: select_mode(c, "extra"), lambda c: c.data == "gm:extra", state="*")
    dp.register_callback_query_handler(lambda c: toggle_player(c, "mute"), lambda c: str(c.data or "").startswith("gm:mute:"), state="*")
    dp.register_callback_query_handler(lambda c: toggle_player(c, "extra"), lambda c: str(c.data or "").startswith("gm:extra:"), state="*")
    dp.register_callback_query_handler(noop, lambda c: str(c.data or "").startswith("gm:noop:"), state="*")
    dp.register_callback_query_handler(challenge_block, lambda c: str(c.data or "").startswith("challenge_request_"), state="*")

    # Put the management controls and terminal Next before legacy duplicates.
    registry = getattr(dp.callback_query_handlers, "handlers", [])
    for name in ("next_turn", "players_menu", "noop"):
        for i, item in enumerate(registry):
            if getattr(_handler(item), "__name__", "") == name:
                registry.insert(0, registry.pop(i))
                break
    logging.info("Game management controls installed: player list, mute-next-round, extra-turn")
    return True


async def _can_manage(main, uid):
    moderator = getattr(main, "moderator_id", None)
    if uid == moderator:
        return True
    gid = None
    for attr in ("group_chat_id", "ALLOWED_GROUP_ID", "GROUP_ID", "group_id"):
        value = getattr(main, attr, None)
        if value:
            try:
                gid = int(value)
                break
            except (TypeError, ValueError):
                pass
    if not gid:
        return False
    try:
        admins = await main.bot.get_chat_administrators(gid)
        return any(a.user.id == uid for a in admins)
    except Exception:
        return False
