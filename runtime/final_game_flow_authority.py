from __future__ import annotations

import asyncio
import html
import logging
import time
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


LEGACY_NAMES = {
    "start_round_handler",
    "handle_start_turn",
    "start_round_clean",
    "next_turn",
    "challenge_request",
    "handle_challenge_response",
    "speaker_auto",
    "speaker_manual",
    "head_set_handler",
}


def _handler(item):
    return getattr(item, "handler", None)


def _front(registry, name):
    for i, item in enumerate(registry):
        if getattr(_handler(item), "__name__", "") == name:
            registry.insert(0, registry.pop(i))
            return


def _remove_names(registry, names):
    registry[:] = [item for item in registry if getattr(_handler(item), "__name__", "") not in names]


def _ensure_challenge_state(main):
    if not isinstance(getattr(main, "challenge_used_by", None), set):
        main.challenge_used_by = set()
    if not isinstance(getattr(main, "challenge_request_messages", None), dict):
        main.challenge_request_messages = {}


def _reset_challenge_state(main):
    _ensure_challenge_state(main)
    main.challenge_used_by.clear()
    main.challenge_request_messages.clear()
    try:
        main.challenge_requests.clear()
    except Exception:
        main.challenge_requests = {}
    try:
        main.pending_challenges.clear()
    except Exception:
        main.pending_challenges = {}
    main.active_challenger_seats = set()
    main.challenge_mode = False
    main.paused_main_player = None
    main.paused_main_duration = None
    main.post_challenge_advance = False


async def _delete_message(bot, chat_id, message_id):
    if not message_id:
        return
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception:
        pass


async def _delete_request_messages(main, target_seat, keep=None):
    _ensure_challenge_state(main)
    chat_id = getattr(main, "group_chat_id", None)
    pending = getattr(main, "challenge_requests", {}).get(target_seat, {}) or {}
    for challenger_id in list(pending.keys()):
        key = (int(target_seat), int(challenger_id))
        message_id = main.challenge_request_messages.pop(key, None)
        if message_id and key != keep:
            await _delete_message(main.bot, chat_id, message_id)
    try:
        main.challenge_requests.pop(target_seat, None)
    except Exception:
        pass


def _player_name(main, uid):
    try:
        return main.display_name(uid, main.players.get(uid, "❓"))
    except Exception:
        return main.players.get(uid, "❓") if isinstance(main.players, dict) else "❓"


def _player_list_text(main):
    lines = ["👥 <b>لیست بازیکنان</b>", ""]
    for seat, uid in sorted((main.player_slots or {}).items()):
        name = _player_name(main, uid)
        lines.append(f"{seat:02d}. <a href='tg://user?id={uid}'>{html.escape(str(name))}</a>")
    if len(lines) == 2:
        lines.append("— بازیکنی ثبت نشده است.")
    return "\n".join(lines)


def _start_round_keyboard():
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton("▶️ شروع دور", callback_data="start_round"))
    return kb


def _round_list_keyboard():
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton("⚔️ وضعیت چالش", callback_data="lv6_challenge_status"))
    return kb


