"""Serverless-safe voting transitions with scenario-driven two-round rules."""
from __future__ import annotations

import asyncio
import html
import logging
import math
import time

from aiogram.dispatcher.handler import CancelHandler
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from runtime import voting_runtime


def _scenario(main):
    game = voting_runtime._game(main)
    if not game:
        return {}
    scenario_id = game.get("scenario_id")
    state = getattr(getattr(main, "runtime", None), "state", None)
    repo = getattr(state, "scenarios", None)
    try:
        row = repo.get_by_id(scenario_id) if repo and scenario_id else None
        return dict(row or {})
    except Exception:
        return {}


def _rules(main):
    config = _scenario(main).get("config") or {}
    if not isinstance(config, dict):
        config = {}
    voting = config.get("voting") or {}
    if not isinstance(voting, dict):
        voting = {}
    r1 = voting.get("round_1") or {}
    r2 = voting.get("round_2") or {}
    return {
        "enabled": bool(voting.get("enabled", True)),
        "self_vote": bool(voting.get("self_vote", False)),
        "r1": r1 if isinstance(r1, dict) else {},
        "r2": r2 if isinstance(r2, dict) else {},
    }


def _threshold(rules, player_count):
    spec = (rules.get("r1") or {}).get("defense_threshold") or {}
    if not isinstance(spec, dict):
        spec = {"type": str(spec)}
    kind = str(spec.get("type") or "ceil_half").lower()
    n = int(player_count)
    if kind in {"floor_half", "half_floor", "floor-half"}:
        return max(1, n // 2)
    if kind in {"ceil_half", "half_ceil", "ceil-half"}:
        return max(1, math.ceil(n / 2))
    if kind in {"exact", "count"}:
        try:
            return max(1, int(spec.get("value")))
        except Exception:
            return None
    if kind in {"percentage", "percent"}:
        try:
            return max(1, math.ceil(n * float(spec.get("value")) / 100.0))
        except Exception:
            return None
    return max(1, math.ceil(n / 2))


def _round2_mode(rules):
    mode = str((rules.get("r2") or {}).get("target_selection") or "manual").lower()
    return "automatic" if mode in {"automatic", "auto", "خودکار"} else "manual"


def _round2_targets_automatic(rules, candidates, player_count):
    rule = (rules.get("r2") or {}).get("target_count")
    if rule in (None, "all", "all_candidates", "همه"):
        return list(candidates)
    if isinstance(rule, dict):
        kind = str(rule.get("type") or "all").lower()
        if kind in {"count", "exact"}:
            try:
                return list(candidates)[: max(0, int(rule.get("value")))]
            except Exception:
                return list(candidates)
        if kind in {"floor_half", "ceil_half"}:
            count = player_count // 2 if kind == "floor_half" else math.ceil(player_count / 2)
            return list(candidates)[: max(0, int(count))]
    try:
        return list(candidates)[: max(0, int(rule))]
    except Exception:
        return list(candidates)


def _round1_voters(main, v):
    present = {int(x["player_id"]) for x in voting_runtime._players(main)}
    return present - voting_runtime._active_rights(v)


def _round2_voters(main, v, rules):
    voters = _round1_voters(main, v)
    if not bool((rules.get("r2") or {}).get("defenders_can_vote", True)):
        voters -= {int(x) for x in (v.get("round2_targets") or v.get("selected_round_two") or [])}
    return voters


def _current_voters(main, v):
    if int(v.get("round") or 1) == 2:
        return _round2_voters(main, v, _rules(main))
    return _round1_voters(main, v)


async def _resolve_name(main, uid, seat=None):
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


def _row_map(main):
    return {int(x["player_id"]): x for x in voting_runtime._players(main)}


async def _send_round2_settings(main, callback=None):
    v = voting_runtime._v(main)
    rules = _rules(main)
    voters = _round2_voters(main, v, rules)
    targets = [int(x) for x in (v.get("round2_targets") or v.get("selected_round_two") or [])]
    rows = _row_map(main)
    target_text = "\n".join(f"• {html.escape(await _resolve_name(main, uid, rows.get(uid, {}).get('seat')))}" for uid in targets) or "• هیچ‌کس"
    voter_text = "\n".join(f"• {html.escape(await _resolve_name(main, uid, rows.get(uid, {}).get('seat')))}" for uid in sorted(voters)) or "• هیچ‌کس"
    defender_vote = "دارند" if bool((rules.get("r2") or {}).get("defenders_can_vote", True)) else "ندارند"
    text = (
        "⚙️ <b>تنظیمات رأی‌گیری دور ۲</b>\n\n"
        f"🛡 <b>هدف‌های دور ۲:</b>\n{target_text}\n\n"
        f"🗳 <b>رأی‌دهندگان دور ۲:</b> {len(voters)} نفر\n{voter_text}\n\n"
        f"👤 بازیکنان داخل دفاع حق رأی {defender_vote}.\n"
        f"⏱ زمان انتظار: {int(v.get('wait_seconds', 20))} ثانیه\n"
        f"⏱ زمان هر رأی: {int(v.get('vote_seconds', 20))} ثانیه"
    )
    kb = InlineKeyboardMarkup(row_width=1).add(
        InlineKeyboardButton(f"⏱ زمان انتظار: {int(v.get('wait_seconds', 20))} ثانیه", callback_data="vote:wait"),
        InlineKeyboardButton(f"⏱ زمان هر رأی: {int(v.get('vote_seconds', 20))} ثانیه", callback_data="vote:duration"),
        InlineKeyboardButton("▶️ شروع رأی‌گیری دور ۲", callback_data="vote:start"),
        InlineKeyboardButton("⬅️ بازگشت به انتخاب دفاع", callback_data="vote:round2"),
    )
    if callback is not None:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        await callback.answer()
    else:
        await main.bot.send_message(voting_runtime._gid(main), text, reply_markup=kb, parse_mode="HTML")


async def _durable_start_wait(main):
    v = voting_runtime._v(main)
    voters = _current_voters(main, v)
    now = time.time()
    if v.get("mode") == voting_runtime.MANUAL:
        v.update(phase="manual_ready", started_at=None, deadline=None, target_index=0, votes={}, eligible_voters=sorted(voters))
        voting_runtime._put(main, v)
        await main.bot.send_message(
            voting_runtime._gid(main),
            "🗳 <b>شروع رای‌گیری</b>\n\nرای‌گیری دستی آماده است. با زدن دکمه زیر توسط گرداننده، رای‌گیری نفر اول شروع می‌شود.",
            parse_mode="HTML", reply_markup=voting_runtime._manual_start_kb(),
        )
        main._voting_task = None
        return
    v.update(phase="waiting", started_at=now, deadline=now + int(v["wait_seconds"]), target_index=0, votes={}, eligible_voters=sorted(voters))
    voting_runtime._put(main, v)
    rows = _row_map(main)
    names = [await _resolve_name(main, uid, rows.get(uid, {}).get("seat")) for uid in sorted(voters)]
    blocked = voting_runtime._active_rights(v)
    blocked_names = [await _resolve_name(main, uid, rows.get(uid, {}).get("seat")) for uid in sorted(blocked)]
    blocked_text = "\n".join(f"• {html.escape(x)}" for x in blocked_names) if blocked_names else "• هیچ‌کس"
    await main.bot.send_message(
        voting_runtime._gid(main),
        f"🗳 <b>رأی‌گیری دور {int(v.get('round') or 1)} پس از {int(v['wait_seconds'])} ثانیه شروع می‌شود.</b>\nبرای هر هدف {int(v['vote_seconds'])} ثانیه فرصت دارید.\n\n👥 <b>افراد دارای حق رأی:</b> {len(names)} نفر\n🚫 <b>حق رأی گرفته‌شده:</b>\n{blocked_text}",
        parse_mode="HTML",
    )
    # Vercel webhooks are ephemeral; keep this invocation alive through the configured wait.
    await asyncio.sleep(max(0, float(v["deadline"]) - time.time()))
    current = voting_runtime._v(main)
    if current.get("phase") != "waiting" or current.get("deadline") != v["deadline"]:
        main._voting_task = None
        return

    await _start_target(main)

    # Keep this invocation alive through every automatic target.
    while True:
        current = voting_runtime._v(main)
        if current.get("mode") != voting_runtime.AUTO or current.get("phase") != "voting":
            break
        deadline = current.get("deadline")
        if deadline is None:
            break
        await asyncio.sleep(max(0, float(deadline) - time.time()))
        current = voting_runtime._v(main)
        if current.get("phase") != "voting" or current.get("deadline") != deadline:
            continue
        await _auto_end_target(main)

    main._voting_task = None


async def _start_target(main):
    v = voting_runtime._v(main)
    targets = [int(x) for x in (v.get("targets") or [])]
    idx = int(v.get("target_index") or 0)
    if idx >= len(targets):
        return await voting_runtime._finish_round(main)
    target = targets[idx]
    rows = _row_map(main)
    name = await _resolve_name(main, target, rows.get(target, {}).get("seat"))
    now = time.time()
    deadline = None if v.get("mode") == voting_runtime.MANUAL else now + int(v["vote_seconds"])
    v["phase"], v["started_at"], v["deadline"] = "voting", now, deadline
    v["target_vote_ended"] = False
    v.setdefault("votes", {}).setdefault(str(target), [])
    v["eligible_voters"] = sorted(_current_voters(main, v))
    voting_runtime._put(main, v)
    markup = (
        InlineKeyboardMarkup(row_width=1).add(InlineKeyboardButton("🗳 رأی می‌دهم", callback_data="vote:autocast"))
        if v.get("mode") == voting_runtime.AUTO
        else voting_runtime._manual_next_kb(idx >= len(targets) - 1)
    )
    sent = await main.bot.send_message(
        voting_runtime._gid(main), voting_runtime._vote_message_text(main, v, target),
        parse_mode="HTML", reply_markup=markup,
    )
    v["vote_message_id"] = int(sent.message_id)
    voting_runtime._put(main, v)
    # Automatic voting timers are awaited by _durable_start_wait(). A background
    # task is not reliable on Vercel because the webhook invocation can end.
    main._voting_task = None


async def _auto_end_target(main):
    """Close the current target in-place and immediately advance."""
    v = voting_runtime._v(main)
    targets = [int(x) for x in (v.get("targets") or [])]
    idx = int(v.get("target_index") or 0)
    if idx >= len(targets):
        return await _finish_round(main)

    target = targets[idx]
    message_id = v.get("vote_message_id")
    v["target_vote_ended"] = True
    voting_runtime._put(main, v)

    # Keep the complete result in the original voting message.
    if message_id:
        try:
            await main.bot.edit_message_text(
                voting_runtime._vote_message_text(main, v, target),
                chat_id=voting_runtime._gid(main),
                message_id=int(message_id),
                parse_mode="HTML",
                reply_markup=voting_runtime._disabled_vote_kb(),
            )
        except Exception:
            pass

    v["target_index"] = idx + 1
    v["started_at"] = None
    v["deadline"] = None
    voting_runtime._put(main, v)

    if idx + 1 < len(targets):
        await _start_target(main)
    else:
        await _finish_round(main)

async def _finish_round(main):
    v = voting_runtime._v(main)
    round_no = int(v.get("round") or 1)
    v["phase"], v["deadline"] = "round_finished", None
    if round_no == 1:
        rules = _rules(main)
        threshold = _threshold(rules, len(voting_runtime._players(main)))
        votes = v.get("votes") or {}
        candidates = []
        for target in [int(x) for x in (v.get("targets") or [])]:
            count = len(voting_runtime._vote_records(v, target))
            if threshold is not None and count >= threshold:
                candidates.append(target)
        v["defense_threshold"] = threshold
        v["defense_candidates"] = candidates
        v["selected_round_two"] = []
        v["round2_targets"] = []
    voting_runtime._put(main, v)

    if round_no == 1:
        candidates = [int(x) for x in (v.get("defense_candidates") or [])]
        threshold = v.get("defense_threshold")
        rows = _row_map(main)
        if candidates:
            lines = [f"• {html.escape(await _resolve_name(main, uid, rows.get(uid, {}).get('seat')))}" for uid in candidates]
            threshold_text = f"حدنصاب: <b>{int(threshold)}</b> رأی" if threshold else "حدنصاب سناریو تعریف نشده است"
            text = "✅ <b>رأی‌گیری دور ۱ به پایان رسید.</b>\n\n" + threshold_text + "\n🛡 <b>واجدین شرایط دفاع:</b>\n" + "\n".join(lines)
            kb = InlineKeyboardMarkup(row_width=1).add(
                InlineKeyboardButton("🔄 شروع رای دوم", callback_data="vote:round2"),
                InlineKeyboardButton("🌌 شروع فاز شب", callback_data="start_night"),
                InlineKeyboardButton("🏁 اتمام بازی", callback_data="end_game"),
            )
        else:
            text = "✅ <b>رأی‌گیری دور ۱ به پایان رسید.</b>\n\n🛡 هیچ بازیکنی به حدنصاب دفاع نرسید."
            kb = InlineKeyboardMarkup(row_width=1).add(
                InlineKeyboardButton("🌌 شروع فاز شب", callback_data="start_night"),
                InlineKeyboardButton("🏁 اتمام بازی", callback_data="end_game"),
            )
    else:
        text = "🏁 <b>رأی‌گیری دور ۲ به پایان رسید.</b>\n\nمرحله بعد را انتخاب کنید."
        kb = InlineKeyboardMarkup(row_width=1).add(
            InlineKeyboardButton("🌌 شروع فاز شب", callback_data="start_night"),
            InlineKeyboardButton("🏁 اتمام بازی", callback_data="end_game"),
        )
    await main.bot.send_message(voting_runtime._gid(main), text, parse_mode="HTML", reply_markup=kb)


async def _cast(main, callback):
    v = voting_runtime._v(main)
    if v.get("phase") != "voting":
        await callback.answer("⏳ زمان رأی‌گیری این هدف تمام شده است.", show_alert=True); raise CancelHandler()
    uid = int(callback.from_user.id)
    eligible = {int(x) for x in (v.get("eligible_voters") or _current_voters(main, v))}
    if uid not in eligible:
        await callback.answer("🚫 شما در این دور حق رأی ندارید.", show_alert=True); raise CancelHandler()
    targets = [int(x) for x in (v.get("targets") or [])]
    idx = int(v.get("target_index") or 0)
    if idx >= len(targets):
        await callback.answer("⏳ این رأی‌گیری تمام شده است.", show_alert=True); raise CancelHandler()
    target = targets[idx]
    if uid == target and not _rules(main).get("self_vote", False):
        await callback.answer("🚫 نمی‌توانید به خودتان رأی بدهید.", show_alert=True); raise CancelHandler()
    records = voting_runtime._vote_records(v, target)
    if uid in {int(x["user_id"]) for x in records}:
        await callback.answer("⚠️ رأی شما قبلاً ثبت شده است.", show_alert=True); raise CancelHandler()
    bucket = list(v.setdefault("votes", {}).setdefault(str(target), []))
    bucket.append({"user_id": uid, "voted_at": voting_runtime._vote_timestamp()})
    v["votes"][str(target)] = bucket
    voting_runtime._put(main, v)
    message_id = v.get("vote_message_id")
    if message_id:
        try:
            await main.bot.edit_message_text(
                voting_runtime._vote_message_text(main, v, target),
                chat_id=voting_runtime._gid(main),
                message_id=int(message_id),
                parse_mode="HTML",
                reply_markup=(
                    voting_runtime._manual_next_kb(idx >= len(targets) - 1)
                    if v.get("mode") == voting_runtime.MANUAL
                    else InlineKeyboardMarkup(row_width=1).add(
                        InlineKeyboardButton("🗳 رای می‌دهم", callback_data="vote:cast")
                    )
                )            )
        except Exception: pass
    await callback.answer("✅ رأی شما ثبت شد.")


async def _manual_start(main, callback):
    if int(callback.from_user.id) != int(getattr(main, "moderator_id", -1) or -1):
        await callback.answer("⛔ فقط گرداننده دسترسی دارد.", show_alert=True); raise CancelHandler()
    v=voting_runtime._v(main)
    if v.get("mode") != voting_runtime.MANUAL or v.get("phase") != "manual_ready":
        await callback.answer("⛔ رأی‌گیری دستی آماده نیست.", show_alert=True); raise CancelHandler()
    await callback.answer("▶️ رأی‌گیری نفر اول شروع شد."); await _start_target(main); raise CancelHandler()

async def _manual_next(main, callback):
    if int(callback.from_user.id) != int(getattr(main, "moderator_id", -1) or -1):
        await callback.answer("⛔ فقط گرداننده دسترسی دارد.", show_alert=True); raise CancelHandler()
    v=voting_runtime._v(main)
    if v.get("mode") != voting_runtime.MANUAL or v.get("phase") != "voting":
        await callback.answer("⛔ رأی‌گیری دستی فعال نیست.", show_alert=True); raise CancelHandler()
    idx = int(v.get("target_index") or 0)
    targets = [int(x) for x in (v.get("targets") or [])]
    if idx >= len(targets):
        await callback.answer("⛔ هدف دیگری برای رأی‌گیری وجود ندارد.", show_alert=True); raise CancelHandler()
    target = targets[idx]
    mid=v.get("vote_message_id")
    v["target_vote_ended"] = True
    voting_runtime._put(main, v)
    if mid:
        try:
            await main.bot.edit_message_text(
                voting_runtime._vote_message_text(main, v, target),
                chat_id=voting_runtime._gid(main),
                message_id=int(mid),
                parse_mode="HTML",
                reply_markup=voting_runtime._disabled_vote_kb(),
            )
        except Exception:
            pass
    v["target_index"]=idx+1; v["started_at"]=None; v["deadline"]=None; voting_runtime._put(main,v)
    await callback.answer("➡️ نفر بعدی"); await _start_target(main); raise CancelHandler()

async def _manual_end(main, callback):
    if int(callback.from_user.id) != int(getattr(main, "moderator_id", -1) or -1):
        await callback.answer("⛔ فقط گرداننده دسترسی دارد.", show_alert=True); raise CancelHandler()
    v=voting_runtime._v(main)
    if v.get("mode") != voting_runtime.MANUAL or v.get("phase") != "voting":
        await callback.answer("⛔ رأی‌گیری دستی فعال نیست.", show_alert=True); raise CancelHandler()
    idx = int(v.get("target_index") or 0)
    targets = [int(x) for x in (v.get("targets") or [])]
    if idx < len(targets):
        target = targets[idx]
        mid=v.get("vote_message_id")
        v["target_vote_ended"] = True
        voting_runtime._put(main, v)
        if mid:
            try:
                await main.bot.edit_message_text(
                    voting_runtime._vote_message_text(main, v, target),
                    chat_id=voting_runtime._gid(main),
                    message_id=int(mid),
                    parse_mode="HTML",
                    reply_markup=voting_runtime._disabled_vote_kb(),
                )
            except Exception:
                pass
    v["target_index"]=len(targets); v["started_at"]=None; v["deadline"]=None; voting_runtime._put(main,v)
    await callback.answer("🏁 رأی‌گیری این دور به پایان رسید."); await voting_runtime._finish_round(main); raise CancelHandler()

async def _vote_noop(callback):
    await callback.answer("این پیام مربوط به مرحله قبلی رأی‌گیری است.")


async def _round2(main, callback):
    v = voting_runtime._v(main)
    rules = _rules(main)
    candidates = [int(x) for x in (v.get("defense_candidates") or [])]
    if not candidates:
        await callback.message.edit_text(
            "🛡 <b>هیچ بازیکنی به حدنصاب دفاع نرسیده است.</b>",
            reply_markup=InlineKeyboardMarkup(row_width=1).add(
                InlineKeyboardButton("🌌 شروع فاز شب", callback_data="start_night"),
                InlineKeyboardButton("🏁 اتمام بازی", callback_data="end_game"),
            ), parse_mode="HTML")
        await callback.answer()
        return
    if _round2_mode(rules) == "automatic":
        selected = _round2_targets_automatic(rules, candidates, len(voting_runtime._players(main)))
        v["round2_targets"] = selected
        v["selected_round_two"] = selected
        voting_runtime._put(main, v)
        await _send_round2_settings(main, callback)
        return
    selected = {int(x) for x in (v.get("round2_targets") or v.get("selected_round_two") or [])}
    kb = InlineKeyboardMarkup(row_width=1)
    rows = _row_map(main)
    for uid in candidates:
        name = await _resolve_name(main, uid, rows.get(uid, {}).get("seat"))
        kb.add(InlineKeyboardButton(f"{name}" + (" ✅" if uid in selected else ""), callback_data=f"vote:r2pick:{uid}"))
    kb.add(InlineKeyboardButton("✅ تایید بازیکنان دفاع", callback_data="vote:r2confirm_v2"))
    kb.add(InlineKeyboardButton("⬅️ بازگشت", callback_data="vote:r2back"))
    await callback.message.edit_text(
        "🔄 <b>انتخاب بازیکنان دفاع دور ۲</b>\n\n"
        "فقط بازیکنانی که در دور ۱ به حدنصاب رسیده‌اند در این فهرست هستند.\n"
        "انتخاب هدف‌های دور ۲ مستقل از حق رأی است.",
        reply_markup=kb, parse_mode="HTML")
    await callback.answer()


async def _round2_pick(main, callback):
    uid = int(callback.data.split(":")[-1])
    v = voting_runtime._v(main)
    allowed = {int(x) for x in (v.get("defense_candidates") or [])}
    if uid not in allowed:
        await callback.answer("⛔ این بازیکن به حدنصاب دفاع نرسیده است.", show_alert=True)
        raise CancelHandler()
    selected = {int(x) for x in (v.get("round2_targets") or v.get("selected_round_two") or [])}
    if uid in selected:
        selected.remove(uid)
    else:
        selected.add(uid)
    v["round2_targets"] = sorted(selected)
    v["selected_round_two"] = sorted(selected)
    voting_runtime._put(main, v)
    await _round2(main, callback)


async def _round2_confirm(main, callback):
    v = voting_runtime._v(main)
    rules = _rules(main)
    selected = [int(x) for x in (v.get("round2_targets") or v.get("selected_round_two") or [])]
    if not selected:
        await callback.answer("حداقل یک بازیکن را برای دفاع انتخاب کنید.", show_alert=True)
        raise CancelHandler()
    max_count = (rules.get("r2") or {}).get("max_targets")
    if max_count is not None:
        try:
            if len(selected) > int(max_count):
                await callback.answer(f"حداکثر {int(max_count)} بازیکن قابل انتخاب است.", show_alert=True)
                raise CancelHandler()
        except ValueError:
            pass
    v["round2_targets"] = selected
    v["selected_round_two"] = selected
    v["round"] = 2
    v["phase"] = "round2_settings"
    v["target_index"] = 0
    v["votes"] = {}
    v["deadline"] = None
    v["eligible_voters"] = sorted(_round2_voters(main, v, rules))
    voting_runtime._put(main, v)
    await _send_round2_settings(main, callback)


async def _settings(main, callback):
    v = voting_runtime._v(main)
    if int(v.get("round") or 1) == 2 and v.get("phase") == "round2_settings":
        await _send_round2_settings(main, callback)
        return
    text = (
        "🗳 <b>تنظیمات رأی‌گیری دور ۱</b>\n\n"
        f"⏱ زمان انتظار: {int(v.get('wait_seconds', 20))} ثانیه\n"
        f"⏱ زمان هر رأی: {int(v.get('vote_seconds', 20))} ثانیه\n"
        f"🚫 بدون حق رأی: {len(v.get('vote_rights_taken', []))} نفر\n"
        f"🗳 نوع رأی‌گیری: {'خودکار' if v.get('mode') == voting_runtime.AUTO else 'دستی'}"
    )
    kb = InlineKeyboardMarkup(row_width=1).add(
        InlineKeyboardButton(f"⏱ زمان انتظار: {int(v.get('wait_seconds', 20))} ثانیه", callback_data="vote:wait"),
        InlineKeyboardButton(f"⏱ زمان هر رأی: {int(v.get('vote_seconds', 20))} ثانیه", callback_data="vote:duration"),
        InlineKeyboardButton(f"🚫 گرفتن حق رأی ({len(v.get('vote_rights_taken', []))})", callback_data="vote:rights"),
        InlineKeyboardButton(f"🗳 نوع رأی‌گیری: {'خودکار' if v.get('mode') == voting_runtime.AUTO else 'دستی'}", callback_data="vote:mode"),
        InlineKeyboardButton("▶️ شروع رأی‌گیری", callback_data="vote:start"),
    )
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


def _remove_voting_handlers(main):
    dp = getattr(main, "dp", None)
    reg = getattr(getattr(dp, "callback_query_handlers", None), "handlers", None)
    if reg is None:
        return
    kept = []
    for item in list(reg):
        fn = getattr(item, "handler", None)
        if getattr(fn, "__module__", "") == "runtime.voting_runtime":
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
    if dp is None:
        return False

    async def only_mod(c):
        if int(c.from_user.id) != int(getattr(main, "moderator_id", -1) or -1):
            await c.answer("⛔ فقط گرداننده دسترسی دارد.", show_alert=True)
            raise CancelHandler()

    async def settings_handler(c):
        await only_mod(c); await _settings(main, c)

    async def wait_handler(c):
        await only_mod(c)
        v = voting_runtime._v(main)
        await c.message.edit_text("⏱ <b>زمان انتظار را انتخاب کنید.</b>", reply_markup=voting_runtime._choices("wait", voting_runtime.WAIT_OPTIONS, v.get("wait_seconds", 20)), parse_mode="HTML")
        await c.answer()

    async def wait_set(c):
        await only_mod(c)
        v = voting_runtime._v(main); v["wait_seconds"] = int(c.data.split(":")[-1]); voting_runtime._put(main, v); await _settings(main, c)

    async def duration_handler(c):
        await only_mod(c)
        v = voting_runtime._v(main)
        await c.message.edit_text("⏱ <b>زمان هر رأی را انتخاب کنید.</b>", reply_markup=voting_runtime._choices("duration", voting_runtime.VOTE_OPTIONS, v.get("vote_seconds", 20)), parse_mode="HTML")
        await c.answer()

    async def duration_set(c):
        await only_mod(c)
        v = voting_runtime._v(main); v["vote_seconds"] = int(c.data.split(":")[-1]); voting_runtime._put(main, v); await _settings(main, c)

    async def rights(c):
        await only_mod(c)
        v = voting_runtime._v(main)
        await c.message.edit_text("🚫 <b>بازیکنان بدون حق رأی</b>", reply_markup=voting_runtime._rights_kb(main, v), parse_mode="HTML")
        await c.answer()

    async def right_toggle(c):
        await only_mod(c)
        uid = int(c.data.split(":")[-1])
        v = voting_runtime._v(main)
        rights_set = voting_runtime._active_rights(v)
        if uid in rights_set:
            rights_set.remove(uid)
        else:
            rights_set.add(uid)
        v["vote_rights_taken"] = sorted(rights_set)
        voting_runtime._put(main, v)
        await rights(c)

    async def mode_handler(c):
        await only_mod(c)
        v = voting_runtime._v(main)
        await c.message.edit_text("🗳 <b>نوع رأی‌گیری</b>", reply_markup=voting_runtime._choices("mode", (voting_runtime.AUTO, voting_runtime.MANUAL), v.get("mode")), parse_mode="HTML")
        await c.answer()

    async def mode_set(c):
        await only_mod(c); v = voting_runtime._v(main); v["mode"] = c.data.split(":")[-1]; voting_runtime._put(main, v); await _settings(main, c)

    async def start(c):
        await only_mod(c)
        v = voting_runtime._v(main)
        if v.get("phase") in {"waiting", "voting"}:
            await c.answer("⏳ رأی‌گیری در حال اجراست.", show_alert=True); raise CancelHandler()
        if int(v.get("round") or 1) == 2 and not v.get("round2_targets"):
            await c.answer("⛔ ابتدا بازیکنان دفاع دور ۲ را انتخاب کنید.", show_alert=True); raise CancelHandler()
        rules = _rules(main)
        fresh = dict(v)
        fresh.update(phase="settings", target_index=0, votes={}, deadline=None, eligible_voters=sorted(_current_voters(main, fresh)))
        if int(fresh.get("round") or 1) == 1:
            fresh["targets"] = [int(x["player_id"]) for x in voting_runtime._players(main)]
        else:
            fresh["targets"] = [int(x) for x in (fresh.get("round2_targets") or [])]
            fresh["eligible_voters"] = sorted(_round2_voters(main, fresh, rules))
        voting_runtime._put(main, fresh)
        rt, gid = getattr(main, "runtime", None), voting_runtime._gid(main)
        if rt and gid:
            rt.days.set_phase(gid, "voting", extra={"voting": fresh})
        await c.answer("🗳 رأی‌گیری آماده شد.")
        await _durable_start_wait(main)
        raise CancelHandler()

    async def cast(c):
        await _cast(main, c)

    async def r2(c):
        await only_mod(c); await _round2(main, c)

    async def r2pick(c):
        await only_mod(c); await _round2_pick(main, c)

    async def r2confirm(c):
        await only_mod(c); await _round2_confirm(main, c)
    async def r2back(c):
        await only_mod(c)
        await _settings(main, c)


    handlers = [
        (lambda c: c.data == "vote:settings", settings_handler),
        (lambda c: c.data == "vote:wait", wait_handler),
        (lambda c: c.data.startswith("vote:wait:"), wait_set),
        (lambda c: c.data == "vote:duration", duration_handler),
        (lambda c: c.data.startswith("vote:duration:"), duration_set),
        (lambda c: c.data == "vote:rights", rights),
        (lambda c: c.data.startswith("vote:right:"), right_toggle),
        (lambda c: c.data == "vote:mode", mode_handler),
        (lambda c: c.data.startswith("vote:mode:"), mode_set),
        (lambda c: c.data == "vote:start", start),
        (lambda c: c.data == "vote:manual_start", lambda c: _manual_start(main, c)),
        (lambda c: c.data == "vote:manual_next", lambda c: _manual_next(main, c)),
        (lambda c: c.data == "vote:manual_end", lambda c: _manual_end(main, c)),
        (lambda c: c.data == "vote:noop", _vote_noop),
        (lambda c: c.data == "vote:autocast", cast),
        (lambda c: c.data == "vote:round2", r2),
        (lambda c: c.data.startswith("vote:r2pick:"), r2pick),
        (lambda c: c.data == "vote:r2confirm_v2", r2confirm),
        (lambda c: c.data == "vote:r2back", r2back),
    ]
    for predicate, handler in handlers:
        dp.register_callback_query_handler(handler, predicate, state="*")

    # vote:cast existed in older voting handlers too. Put the canonical cast
    # handler at the very front so a stale legacy callback can never consume
    # the button before the persistent voting state is updated.
    try:
        registry = getattr(getattr(dp, "callback_query_handlers", None), "handlers", None)
        if registry is not None:
            priority_names = {"cast", "r2confirm", "r2pick", "r2"}
            priority_items = [
                item for item in registry
                if getattr(getattr(item, "handler", None), "__name__", "") in priority_names
            ]
            for item in reversed(priority_items):
                registry.remove(item)
                registry.insert(0, item)
    except Exception:
        logging.exception("failed to prioritize canonical vote:cast handler")

    main._voting_timer_patch_installed = True
    return True
