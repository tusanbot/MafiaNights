"""Authoritative day-voting runtime for MafiaNights.

Voting is a day sub-phase, not a second round engine. Its durable state lives
inside the active game's JSON state so webhook workers can recover the phase
without relying on asyncio Tasks as game truth.
"""
from __future__ import annotations

import asyncio
import html
import time
from typing import Any

from aiogram.dispatcher.handler import CancelHandler
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

WAIT_OPTIONS = (15, 20, 30)
VOTE_OPTIONS = (15, 20, 30)
MODE_AUTO = "auto"
MODE_MANUAL = "manual"


def _gid(main):
    for obj in (main, getattr(main, "addons", None)):
        for key in ("group_chat_id", "ALLOWED_GROUP_ID", "GROUP_ID", "group_id"):
            value = getattr(obj, key, None)
            if value:
                try:
                    return int(value)
                except (TypeError, ValueError):
                    pass
    return None


def _runtime(main):
    return getattr(main, "runtime", None)


def _game(main):
    rt = _runtime(main)
    gid = _gid(main)
    if not rt or not gid:
        return None
    return rt.state.active_game(gid)


def _state(main) -> dict[str, Any]:
    game = _game(main)
    return dict((game or {}).get("state") or {})


def _save(main, payload: dict[str, Any]) -> bool:
    game = _game(main)
    rt = _runtime(main)
    if not game or not rt:
        return False
    return rt.state.games.update_game(game["id"], state=payload)


def _players(main) -> list[dict[str, Any]]:
    game = _game(main)
    rt = _runtime(main)
    if game and rt:
        try:
            rows = rt.state.games.list_players(game["id"])
            return [dict(x) for x in rows if str(x.get("status") or "active") not in {"dead", "removed"}]
        except Exception:
            pass
    result = []
    for seat, uid in sorted((getattr(main, "player_slots", {}) or {}).items()):
        result.append({"seat": int(seat), "player_id": int(uid), "nickname": None})
    return result


def _name(main, uid, seat=None) -> str:
    try:
        manager = getattr(main, "nicknames", None)
        for method in ("get_nick", "get"):
            fn = getattr(manager, method, None)
            if fn:
                value = fn(int(uid))
                if value and str(value).strip() not in {"?", "❓", "None", "بازیکن"}:
                    return str(value)
    except Exception:
        pass
    try:
        value = main.display_name(int(uid), None)
        if value and str(value).strip() not in {"?", "❓", "None", "بازیکن"}:
            return str(value)
    except Exception:
        pass
    return f"بازیکن {int(seat or 0)}"


def _player_name(main, row):
    uid = row.get("player_id") or row.get("id")
    return row.get("nickname") or row.get("first_name") or _name(main, uid, row.get("seat"))


def _default_state(main) -> dict[str, Any]:
    rows = _players(main)
    return {
        "voting": {
            "round": 1,
            "wait_seconds": 20,
            "vote_seconds": 20,
            "mode": MODE_AUTO,
            "vote_rights_taken": [],
            "targets": [int(x["player_id"]) for x in rows],
            "target_index": 0,
            "votes": {},
            "started_at": None,
            "deadline": None,
            "phase": "settings",
            "selected_round_two": [],
        }
    }


def _get_voting(main) -> dict[str, Any]:
    payload = _state(main)
    voting = payload.get("voting")
    if not isinstance(voting, dict):
        voting = _default_state(main)["voting"]
        payload["voting"] = voting
        _save(main, payload)
    return voting


def _set_voting(main, **updates):
    payload = _state(main)
    voting = payload.setdefault("voting", _default_state(main)["voting"])
    voting.update(updates)
    _save(main, payload)
    return voting


def _is_moderator(main, uid):
    return int(uid) == int(getattr(main, "moderator_id", -1) or -1)