def install(main):
    dp = main.dp
    registry = getattr(getattr(dp, "callback_query_handlers", None), "handlers", None)
    if registry is None:
        logging.error("FINAL game flow authority: callback registry unavailable")
        return

    _ensure_challenge_state(main)
    _remove_names(registry, LEGACY_NAMES)

    async def start_round_clean(callback):
        if callback.from_user.id != main.moderator_id:
            await callback.answer("❌ فقط گرداننده می‌تواند دور را شروع کند.", show_alert=True)
            return
        if not main.player_slots:
            await callback.answer("⚠️ بازیکنی برای شروع دور وجود ندارد.", show_alert=True)
            return
        if not main.turn_order:
            main.turn_order = sorted(main.player_slots.keys())
        main.current_turn_index = 0
        main.round_active = True
        main.game_running = True
        _reset_challenge_state(main)
        try:
            await callback.message.edit_text(
                _player_list_text(main),
                reply_markup=_round_list_keyboard(),
                parse_mode="HTML",
            )
            main.game_message_id = callback.message.message_id
        except Exception:
            msg = await main.bot.send_message(
                main.group_chat_id,
                _player_list_text(main),
                reply_markup=_round_list_keyboard(),
                parse_mode="HTML",
            )
            main.game_message_id = msg.message_id
        await main.start_turn(main.turn_order[0])
        await callback.answer("✅ دور شروع شد")

    start_round_clean._final_flow = True

    async def speaker_auto(callback):
        import random
        if callback.from_user.id != main.moderator_id:
            await callback.answer("❌ فقط گرداننده می‌تواند انتخاب کند.", show_alert=True)
            return
        seats = sorted(main.player_slots.keys())
        if not seats:
            await callback.answer("⚠️ هیچ بازیکنی ثبت نشده.", show_alert=True)
            return
        seat = random.choice(seats)
        idx = seats.index(seat)
        main.current_speaker = seat
        main.current_turn_index = 0
        main.turn_order = seats[idx:] + seats[:idx]
        _reset_challenge_state(main)
        kb = _start_round_keyboard()
        text = f"🎯 سر صحبت انتخاب شد: صندلی {seat}\n\nبرای شروع دور، «▶️ شروع دور» را بزنید."
        try:
            await callback.message.edit_text(text, reply_markup=kb)
            main.game_message_id = callback.message.message_id
        except Exception:
            msg = await main.bot.send_message(main.group_chat_id, text, reply_markup=kb)
            main.game_message_id = msg.message_id
        await callback.answer(f"✅ صندلی {seat} سر صحبت شد.")

    speaker_auto.__name__ = "speaker_auto"

    async def speaker_manual(callback):
        if callback.from_user.id != main.moderator_id:
            await callback.answer("❌ فقط گرداننده می‌تواند انتخاب کند.", show_alert=True)
            return
        if not main.player_slots:
            await callback.answer("⚠️ هیچ بازیکنی ثبت نشده.", show_alert=True)
            return
        kb = InlineKeyboardMarkup(row_width=2)
        for seat, uid in sorted(main.player_slots.items()):
            kb.add(InlineKeyboardButton(f"{seat}. {html.escape(str(_player_name(main, uid)))}", callback_data=f"head_set_{seat}"))
        try:
            await callback.message.edit_text("✋ یکی از بازیکن‌ها را برای سر صحبت انتخاب کنید:", reply_markup=kb)
            main.game_message_id = callback.message.message_id
        except Exception:
            msg = await main.bot.send_message(main.group_chat_id, "✋ یکی از بازیکن‌ها را برای سر صحبت انتخاب کنید:", reply_markup=kb)
            main.game_message_id = msg.message_id
        await callback.answer()

    speaker_manual.__name__ = "speaker_manual"

    async def head_set_handler(callback):
        if callback.from_user.id != main.moderator_id:
            await callback.answer("❌ فقط گرداننده می‌تواند سر صحبت را تعیین کند.", show_alert=True)
            return
        try:
            seat = int(str(callback.data).split("head_set_", 1)[1])
        except Exception:
            await callback.answer("⚠️ صندلی نامعتبر است.", show_alert=True)
            return
        if seat not in main.player_slots:
            await callback.answer("⚠️ این صندلی خالی است.", show_alert=True)
            return
        seats = sorted(main.player_slots.keys())
        idx = seats.index(seat)
        main.current_speaker = seat
        main.current_turn_index = 0
        main.turn_order = seats[idx:] + seats[:idx]
        _reset_challenge_state(main)
        text = f"🎯 سر صحبت انتخاب شد: صندلی {seat} - {html.escape(str(_player_name(main, main.player_slots[seat])))}\n\nبرای شروع دور، «▶️ شروع دور» را بزنید."
        try:
            await callback.message.edit_text(text, reply_markup=_start_round_keyboard(), parse_mode="HTML")
            main.game_message_id = callback.message.message_id
        except Exception:
            msg = await main.bot.send_message(main.group_chat_id, text, reply_markup=_start_round_keyboard(), parse_mode="HTML")
            main.game_message_id = msg.message_id
        await callback.answer("✅ سر صحبت انتخاب شد.")

    async def challenge_request(callback):
        _ensure_challenge_state(main)
        if not getattr(main, "challenge_active", True):
            await callback.answer("⚔️ چالش خاموش است.", show_alert=True)
            return
        challenger_id = callback.from_user.id
        try:
            target_seat = int(str(callback.data).split("_", 2)[2])
        except Exception:
            await callback.answer("⚠️ داده چالش نامعتبر است.", show_alert=True)
            return
        target_id = (main.player_slots or {}).get(target_seat)
        if not target_id:
            await callback.answer("⚠️ بازیکن یافت نشد.", show_alert=True)
            return
        if challenger_id == target_id:
            await callback.answer("❌ نمی‌توانی خودت را به چالش بکشی.", show_alert=True)
            return
        if challenger_id in main.challenge_used_by:
            await callback.answer("❌ شما در این دور قبلاً یک چالش ثبت کرده‌اید و دیگر نمی‌توانید چالش دیگری بدهید.", show_alert=True)
            return
        main.challenge_used_by.add(challenger_id)
        main.challenge_requests.setdefault(target_seat, {})[challenger_id] = "pending"
        challenger_name = _player_name(main, challenger_id)
        target_name = _player_name(main, target_id)
        kb = InlineKeyboardMarkup(row_width=2)
        kb.add(
            InlineKeyboardButton("✅ قبول (قبل)", callback_data=f"accept_before_{challenger_id}_{target_id}"),
            InlineKeyboardButton("✅ قبول (بعد)", callback_data=f"accept_after_{challenger_id}_{target_id}"),
            InlineKeyboardButton("❌ رد", callback_data=f"reject_{challenger_id}_{target_id}"),
        )
        msg = await main.bot.send_message(
            main.group_chat_id,
            f"⚔ {html.escape(str(challenger_name))} از {html.escape(str(target_name))} درخواست چالش کرد.",
            reply_markup=kb,
            parse_mode="HTML",
        )
        main.challenge_request_messages[(target_seat, challenger_id)] = msg.message_id
        await callback.answer("⏳ درخواست چالش ارسال شد.", show_alert=True)

    async def handle_challenge_response(callback):
        _ensure_challenge_state(main)
        parts = str(callback.data or "").split("_")
        if len(parts) < 4:
            await callback.answer("⚠️ داده چالش نامعتبر است.", show_alert=True)
            return
        action = parts[0]
        timing = parts[1] if action == "accept" else None
        try:
            challenger_id = int(parts[2])
            target_id = int(parts[3])
        except ValueError:
            await callback.answer("⚠️ داده چالش نامعتبر است.", show_alert=True)
            return
        target_seat = next((s for s, uid in main.player_slots.items() if uid == target_id), None)
        challenger_seat = next((s for s, uid in main.player_slots.items() if uid == challenger_id), None)
        if target_seat is None or challenger_seat is None:
            await callback.answer("⚠️ صندلی نامعتبر است.", show_alert=True)
            return
        if callback.from_user.id not in {target_id, main.moderator_id}:
            await callback.answer("❌ فقط صاحب نوبت یا گرداننده می‌تواند تصمیم بگیرد.", show_alert=True)
            return
        if challenger_id not in getattr(main, "challenge_requests", {}).get(target_seat, {}):
            await callback.answer("⚠️ این درخواست دیگر فعال نیست.", show_alert=True)
            return

        target_name = _player_name(main, target_id)
        challenger_name = _player_name(main, challenger_id)
        request_key = (target_seat, challenger_id)
        request_message_id = main.challenge_request_messages.pop(request_key, None)

        # Close/remove this request immediately, then invalidate every other
        # pending request for the same target so stale buttons cannot be used.
        await _delete_message(main.bot, main.group_chat_id, request_message_id)
        await _delete_request_messages(main, target_seat)

        if action == "reject":
            await main.bot.send_message(main.group_chat_id, f"🚫 {html.escape(str(target_name))} درخواست چالش {html.escape(str(challenger_name))} را رد کرد.", parse_mode="HTML")
            await callback.answer("❌ درخواست رد شد.")
            return

        if action != "accept" or timing not in {"before", "after"}:
            await callback.answer("⚠️ نوع چالش نامعتبر است.", show_alert=True)
            return

        if timing == "after":
            main.pending_challenges[target_seat] = challenger_id
            await main.bot.send_message(main.group_chat_id, f"⚔ {html.escape(str(target_name))} درخواست چالش {html.escape(str(challenger_name))} را قبول کرد (بعد از صحبت).", parse_mode="HTML")
            await callback.answer("✅ چالش بعد ثبت شد.")
            return

        # before: the challenger speaks now, then the original target resumes.
        main.paused_main_player = target_seat
        main.paused_main_duration = getattr(main, "DEFAULT_TURN_DURATION", 120)
        main.post_challenge_advance = False
        main.challenge_mode = True
        if getattr(main, "turn_timer_task", None) and not main.turn_timer_task.done():
            main.turn_timer_task.cancel()
        await main.bot.send_message(main.group_chat_id, f"⚔ {html.escape(str(target_name))} درخواست چالش {html.escape(str(challenger_name))} را قبول کرد (قبل از صحبت).", parse_mode="HTML")
        await main.start_turn(challenger_seat, duration=60, is_challenge=True)
        await callback.answer("✅ چالش قبل اجرا شد.")

    async def next_turn(callback):
        import time as _time
        now = _time.time()
        if callback.from_user.id != main.moderator_id and not getattr(main, "next_by_players_enabled", True):
            await callback.answer("⛔ نکست برای بازیکنان غیرفعال شده.", show_alert=True)
            return
        if callback.from_user.id == main.moderator_id and not getattr(main, "next_by_moderator_enabled", True):
            await callback.answer("⛔ نکست برای گرداننده غیرفعال شده.", show_alert=True)
            return
        if getattr(main, "addons", None) and main.addons.settings.get("next", {}).get("anti_spam", True):
            if now - getattr(main, "last_next_time", 0) < 3:
                await callback.answer("⏳ لطفاً کمی صبر کنید...", show_alert=True)
                return
            main.last_next_time = now
        try:
            seat = int(str(callback.data).split("_", 1)[1])
        except Exception:
            await callback.answer("⚠️ داده نوبت نامعتبر است.", show_alert=True)
            return
        player_uid = (main.player_slots or {}).get(seat)
        if callback.from_user.id not in {main.moderator_id, player_uid}:
            await callback.answer("❌ فقط بازیکن مربوطه یا گرداننده می‌تواند نوبت را رد کند.", show_alert=True)
            return
        if getattr(main, "turn_timer_task", None) and not main.turn_timer_task.done():
            main.turn_timer_task.cancel()

        # A challenge turn has finished.
        if getattr(main, "challenge_mode", False):
            paused = getattr(main, "paused_main_player", None)
            advance = bool(getattr(main, "post_challenge_advance", False))
            main.challenge_mode = False
            main.paused_main_player = None
            main.paused_main_duration = None
            main.post_challenge_advance = False
            if paused is not None and not advance:
                await main.start_turn(paused)
                await callback.answer("➡️ بازگشت به نوبت اصلی")
                return
            if advance:
                main.current_turn_index += 1

        else:
            # The current target's main turn can trigger an accepted "after" challenge.
            pending = getattr(main, "pending_challenges", {})
            if seat in pending:
                challenger_id = pending.pop(seat)
                challenger_seat = next((s for s, uid in main.player_slots.items() if uid == challenger_id), None)
                if challenger_seat is not None:
                    main.paused_main_player = seat
                    main.paused_main_duration = getattr(main, "DEFAULT_TURN_DURATION", 120)
                    main.post_challenge_advance = True
                    main.challenge_mode = True
                    await main.start_turn(challenger_seat, duration=60, is_challenge=True)
                    await callback.answer("⚔️ چالش بعد اجرا شد.")
                    return
            main.current_turn_index += 1

        if main.current_turn_index >= len(main.turn_order):
            kb = InlineKeyboardMarkup(row_width=1)
            kb.add(InlineKeyboardButton("🌙 شروع فاز شب", callback_data="start_night"))
            try:
                await callback.message.edit_text("✅ همه بازیکنا صحبت کردن. فاز روز تموم شد.", reply_markup=kb)
                main.game_message_id = callback.message.message_id
            except Exception:
                msg = await main.bot.send_message(main.group_chat_id, "✅ همه بازیکنا صحبت کردن. فاز روز تموم شد.", reply_markup=kb)
                main.game_message_id = msg.message_id
        else:
            await _delete_message(main.bot, callback.message.chat.id, callback.message.message_id)
            await main.start_turn(main.turn_order[main.current_turn_index])
        await callback.answer()

    # Register in a deliberate order. All names match the final runtime guard.
    dp.register_callback_query_handler(start_round_clean, lambda c: c.data == "start_round")
    dp.register_callback_query_handler(speaker_auto, lambda c: c.data == "speaker_auto")
    dp.register_callback_query_handler(speaker_manual, lambda c: c.data == "speaker_manual")
    dp.register_callback_query_handler(head_set_handler, lambda c: str(c.data or "").startswith("head_set_"))
    dp.register_callback_query_handler(challenge_request, lambda c: str(c.data or "").startswith("challenge_request_"))
    dp.register_callback_query_handler(handle_challenge_response, lambda c: str(c.data or "").startswith(("accept_before_", "accept_after_", "reject_")))
    dp.register_callback_query_handler(next_turn, lambda c: str(c.data or "").startswith("next_"))

    registry = getattr(dp.callback_query_handlers, "handlers", [])
    for name in reversed(("next_turn", "handle_challenge_response", "challenge_request", "head_set_handler", "speaker_manual", "speaker_auto", "start_round_clean")):
        _front(registry, name)

    logging.info("FINAL game flow authority installed: challenge lock + round UI + next-turn lifecycle")
