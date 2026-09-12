"""Serverless-safe voting transition and voting-rules compatibility layer."""
from __future__ import annotations

import html
import time

from aiogram.dispatcher.handler import CancelHandler
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from runtime import voting_runtime


async def _durable_start_wait(main):
    v = voting_runtime._v(main)
    deadline = time.time() + int(v["wait_seconds"])
    v.update(
        phase="waiting",
        started_at=time.time(),
        deadline=deadline,
        target_index=0,
        votes={},
    )
    voting_runtime._put(main, v)

    blocked = voting_runtime._active_rights(v)
    names = [
        voting_runtime._row_name(main, row)
        for row in voting_runtime._players(main)
        if int(row["player_id"]) in blocked
    ]
    blocked_text = "\n".join(
        f"• {html.escape(name)}" for name in names
    ) if names else "• هیچ‌کس"

    await main.bot.send_message(
        voting_runtime._gid(main),
        f"🗳 <b>رای‌گیری پس از {int(v['wait_seconds'])} ثانیه شروع می‌شود.</b>\n"
        f"برای رای به هر بازیکن {int(v['vote_seconds'])} ثانیه فرصت دارید.\n\n"
        f"🚫 <b>بازیکنانی که حق رای ندارند:</b>\n{blocked_text}",
        parse_mode="HTML",
    )
    main._voting_task = None


async def _resolve_name(main, uid, seat=None):
    """Resolve a real Telegram/player name; use seat only as last fallback."""
    value = voting_runtime._name(main, uid, seat)
    if value and not str(value).startswith("بازیکن "):
        return str(value)
    gid = voting_runtime._gid(main)
    if gid:
        try:
            member = await main.bot.get_chat_member(gid, int(uid))
            user = getattr(member, "user", None)
            name = getattr(user, "full_name", None) or getattr(user, "first_name", None)
            if name:
                return str(name)
        except Exception:
            pass
    return str(value or f"بازیکن {int(seat or 0)}")


async def _start_target(main):
    """Start one candidate vote with a real display name."""
    v = voting_runtime._v(main)
    targets = [int(x) for x in (v.get("targets") or [])]
    idx = int(v.get("target_index") or 0)
    if idx >= len(targets):
        return await voting_runtime._finish_round(main)

    target = int(targets[idx])
    rows = {int(x["player_id"]): x for x in voting_runtime._players(main)}
    name = await _resolve_name(main, target, rows.get(target, {}).get("seat"))
    now = time.time()
    deadline = now + int(v["vote_seconds"])
    v["phase"], v["started_at"], v["deadline"] = "voting", now, deadline
    v.setdefault("votes", {}).setdefault(str(target), [])
    voting_runtime._put(main, v)

    markup = None
    if v.get("mode") == voting_runtime.AUTO:
        markup = InlineKeyboardMarkup(row_width=1).add(
            InlineKeyboardButton("🗳 رای می‌دهم", callback_data="vote:cast")
        )

    await main.bot.send_message(
        voting_runtime._gid(main),
        f"🗳 <b>رای برای {html.escape(name)}</b>\n\n"
        f"⏱ {int(v['vote_seconds'])} ثانیه فرصت دارید.",
        parse_mode="HTML",
        reply_markup=markup,
    )
    main._voting_task = None