def _settings_keyboard(v):
    def tick(value, current):
        return " ✅" if value == current else ""
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton(f"⏱ زمان انتظار رای‌گیری: {v['wait_seconds']} ثانیه", callback_data="vote:wait"))
    kb.add(InlineKeyboardButton(f"⏱ زمان هر رای: {v['vote_seconds']} ثانیه", callback_data="vote:duration"))
    kb.add(InlineKeyboardButton(f"🚫 گرفتن حق رای ({len(v.get('vote_rights_taken', []))})", callback_data="vote:rights"))
    mode = "خودکار" if v.get("mode") == MODE_AUTO else "دستی"
    kb.add(InlineKeyboardButton(f"🗳 نوع رای‌گیری: {mode}", callback_data="vote:mode"))
    kb.add(InlineKeyboardButton("▶️ شروع رای‌گیری", callback_data="vote:start"))
    return kb


def _choice_keyboard(prefix: str, values, current: int | str):
    kb = InlineKeyboardMarkup(row_width=1)
    for value in values:
        label = f"{value} ثانیه" if isinstance(value, int) else ("خودکار" if value == MODE_AUTO else "دستی")
        if value == current:
            label += " ✅"
        kb.add(InlineKeyboardButton(label, callback_data=f"vote:{prefix}:{value}"))
    kb.add(InlineKeyboardButton("⬅️ تنظیمات رای‌گیری", callback_data="vote:settings"))
    return kb


def _rights_keyboard(main, v):
    taken = {int(x) for x in v.get("vote_rights_taken", [])}
    kb = InlineKeyboardMarkup(row_width=1)
    for row in _players(main):
        uid = int(row["player_id"])
        label = f"🚫 {_player_name(main, row)}"
        if uid in taken:
            label += " ✅"
        kb.add(InlineKeyboardButton(label, callback_data=f"vote:right:{uid}"))
    kb.add(InlineKeyboardButton("⬅️ تنظیمات رای‌گیری", callback_data="vote:settings"))
    return kb


def _main_day_keyboard():
    return InlineKeyboardMarkup(row_width=1).add(
        InlineKeyboardButton("🗳 رای‌گیری", callback_data="vote:settings"),
        InlineKeyboardButton("🌙 شروع فاز شب", callback_data="start_night"),
    )


def _vote_button():
    return InlineKeyboardMarkup(row_width=1).add(
        InlineKeyboardButton("🗳 رای می‌دهم", callback_data="vote:cast"),
    )


async def _send_settings(main, callback=None):
    v = _get_voting(main)
    text = (
        "🗳 <b>تنظیمات رای‌گیری</b>\n\n"
        f"⏱ زمان انتظار: {v['wait_seconds']} ثانیه\n"
        f"⏱ زمان هر رای: {v['vote_seconds']} ثانیه\n"
        f"🚫 بدون حق رای: {len(v.get('vote_rights_taken', []))} نفر\n"
        f"🗳 نوع: {'خودکار' if v.get('mode') == MODE_AUTO else 'دستی'}"
    )
    if callback and callback.message:
        await callback.message.edit_text(text, reply_markup=_settings_keyboard(v), parse_mode="HTML")
        await callback.answer()
    else:
        await main.bot.send_message(_gid(main), text, reply_markup=_settings_keyboard(v), parse_mode="HTML")


async def _end_target(main):
    v = _get_voting(main)
    targets = list(v.get("targets") or [])
    idx = int(v.get("target_index") or 0)
    if idx >= len(targets):
        return await _finish_round(main)
    target_id = int(targets[idx])
    votes = {int(x) for x in (v.get("votes") or {}).get(str(target_id), [])}
    rows = {int(x["player_id"]): x for x in _players(main)}
    target_name = _name(main, target_id, rows.get(target_id, {}).get("seat"))
    voters = [_name(main, uid, rows.get(uid, {}).get("seat")) for uid in votes]
    voter_text = "\n".join(f"• {html.escape(x)}" for x in voters) if voters else "• هیچ‌کس"
    await main.bot.send_message(
        _gid(main),
        f"📊 <b>نتیجه رای‌گیری برای {html.escape(target_name)}</b>\n\n"
        f"🗳 تعداد رای: <b>{len(votes)}</b>\n👥 رای‌دهندگان:\n{voter_text}",
        parse_mode="HTML",
    )
    v["target_index"] = idx + 1
    v["started_at"] = None
    v["deadline"] = None
    _set_voting(main, **v)
    return await _start_next_target(main)


