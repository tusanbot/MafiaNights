"""Persistent day-voting runtime for MafiaNights."""
from __future__ import annotations

import asyncio
import html
import time

from aiogram.dispatcher.handler import CancelHandler
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

WAIT_OPTIONS = (15, 20, 30)
VOTE_OPTIONS = (15, 20, 30)
AUTO, MANUAL = "auto", "manual"


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


def _rt(main):
    return getattr(main, "runtime", None)


def _game(main):
    rt, gid = _rt(main), _gid(main)
    return rt.state.active_game(gid) if rt and gid else None


def _state(main):
    return dict((_game(main) or {}).get("state") or {})


def _save(main, payload):
    game, rt = _game(main), _rt(main)
    return bool(game and rt and rt.state.games.update_game(game["id"], state=payload))


def _players(main):
    game, rt = _game(main), _rt(main)
    if game and rt:
        try:
            return [
                dict(x)
                for x in rt.state.games.list_players(game["id"])
                if str(x.get("status") or "active") not in {"dead", "removed"}
            ]
        except Exception:
            pass
    return [
        {"seat": int(s), "player_id": int(uid)}
        for s, uid in sorted((getattr(main, "player_slots", {}) or {}).items())
    ]


def _name(main, uid, seat=None):
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


def _row_name(main, row):
    return row.get("nickname") or row.get("first_name") or _name(
        main, row["player_id"], row.get("seat")
    )


def _default(main):
    return {
        "round": 1,
        "wait_seconds": 20,
        "vote_seconds": 20,
        "mode": AUTO,
        # One shared source of truth. This is intentionally NOT per-round.
        "vote_rights_taken": [],
        "targets": [int(x["player_id"]) for x in _players(main)],
        "target_index": 0,
        "votes": {},
        "started_at": None,
        "deadline": None,
        "phase": "settings",
        "selected_round_two": [],
    }


def _v(main):
    payload = _state(main)
    voting = payload.get("voting")
    if not isinstance(voting, dict):
        voting = _default(main)
        payload["voting"] = voting
        _save(main, payload)
    # Migrate old data from the incorrect temporary per-round field.
    if "vote_rights_taken" not in voting:
        voting["vote_rights_taken"] = list(voting.get("round_two_vote_rights_taken") or [])
        voting.pop("round_two_vote_rights_taken", None)
        _put(main, voting)
    elif "round_two_vote_rights_taken" in voting:
        # The old field was a separate authority and must no longer affect voting.
        voting.pop("round_two_vote_rights_taken", None)
        _put(main, voting)
    return voting


def _put(main, voting):
    payload = _state(main)
    payload["voting"] = voting
    _save(main, payload)
    return voting


def _active_rights(v):
    """Return the shared set of users whose voting right is currently revoked."""
    return {int(x) for x in (v.get("vote_rights_taken") or [])}


def _settings_kb(v):
    mode = "خودکار" if v.get("mode") == AUTO else "دستی"
    return InlineKeyboardMarkup(row_width=1).add(
        InlineKeyboardButton(
            f"⏱ زمان انتظار رای‌گیری: {v['wait_seconds']} ثانیه", callback_data="vote:wait"
        ),
        InlineKeyboardButton(
            f"⏱ زمان هر رای: {v['vote_seconds']} ثانیه", callback_data="vote:duration"
        ),
        InlineKeyboardButton(
            f"🚫 گرفتن حق رای ({len(v.get('vote_rights_taken', []))})",
            callback_data="vote:rights",
        ),
        InlineKeyboardButton(
            f"🗳 نوع رای‌گیری: {mode}", callback_data="vote:mode"
        ),
        InlineKeyboardButton("▶️ شروع رای‌گیری", callback_data="vote:start"),
    )


def _choices(prefix, values, current):
    kb = InlineKeyboardMarkup(row_width=1)
    for value in values:
        label = (
            f"{value} ثانیه"
            if isinstance(value, int)
            else ("خودکار" if value == AUTO else "دستی")
        )
        if value == current:
            label += " ✅"
        kb.add(InlineKeyboardButton(label, callback_data=f"vote:{prefix}:{value}"))
    kb.add(InlineKeyboardButton("⬅️ تنظیمات رای‌گیری", callback_data="vote:settings"))
    return kb