async def _finish_round(main):
    """Finish a round; round two contains only candidates who reached defense."""
    v = voting_runtime._v(main)
    round_no = int(v.get("round") or 1)
    v["phase"], v["deadline"] = "round_finished", None

    if round_no == 1:
        votes = v.get("votes") or {}
        # A player enters defense when they received at least one valid vote.
        defenders = []
        for target in [int(x) for x in (v.get("targets") or [])]:
            voters = {int(x) for x in (votes.get(str(target)) or [])}
            if voters:
                defenders.append(target)
        v["selected_round_two"] = defenders
        v["defense_candidates"] = defenders

    voting_runtime._put(main, v)

    if round_no == 1:
        defenders = list(v.get("selected_round_two") or [])
        if defenders:
            text = (
                "✅ <b>رای‌گیری دور ۱ به پایان رسید.</b>\n\n"
                "🛡 <b>بازیکنان رفته به دفاع:</b>\n"
                + "\n".join(
                    f"• {html.escape(await _resolve_name(main, uid))}" for uid in defenders
                )
                + "\n\n🔄 برای شروع رای دوم، بازیکنان دفاع را بررسی و تایید کنید."
            )
            markup = InlineKeyboardMarkup(row_width=1).add(
                InlineKeyboardButton("🔄 شروع رای دوم", callback_data="vote:round2"),
                InlineKeyboardButton("🌙 شروع فاز شب", callback_data="start_night"),
                InlineKeyboardButton("🏁 اتمام بازی", callback_data="end_game"),
            )
        else:
            text = "✅ <b>رای‌گیری دور ۱ به پایان رسید.</b>\n\n🛡 هیچ بازیکنی به دفاع نرفت."
            markup = InlineKeyboardMarkup(row_width=1).add(
                InlineKeyboardButton("🌙 شروع فاز شب", callback_data="start_night"),
                InlineKeyboardButton("🏁 اتمام بازی", callback_data="end_game"),
            )
    else:
        text = "✅ <b>رای‌گیری دور ۲ به پایان رسید.</b>\n\nحالا می‌توانید بازی را به فاز شب ببرید یا بازی را تمام کنید."
        markup = InlineKeyboardMarkup(row_width=1).add(
            InlineKeyboardButton("🌙 شروع فاز شب", callback_data="start_night"),
            InlineKeyboardButton("🏁 اتمام بازی", callback_data="end_game"),
        )

    await main.bot.send_message(voting_runtime._gid(main), text, parse_mode="HTML", reply_markup=markup)


async def _cast(main, callback):
    """Register a vote while enforcing voting rights and no self-votes."""
    v = voting_runtime._v(main)
    if v.get("phase") != "voting":
        await callback.answer("⏳ زمان رای‌گیری این هدف تمام شده است.", show_alert=True)
        raise CancelHandler()

    uid = int(callback.from_user.id)
    if uid in voting_runtime._active_rights(v):
        await callback.answer("🚫 حق رای شما گرفته شده است.", show_alert=True)
        raise CancelHandler()

    targets = [int(x) for x in (v.get("targets") or [])]
    idx = int(v.get("target_index") or 0)
    if idx >= len(targets):
        await callback.answer("⏳ این رای‌گیری تمام شده است.", show_alert=True)
        raise CancelHandler()
    target = targets[idx]

    if uid == target:
        await callback.answer("🚫 نمی‌توانید به خودتان رای بدهید.", show_alert=True)
        raise CancelHandler()

    bucket = list((v.setdefault("votes", {})).setdefault(str(target), []))
    if uid in {int(x) for x in bucket}:
        await callback.answer("⚠️ رای شما قبلاً ثبت شده است.", show_alert=True)
        raise CancelHandler()

    bucket.append(uid)
    v["votes"][str(target)] = bucket
    voting_runtime._put(main, v)
    await callback.answer("✅ رای شما ثبت شد.")