async def _start_next_target(main):
    v = _get_voting(main)
    targets = list(v.get("targets") or [])
    idx = int(v.get("target_index") or 0)
    if idx >= len(targets):
        return await _finish_round(main)
    target_id = int(targets[idx])
    rows = {int(x["player_id"]): x for x in _players(main)}
    target_name = _name(main, target_id, rows.get(target_id, {}).get("seat"))
    now = time.time()
    deadline = now + int(v["vote_seconds"])
    v["started_at"] = now
    v["deadline"] = deadline
    v["votes"] = v.get("votes") or {}
    v["votes"].setdefault(str(target_id), [])
    v["phase"] = "voting"
    _set_voting(main, **v)
    text = f"🗳 <b>رای برای {html.escape(target_name)}</b>\n\n⏱ {int(v['vote_seconds'])} ثانیه فرصت دارید."
    markup = _vote_button() if v.get("mode") == MODE_AUTO else None
    await main.bot.send_message(_gid(main), text, parse_mode="HTML", reply_markup=markup)
    main._voting_task = asyncio.create_task(_wait_vote_timer(main, deadline))


async def _wait_vote_timer(main, deadline):
    delay = max(0.0, float(deadline) - time.time())
    await asyncio.sleep(delay)
    v = _get_voting(main)
    if v.get("phase") != "voting":
        return
    if v.get("deadline") != deadline:
        return
    await _end_target(main)


async def _start_wait(main):
    v = _get_voting(main)
    deadline = time.time() + int(v["wait_seconds"])
    v["phase"] = "waiting"
    v["started_at"] = time.time()
    v["deadline"] = deadline
    v["target_index"] = 0
    v["votes"] = {}
    _set_voting(main, **v)
    rights = {int(x) for x in v.get("vote_rights_taken", [])}
    rows = _players(main)
    blocked = [html.escape(_player_name(main, r)) for r in rows if int(r["player_id"]) in rights]
    blocked_text = "\n".join(f"• {x}" for x in blocked) if blocked else "• هیچ‌کس"
    await main.bot.send_message(
        _gid(main),
        f"🗳 <b>رای‌گیری پس از {int(v['wait_seconds'])} ثانیه شروع می‌شود.</b>\n"
        f"برای رای به هر بازیکن {int(v['vote_seconds'])} ثانیه فرصت دارید.\n\n"
        f"🚫 <b>بازیکنانی که حق رای ندارند:</b>\n{blocked_text}",
        parse_mode="HTML",
    )
    main._voting_task = asyncio.create_task(_wait_start_timer(main, deadline))


async def _wait_start_timer(main, deadline):
    await asyncio.sleep(max(0.0, float(deadline) - time.time()))
    v = _get_voting(main)
    if v.get("phase") != "waiting" or v.get("deadline") != deadline:
        return
    await _start_next_target(main)


async def _finish_round(main):
    v = _get_voting(main)
    round_no = int(v.get("round") or 1)
    v["phase"] = "round_finished"
    v["deadline"] = None
    _set_voting(main, **v)
    kb = InlineKeyboardMarkup(row_width=1).add(
        InlineKeyboardButton("🔄 شروع رای دوم", callback_data="vote:round2"),
        InlineKeyboardButton("🌙 پایان رای‌گیری", callback_data="vote:end"),
    )
    await main.bot.send_message(_gid(main), f"✅ رای‌گیری دور {round_no} به پایان رسید.", reply_markup=kb)