def _rights_kb(main, v):
    """Show ALL currently active players; rights are global to both rounds."""
    taken = _active_rights(v)
    kb = InlineKeyboardMarkup(row_width=1)
    for row in _players(main):
        uid = int(row["player_id"])
        label = f"🚫 {_row_name(main, row)}" + (" ✅" if uid in taken else "")
        kb.add(InlineKeyboardButton(label, callback_data=f"vote:right:{uid}"))
    kb.add(InlineKeyboardButton("⬅️ تنظیمات رای‌گیری", callback_data="vote:settings"))
    return kb


def _round2_kb(main, v):
    selected = {int(x) for x in (v.get("selected_round_two") or [])}
    kb = InlineKeyboardMarkup(row_width=1)
    for row in _players(main):
        uid = int(row["player_id"])
        kb.add(
            InlineKeyboardButton(
                _row_name(main, row) + (" ✅" if uid in selected else ""),
                callback_data=f"vote:r2pick:{uid}",
            )
        )
    kb.add(
        InlineKeyboardButton("🚫 گرفتن حق رای", callback_data="vote:rights"),
        InlineKeyboardButton("✅ تایید و شروع رای دوم", callback_data="vote:r2confirm"),
        InlineKeyboardButton("⬅️ بازگشت", callback_data="vote:settings"),
    )
    return kb


def _day_end_kb():
    return InlineKeyboardMarkup(row_width=1).add(
        InlineKeyboardButton("🗳 رای‌گیری", callback_data="vote:settings"),
        InlineKeyboardButton("🌙 شروع فاز شب", callback_data="start_night"),
    )


async def _settings(main, callback):
    v = _v(main)
    text = (
        "🗳 <b>تنظیمات رای‌گیری</b>\n\n"
        f"⏱ زمان انتظار: {v['wait_seconds']} ثانیه\n"
        f"⏱ زمان هر رای: {v['vote_seconds']} ثانیه\n"
        f"🚫 بدون حق رای: {len(v.get('vote_rights_taken', []))} نفر\n"
        f"🗳 نوع: {'خودکار' if v.get('mode') == AUTO else 'دستی'}"
    )
    await callback.message.edit_text(
        text, reply_markup=_settings_kb(v), parse_mode="HTML"
    )
    await callback.answer()


async def _start_target(main):
    v = _v(main)
    targets = list(v.get("targets") or [])
    idx = int(v.get("target_index") or 0)
    if idx >= len(targets):
        return await _finish_round(main)
    target = int(targets[idx])
    rows = {int(x["player_id"]): x for x in _players(main)}
    name = _name(main, target, rows.get(target, {}).get("seat"))
    now = time.time()
    deadline = now + int(v["vote_seconds"])
    v["phase"], v["started_at"], v["deadline"] = "voting", now, deadline
    v.setdefault("votes", {}).setdefault(str(target), [])
    _put(main, v)
    markup = (
        InlineKeyboardMarkup(row_width=1).add(
            InlineKeyboardButton("🗳 رای می‌دهم", callback_data="vote:cast")
        )
        if v.get("mode") == AUTO
        else None
    )
    await main.bot.send_message(
        _gid(main),
        f"🗳 <b>رای برای {html.escape(name)}</b>\n\n⏱ {int(v['vote_seconds'])} ثانیه فرصت دارید.",
        parse_mode="HTML",
        reply_markup=markup,
    )
    main._voting_task = asyncio.create_task(_timer(main, deadline, "voting"))


async def _timer(main, deadline, expected):
    await asyncio.sleep(max(0, float(deadline) - time.time()))
    v = _v(main)
    if v.get("phase") == expected and v.get("deadline") == deadline:
        await (_start_target(main) if expected == "waiting" else _end_target(main))