async def _round2(main, callback):
    v = voting_runtime._v(main)
    candidates = [int(x) for x in (v.get("defense_candidates") or v.get("selected_round_two") or [])]
    v["selected_round_two"] = candidates
    voting_runtime._put(main, v)

    if not candidates:
        await callback.message.edit_text(
            "🛡 <b>هیچ بازیکنی به دفاع نرفته است.</b>\n\nرای دوم قابل اجرا نیست.",
            reply_markup=InlineKeyboardMarkup(row_width=1).add(
                InlineKeyboardButton("🌙 شروع فاز شب", callback_data="start_night"),
                InlineKeyboardButton("🏁 اتمام بازی", callback_data="end_game"),
            ),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    selected = set(candidates)
    rows = {int(x["player_id"]): x for x in voting_runtime._players(main)}
    buttons = []
    for uid in candidates:
        name = await _resolve_name(main, uid, rows.get(uid, {}).get("seat"))
        buttons.append(InlineKeyboardButton(f"{name} ✅" if uid in selected else name, callback_data=f"vote:r2pick:{uid}"))

    kb = InlineKeyboardMarkup(row_width=1)
    for button in buttons:
        kb.add(button)
    kb.add(InlineKeyboardButton("🚫 گرفتن حق رای", callback_data="vote:rights"))
    kb.add(InlineKeyboardButton("✅ تایید و شروع رای دوم", callback_data="vote:r2confirm"))
    kb.add(InlineKeyboardButton("⬅️ بازگشت", callback_data="vote:settings"))
    await callback.message.edit_text(
        "🔄 <b>بازیکنان دور دوم</b>\n\n"
        "فقط بازیکنانی که در دور اول به دفاع رفته‌اند در این فهرست هستند.",
        reply_markup=kb,
        parse_mode="HTML",
    )
    await callback.answer()


async def _round2_pick(main, callback):
    uid = int(callback.data.split(":")[-1])
    v = voting_runtime._v(main)
    allowed = {int(x) for x in (v.get("defense_candidates") or [])}
    if uid not in allowed:
        await callback.answer("⛔ این بازیکن به دفاع نرفته است.", show_alert=True)
        raise CancelHandler()
    selected = {int(x) for x in (v.get("selected_round_two") or [])}
    if uid in selected:
        selected.remove(uid)
    else:
        selected.add(uid)
    v["selected_round_two"] = sorted(selected)
    voting_runtime._put(main, v)
    await _round2(main, callback)


async def _round2_confirm(main, callback):
    v = voting_runtime._v(main)
    selected = [int(x) for x in (v.get("selected_round_two") or [])]
    if not selected:
        await callback.answer("حداقل یک بازیکن دفاعی را انتخاب کنید.", show_alert=True)
        raise CancelHandler()
    v["round"] = 2
    v["targets"] = selected
    v["target_index"] = 0
    v["votes"] = {}
    v["phase"] = "waiting"
    v["deadline"] = None
    voting_runtime._put(main, v)
    await callback.answer("🔄 رای دوم آماده شد.")
    await _durable_start_wait(main)
    raise CancelHandler()


async def _end(main, callback):
    v = voting_runtime._v(main)
    v["phase"], v["deadline"] = "finished", None
    voting_runtime._put(main, v)
    kb = InlineKeyboardMarkup(row_width=1).add(
        InlineKeyboardButton("🌙 شروع فاز شب", callback_data="start_night"),
        InlineKeyboardButton("🏁 اتمام بازی", callback_data="end_game"),
    )
    await callback.message.edit_text("🏁 <b>رای‌گیری به پایان رسید.</b>\n\nمرحله بعد را انتخاب کنید.", parse_mode="HTML", reply_markup=kb)
    await callback.answer()


def _remove_voting_handlers(main):
    dp = getattr(main, "dp", None)
    reg = getattr(getattr(dp, "callback_query_handlers", None), "handlers", None)
    if reg is None:
        return
    names = {"cast", "r2", "r2pick", "r2confirm", "end"}
    kept = []
    for item in list(reg):
        fn = getattr(item, "handler", None)
        if getattr(fn, "__name__", "") in names:
            continue
        kept.append(item)
    reg[:] = kept


def install(main):
    if getattr(main, "_voting_timer_patch_installed", False):
        return False

    voting_runtime._start_wait = _durable_start_wait
    voting_runtime._start_target = _start_target
    voting_runtime._finish_round = _finish_round
    voting_runtime._round2 = _round2

    _remove_voting_handlers(main)

    dp = getattr(main, "dp", None)
    if dp is not None:
        async def only_mod(c):
            if int(c.from_user.id) != int(getattr(main, "moderator_id", -1) or -1):
                await c.answer("⛔ فقط گرداننده دسترسی دارد.", show_alert=True)
                raise CancelHandler()

        async def cast_handler(c):
            await _cast(main, c)

        async def r2_handler(c):
            await only_mod(c)
            await _round2(main, c)

        async def r2pick_handler(c):
            await only_mod(c)
            await _round2_pick(main, c)

        async def r2confirm_handler(c):
            await only_mod(c)
            await _round2_confirm(main, c)

        async def end_handler(c):
            await only_mod(c)
            await _end(main, c)

        dp.register_callback_query_handler(cast_handler, lambda c: c.data == "vote:cast", state="*")
        dp.register_callback_query_handler(r2_handler, lambda c: c.data == "vote:round2", state="*")
        dp.register_callback_query_handler(r2pick_handler, lambda c: c.data.startswith("vote:r2pick:"), state="*")
        dp.register_callback_query_handler(r2confirm_handler, lambda c: c.data == "vote:r2confirm", state="*")
        dp.register_callback_query_handler(end_handler, lambda c: c.data == "vote:end", state="*")

    def day_end_keyboard():
        return InlineKeyboardMarkup(row_width=1).add(
            InlineKeyboardButton("🗳 رای‌گیری", callback_data="vote:settings"),
            InlineKeyboardButton("🌙 شروع فاز شب", callback_data="start_night"),
            InlineKeyboardButton("🏁 اتمام بازی", callback_data="end_game"),
        )

    voting_runtime._day_end_kb = day_end_keyboard
    main._voting_timer_patch_installed = True
    return True