async def _round_two_select(main, callback):
    v = _get_voting(main)
    rows = _players(main)
    selected = {int(x) for x in v.get("selected_round_two", [])}
    kb = InlineKeyboardMarkup(row_width=1)
    for row in rows:
        uid = int(row["player_id"])
        label = f"{_player_name(main, row)}" + (" ✅" if uid in selected else "")
        kb.add(InlineKeyboardButton(label, callback_data=f"vote:r2pick:{uid}"))
    kb.add(InlineKeyboardButton("✅ تایید و شروع رای دوم", callback_data="vote:r2confirm"))
    kb.add(InlineKeyboardButton("⬅️ بازگشت", callback_data="vote:settings"))
    await callback.message.edit_text("🔄 <b>بازیکنان رای دوم را انتخاب کنید.</b>", reply_markup=kb, parse_mode="HTML")
    await callback.answer()


async def _finish_to_night(main, callback):
    v = _get_voting(main)
    v["phase"] = "finished"
    v["deadline"] = None
    _set_voting(main, **v)
    rt = _runtime(main)
    gid = _gid(main)
    if rt and gid:
        try:
            rt.days.start_night(gid, extra={"voting_round": int(v.get("round") or 1), "voting": v})
        except Exception:
            pass
    await callback.message.edit_text("🛡 <b>هیچ بازیکنی وارد دفاع نمی‌شود.</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(row_width=1).add(InlineKeyboardButton("🌙 ورود به فاز شب", callback_data="vote:night")))
    await callback.answer()


async def _cast_vote(main, callback):
    v = _get_voting(main)
    if v.get("phase") != "voting":
        await callback.answer("⚠️ در حال حاضر رای‌گیری فعال نیست.", show_alert=True)
        raise CancelHandler()
    voter = int(callback.from_user.id)
    blocked = {int(x) for x in v.get("vote_rights_taken", [])}
    if voter in blocked:
        await callback.answer("🚫 حق رای شما گرفته شده است.", show_alert=True)
        raise CancelHandler()
    players = {int(x["player_id"]): x for x in _players(main)}
    if voter not in players:
        await callback.answer("⛔ شما بازیکن این بازی نیستید.", show_alert=True)
        raise CancelHandler()
    target_id = int((v.get("targets") or [])[int(v.get("target_index") or 0)])
    votes = v.setdefault("votes", {})
    bucket = set(int(x) for x in votes.setdefault(str(target_id), []))
    if voter in bucket:
        await callback.answer("⚠️ رای شما قبلاً ثبت شده است.", show_alert=True)
        raise CancelHandler()
    bucket.add(voter)
    votes[str(target_id)] = sorted(bucket)
    _set_voting(main, **v)
    await callback.answer("✅ رای شما ثبت شد.")
    raise CancelHandler()


def _install_callback(dp, fn, predicate):
    dp.register_callback_query_handler(fn, predicate, state="*")


def install(main):
    if getattr(main, "_voting_runtime_installed", False):
        return False
    dp = getattr(main, "dp", None)
    if dp is None:
        return False

    async def settings(callback):
        if not _is_moderator(main, callback.from_user.id):
            await callback.answer("⛔ فقط گرداننده می‌تواند تنظیمات رای‌گیری را تغییر دهد.", show_alert=True)
            raise CancelHandler()
        await _send_settings(main, callback)

    async def wait_menu(callback):
        if not _is_moderator(main, callback.from_user.id):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); raise CancelHandler()
        v = _get_voting(main); await callback.message.edit_text("⏱ <b>زمان انتظار رای‌گیری</b>", reply_markup=_choice_keyboard("wait", WAIT_OPTIONS, v["wait_seconds"]), parse_mode="HTML"); await callback.answer()

    async def duration_menu(callback):
        if not _is_moderator(main, callback.from_user.id):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); raise CancelHandler()
        v = _get_voting(main); await callback.message.edit_text("⏱ <b>زمان هر رای</b>", reply_markup=_choice_keyboard("duration", VOTE_OPTIONS, v["vote_seconds"]), parse_mode="HTML"); await callback.answer()

    async def choose_wait(callback):
        value = int(str(callback.data).rsplit(":", 1)[1]); _set_voting(main, wait_seconds=value); await _send_settings(main, callback)

    async def choose_duration(callback):
        value = int(str(callback.data).rsplit(":", 1)[1]); _set_voting(main, vote_seconds=value); await _send_settings(main, callback)

    async def rights(callback):
        if not _is_moderator(main, callback.from_user.id):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); raise CancelHandler()
        v = _get_voting(main); await callback.message.edit_text("🚫 <b>گرفتن حق رای</b>", reply_markup=_rights_keyboard(main, v), parse_mode="HTML"); await callback.answer()

    async def toggle_right(callback):
        v = _get_voting(main); uid = int(str(callback.data).rsplit(":", 1)[1]); taken = {int(x) for x in v.get("vote_rights_taken", [])}; taken.symmetric_difference_update({uid}); _set_voting(main, vote_rights_taken=sorted(taken)); await rights(callback)

    async def mode(callback):
        if not _is_moderator(main, callback.from_user.id):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); raise CancelHandler()
        v = _get_voting(main); await callback.message.edit_text("🗳 <b>نوع رای‌گیری</b>", reply_markup=_choice_keyboard("mode", (MODE_AUTO, MODE_MANUAL), v.get("mode")), parse_mode="HTML"); await callback.answer()

    async def choose_mode(callback):
        value = str(callback.data).rsplit(":", 1)[1]; _set_voting(main, mode=value); await _send_settings(main, callback)

    async def start(callback):
        if not _is_moderator(main, callback.from_user.id):
            await callback.answer("⛔ فقط گرداننده می‌تواند رای‌گیری را شروع کند.", show_alert=True); raise CancelHandler()
        v = _get_voting(main)
        if v.get("phase") in {"waiting", "voting"}:
            await callback.answer("⚠️ رای‌گیری در حال اجراست.", show_alert=True); raise CancelHandler()
        rows = _players(main)
        v.update(_default_state(main)["voting"])
        v["wait_seconds"] = int(v.get("wait_seconds") or 20)
        v["vote_seconds"] = int(v.get("vote_seconds") or 20)
        v["mode"] = v.get("mode") or MODE_AUTO
        v["vote_rights_taken"] = sorted({int(x) for x in v.get("vote_rights_taken", [])})
        v["targets"] = [int(x["player_id"]) for x in rows]
        _set_voting(main, **v)
        rt = _runtime(main); gid = _gid(main)
        if rt and gid:
            try: rt.days.set_phase(gid, "voting", extra={"voting": v})
            except Exception: pass
        await callback.answer("🗳 رای‌گیری آماده شد.")
        await _start_wait(main)
        raise CancelHandler()

    async def round2(callback):
        if not _is_moderator(main, callback.from_user.id):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); raise CancelHandler()
        await _round_two_select(main, callback)

    async def r2pick(callback):
        v = _get_voting(main); uid = int(str(callback.data).rsplit(":", 1)[1]); selected = {int(x) for x in v.get("selected_round_two", [])}; selected.symmetric_difference_update({uid}); _set_voting(main, selected_round_two=sorted(selected)); await _round_two_select(main, callback)

    async def r2confirm(callback):
        if not _is_moderator(main, callback.from_user.id):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); raise CancelHandler()
        v = _get_voting(main); selected = [int(x) for x in v.get("selected_round_two", [])]
        if not selected:
            await callback.answer("⚠️ حداقل یک بازیکن را انتخاب کنید.", show_alert=True); raise CancelHandler()
        v["round"] = 2; v["targets"] = selected; v["target_index"] = 0; v["votes"] = {}; v["phase"] = "waiting"; v["started_at"] = None; v["deadline"] = None; _set_voting(main, **v); await callback.answer("🔄 رای دوم آماده شد."); await _start_wait(main); raise CancelHandler()

    async def end(callback):
        if not _is_moderator(main, callback.from_user.id):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); raise CancelHandler()
        await _finish_to_night(main, callback)

    async def night(callback):
        if not _is_moderator(main, callback.from_user.id):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); raise CancelHandler()
        rt = _runtime(main); gid = _gid(main)
        if rt and gid:
            try: rt.days.start_night(gid, extra={"voting": _get_voting(main)})
            except Exception: pass
        await callback.answer("🌙 فاز شب شروع شد.")
        raise CancelHandler()

    _install_callback(dp, settings, lambda c: c.data == "vote:settings")
    _install_callback(dp, wait_menu, lambda c: c.data == "vote:wait")
    _install_callback(dp, duration_menu, lambda c: c.data == "vote:duration")
    _install_callback(dp, choose_wait, lambda c: str(c.data or "").startswith("vote:wait:"))
    _install_callback(dp, choose_duration, lambda c: str(c.data or "").startswith("vote:duration:"))
    _install_callback(dp, rights, lambda c: c.data == "vote:rights")
    _install_callback(dp, toggle_right, lambda c: str(c.data or "").startswith("vote:right:"))
    _install_callback(dp, mode, lambda c: c.data == "vote:mode")
    _install_callback(dp, choose_mode, lambda c: str(c.data or "").startswith("vote:mode:"))
    _install_callback(dp, start, lambda c: c.data == "vote:start")
    _install_callback(dp, _cast_vote, lambda c: c.data == "vote:cast")
    _install_callback(dp, round2, lambda c: c.data == "vote:round2")
    _install_callback(dp, r2pick, lambda c: str(c.data or "").startswith("vote:r2pick:"))
    _install_callback(dp, r2confirm, lambda c: c.data == "vote:r2confirm")
    _install_callback(dp, end, lambda c: c.data == "vote:end")
    _install_callback(dp, night, lambda c: c.data == "vote:night")

    # Replace only the day-end renderer in the authoritative stable engine.
    # Its _advance closure resolves this global at call time, so no second round
    # engine is introduced.
    import runtime.stable_round_engine as stable
    if not getattr(stable, "_voting_end_day_wrapped", False):
        original_end_day = stable._end_day

        async def end_day_with_voting(engine_main):
            await original_end_day.__call__(engine_main) if False else None
            # Reproduce the authoritative day-end state cleanup, but expose both
            # requested next actions. This is the only ownership point for DAY end.
            if getattr(engine_main, "_stable_day_ended", False):
                return
            engine_main._stable_day_ended = True
            engine_main._stable_day_active = False
            engine_main._stable_phase = "ended"
            engine_main._gm_extra_turn_active = False
            engine_main._gm_extra_phase = False
            task = getattr(engine_main, "turn_timer_task", None)
            if task and not task.done(): task.cancel()
            engine_main.turn_timer_task = None
            mid = getattr(engine_main, "current_turn_message_id", None)
            gid = _gid(engine_main)
            if gid and mid:
                try: await engine_main.bot.delete_message(gid, int(mid))
                except Exception: pass
            engine_main.current_turn_message_id = None
            engine_main.challenge_mode = False
            engine_main.pending_challenges = {}
            engine_main.active_challenger_seats = set()
            engine_main.current_turn_index = len(getattr(engine_main, "turn_order", []) or [])
            rt = _runtime(engine_main)
            if rt and gid:
                try: rt.days.set_phase(gid, "day_end")
                except Exception: pass
            await engine_main.bot.send_message(gid, "✅ همه بازیکنا صحبت کردن. فاز روز تموم شد.", reply_markup=_main_day_keyboard())

        stable._end_day = end_day_with_voting
        stable._voting_end_day_wrapped = True

    main._voting_runtime_installed = True
    return True