async def _start_wait(main):
    v = _v(main)
    deadline = time.time() + int(v["wait_seconds"])
    v.update(phase="waiting", started_at=time.time(), deadline=deadline, target_index=0, votes={})
    _put(main, v)
    blocked = _active_rights(v)
    names = [
        _row_name(main, r)
        for r in _players(main)
        if int(r["player_id"]) in blocked
    ]
    blocked_text = "\n".join(f"• {html.escape(x)}" for x in names) if names else "• هیچ‌کس"
    await main.bot.send_message(
        _gid(main),
        f"🗳 <b>رای‌گیری پس از {int(v['wait_seconds'])} ثانیه شروع می‌شود.</b>\n"
        f"برای رای به هر بازیکن {int(v['vote_seconds'])} ثانیه فرصت دارید.\n\n"
        f"🚫 <b>بازیکنانی که حق رای ندارند:</b>\n{blocked_text}",
        parse_mode="HTML",
    )
    main._voting_task = asyncio.create_task(_timer(main, deadline, "waiting"))


async def _end_target(main):
    v = _v(main)
    targets = list(v.get("targets") or [])
    idx = int(v.get("target_index") or 0)
    if idx >= len(targets):
        return await _finish_round(main)
    target = int(targets[idx])
    voted = {
        int(x) for x in (v.get("votes") or {}).get(str(target), [])
    }
    rows = {int(x["player_id"]): x for x in _players(main)}
    target_name = _name(main, target, rows.get(target, {}).get("seat"))
    voter_text = (
        "\n".join(
            f"• {html.escape(_name(main, uid, rows.get(uid, {}).get('seat')))}"
            for uid in voted
        )
        or "• هیچ‌کس"
    )
    await main.bot.send_message(
        _gid(main),
        f"📊 <b>نتیجه رای‌گیری برای {html.escape(target_name)}</b>\n\n"
        f"🗳 تعداد رای: <b>{len(voted)}</b>\n👥 رای‌دهندگان:\n{voter_text}",
        parse_mode="HTML",
    )
    v["target_index"], v["started_at"], v["deadline"] = idx + 1, None, None
    _put(main, v)
    await _start_target(main)


async def _finish_round(main):
    v = _v(main)
    v["phase"], v["deadline"] = "round_finished", None
    _put(main, v)
    await main.bot.send_message(
        _gid(main),
        f"✅ رای‌گیری دور {int(v.get('round') or 1)} به پایان رسید.",
        reply_markup=InlineKeyboardMarkup(row_width=1).add(
            InlineKeyboardButton("🔄 شروع رای دوم", callback_data="vote:round2"),
            InlineKeyboardButton("🌙 پایان رای‌گیری", callback_data="vote:end"),
        ),
    )


async def _round2(main, callback):
    v = _v(main)
    await callback.message.edit_text(
        "🔄 <b>بازیکنان رای دوم را انتخاب کنید.</b>\n\n"
        "انتخاب هدف‌های دور دوم مستقل از حق رای است. برای گرفتن حق رای از «🚫 گرفتن حق رای» استفاده کنید؛ این فهرست شامل همه بازیکنان حاضر است.",
        reply_markup=_round2_kb(main, v),
        parse_mode="HTML",
    )
    await callback.answer()


def install(main):
    if getattr(main, "_voting_runtime_installed", False):
        return False
    dp = getattr(main, "dp", None)
    if dp is None:
        return False

    async def only_mod(c):
        if int(c.from_user.id) != int(getattr(main, "moderator_id", -1) or -1):
            await c.answer("⛔ فقط گرداننده دسترسی دارد.", show_alert=True)
            raise CancelHandler()

    async def settings(c):
        await only_mod(c)
        await _settings(main, c)

    async def wait_menu(c):
        await only_mod(c)
        v = _v(main)
        await c.message.edit_text(
            "⏱ <b>زمان انتظار رای‌گیری</b>",
            reply_markup=_choices("wait", WAIT_OPTIONS, v["wait_seconds"]),
            parse_mode="HTML",
        )
        await c.answer()

    async def duration_menu(c):
        await only_mod(c)
        v = _v(main)
        await c.message.edit_text(
            "⏱ <b>زمان هر رای</b>",
            reply_markup=_choices("duration", VOTE_OPTIONS, v["vote_seconds"]),
            parse_mode="HTML",
        )
        await c.answer()

    async def choose_wait(c):
        await only_mod(c)
        v = _v(main)
        v["wait_seconds"] = int(c.data.rsplit(":", 1)[1])
        _put(main, v)
        await _settings(main, c)

    async def choose_duration(c):
        await only_mod(c)
        v = _v(main)
        v["vote_seconds"] = int(c.data.rsplit(":", 1)[1])
        _put(main, v)
        await _settings(main, c)

    async def rights(c):
        await only_mod(c)
        v = _v(main)
        await c.message.edit_text(
            "🚫 <b>گرفتن حق رای</b>\n\n"
            "این فهرست همه بازیکنان حاضر در بازی را نشان می‌دهد. حق رای یک وضعیت مشترک برای هر دو دور است.",
            reply_markup=_rights_kb(main, v),
            parse_mode="HTML",
        )
        await c.answer()

    async def toggle_right(c):
        await only_mod(c)
        v = _v(main)
        uid = int(c.data.rsplit(":", 1)[1])
        player_ids = {int(x["player_id"]) for x in _players(main)}
        if uid not in player_ids:
            await c.answer("⚠️ این بازیکن دیگر در بازی حاضر نیست.", show_alert=True)
            raise CancelHandler()
        s = _active_rights(v)
        s.symmetric_difference_update({uid})
        v["vote_rights_taken"] = sorted(s)
        _put(main, v)
        await rights(c)

    async def mode(c):
        await only_mod(c)
        v = _v(main)
        await c.message.edit_text(
            "🗳 <b>نوع رای‌گیری</b>",
            reply_markup=_choices("mode", (AUTO, MANUAL), v.get("mode")),
            parse_mode="HTML",
        )
        await c.answer()

    async def choose_mode(c):
        await only_mod(c)
        v = _v(main)
        v["mode"] = c.data.rsplit(":", 1)[1]
        _put(main, v)
        await _settings(main, c)

    async def start(c):
        await only_mod(c)
        v = _v(main)
        if v.get("phase") in {"waiting", "voting"}:
            await c.answer("⚠️ رای‌گیری در حال اجراست.", show_alert=True)
            raise CancelHandler()
        saved = {
            k: v.get(k)
            for k in ("wait_seconds", "vote_seconds", "mode", "vote_rights_taken", "selected_round_two")
        }
        fresh = _default(main)
        fresh.update(saved)
        fresh["targets"] = [int(x["player_id"]) for x in _players(main)]
        _put(main, fresh)
        rt, gid = _rt(main), _gid(main)
        if rt and gid:
            try:
                rt.days.set_phase(gid, "voting", extra={"voting": fresh})
            except Exception:
                pass
        await c.answer("🗳 رای‌گیری آماده شد.")
        await _start_wait(main)
        raise CancelHandler()

    async def cast(c):
        v = _v(main)
        if v.get("phase") != "voting":
            await c.answer("⚠️ رای‌گیری فعال نیست.", show_alert=True)
            raise CancelHandler()
        voter = int(c.from_user.id)
        players = {int(x["player_id"]): x for x in _players(main)}
        if voter not in players:
            await c.answer("⛔ شما بازیکن این بازی نیستید.", show_alert=True)
            raise CancelHandler()
        if voter in _active_rights(v):
            await c.answer("🚫 حق رای شما گرفته شده است.", show_alert=True)
            raise CancelHandler()
        targets = v.get("targets") or []
        idx = int(v.get("target_index") or 0)
        if idx >= len(targets):
            await c.answer("⚠️ این رای‌گیری تمام شده است.", show_alert=True)
            raise CancelHandler()
        target = int(targets[idx])
        votes = v.setdefault("votes", {})
        bucket = {int(x) for x in votes.setdefault(str(target), [])}
        if voter in bucket:
            await c.answer("⚠️ رای شما قبلاً ثبت شده است.", show_alert=True)
            raise CancelHandler()
        bucket.add(voter)
        votes[str(target)] = sorted(bucket)
        _put(main, v)
        await c.answer("✅ رای شما ثبت شد.")
        raise CancelHandler()

    async def r2pick(c):
        await only_mod(c)
        v = _v(main)
        uid = int(c.data.rsplit(":", 1)[1])
        player_ids = {int(x["player_id"]) for x in _players(main)}
        if uid not in player_ids:
            await c.answer("⚠️ این بازیکن دیگر در بازی حاضر نیست.", show_alert=True)
            raise CancelHandler()
        s = {int(x) for x in v.get("selected_round_two", [])}
        s.symmetric_difference_update({uid})
        v["selected_round_two"] = sorted(s)
        _put(main, v)
        await _round2(main, c)

    async def r2confirm(c):
        await only_mod(c)
        v = _v(main)
        selected = [int(x) for x in v.get("selected_round_two", [])]
        if not selected:
            await c.answer("⚠️ حداقل یک بازیکن انتخاب کنید.", show_alert=True)
            raise CancelHandler()
        # No second rights list: the shared rights state is carried forward unchanged.
        v.update(
            round=2,
            targets=selected,
            target_index=0,
            votes={},
            phase="waiting",
            started_at=None,
            deadline=None,
        )
        _put(main, v)
        await c.answer("🔄 رای دوم آماده شد.")
        await _start_wait(main)
        raise CancelHandler()

    async def end(c):
        await only_mod(c)
        v = _v(main)
        v["phase"], v["deadline"] = "finished", None
        _put(main, v)
        await c.message.edit_text(
            "🛡 <b>هیچ بازیکنی وارد دفاع نمی‌شود.</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(row_width=1).add(
                InlineKeyboardButton("🌙 ورود به فاز شب", callback_data="vote:night")
            ),
        )
        await c.answer()

    async def night(c):
        await only_mod(c)
        rt, gid = _rt(main), _gid(main)
        if rt and gid:
            try:
                rt.days.start_night(gid, extra={"voting": _v(main)})
            except Exception:
                pass
        await c.answer("🌙 فاز شب شروع شد.")
        raise CancelHandler()

    pairs = [
        (settings, lambda c: c.data == "vote:settings"),
        (wait_menu, lambda c: c.data == "vote:wait"),
        (duration_menu, lambda c: c.data == "vote:duration"),
        (choose_wait, lambda c: str(c.data or "").startswith("vote:wait:")),
        (choose_duration, lambda c: str(c.data or "").startswith("vote:duration:")),
        (rights, lambda c: c.data == "vote:rights"),
        (toggle_right, lambda c: str(c.data or "").startswith("vote:right:")),
        (mode, lambda c: c.data == "vote:mode"),
        (choose_mode, lambda c: str(c.data or "").startswith("vote:mode:")),
        (start, lambda c: c.data == "vote:start"),
        (cast, lambda c: c.data == "vote:cast"),
        (lambda c: _round2(main, c), lambda c: c.data == "vote:round2"),
        (r2pick, lambda c: str(c.data or "").startswith("vote:r2pick:")),
        (r2confirm, lambda c: c.data == "vote:r2confirm"),
        (end, lambda c: c.data == "vote:end"),
        (night, lambda c: c.data == "vote:night"),
    ]
    for fn, predicate in pairs:
        dp.register_callback_query_handler(fn, predicate, state="*")

    import runtime.stable_round_engine as stable

    if not getattr(stable, "_voting_end_day_wrapped", False):
        async def end_day_with_voting(engine_main):
            if getattr(engine_main, "_stable_day_ended", False):
                return
            engine_main._stable_day_ended = True
            engine_main._stable_day_active = False
            engine_main._stable_phase = "ended"
            engine_main._gm_extra_turn_active = False
            engine_main._gm_extra_phase = False
            task = getattr(engine_main, "turn_timer_task", None)
            if task and not task.done():
                task.cancel()
            engine_main.turn_timer_task = None
            engine_main.challenge_mode = False
            engine_main.pending_challenges = {}
            engine_main.active_challenger_seats = set()
            engine_main.current_turn_index = len(getattr(engine_main, "turn_order", []) or [])
            gid = _gid(engine_main)
            mid = getattr(engine_main, "current_turn_message_id", None)
            if gid and mid:
                try:
                    await engine_main.bot.delete_message(gid, int(mid))
                except Exception:
                    pass
            engine_main.current_turn_message_id = None
            rt = _rt(engine_main)
            if rt and gid:
                try:
                    rt.days.set_phase(gid, "day_end")
                except Exception:
                    pass
            await engine_main.bot.send_message(
                gid,
                "✅ همه بازیکنا صحبت کردن. فاز روز تموم شد.",
                reply_markup=_day_end_kb(),
            )

        stable._end_day = end_day_with_voting
        stable._voting_end_day_wrapped = True

    main._voting_runtime_installed = True
    return True
