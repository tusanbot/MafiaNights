"""Canonical voting engine for MafiaNights.

Votes are persisted independently from game JSON state. Automatic timers are
deadline based and are advanced by a short Supabase Cron tick, so webhook
requests never sleep and Telegram callback queries are answered promptly.
"""
from __future__ import annotations

import html
import logging
import math
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from aiogram.dispatcher.handler import CancelHandler
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from repositories.voting_repository import VotingRepository

WAIT_OPTIONS = (10, 20, 30)
VOTE_OPTIONS = (10, 20, 30)
AUTO, MANUAL = "auto", "manual"

_VOTES = VotingRepository()
_VOTE_CACHE = {}


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
    if not rt or gid is None:
        return None
    return rt.state.active_game(gid)


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
                dict(x) for x in rt.state.games.list_players(game["id"])
                if str(x.get("status") or "active") not in {"dead", "removed"}
            ]
        except Exception:
            pass
    return [{"seat": int(s), "player_id": int(uid)}
            for s, uid in sorted((getattr(main, "player_slots", {}) or {}).items())]


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
    return row.get("nickname") or row.get("first_name") or _name(main, row["player_id"], row.get("seat"))


def _timestamp():
    return datetime.now(timezone.utc)


def _display_time(value):
    try:
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.astimezone(ZoneInfo("Asia/Tehran")).strftime("%H:%M:%S.%f")[:-4]
    except Exception:
        return "نامشخص"


def _default(main, round_no=1):
    return {
        "round": int(round_no),
        "wait_seconds": 20,
        "vote_seconds": 20,
        "mode": AUTO,
        "vote_rights_taken": [],
        "targets": [int(x["player_id"]) for x in _players(main)],
        "target_index": 0,
        "started_at": None,
        "deadline": None,
        "phase": "settings",
        "selected_round_two": [],
        "round2_targets": [],
        "eligible_voters": [],
        "vote_message_id": None,
        "target_vote_ended": False,
        "defense_threshold": None,
        "defense_candidates": [],
    }


def _cache_key(main):
    game = _game(main)
    return str(game.get("id")) if game else None


def _v(main):
    # Never treat process-local cache as authoritative. Webhook callbacks and
    # cron ticks can run on different Vercel workers; every transition must
    # begin from the durable game state.
    key = _cache_key(main)
    payload = _state(main)
    voting = payload.get("voting")
    if not isinstance(voting, dict):
        voting = _default(main)
        payload["voting"] = voting
        _save(main, payload)
    if "vote_rights_taken" not in voting:
        voting["vote_rights_taken"] = list(voting.get("round_two_vote_rights_taken") or [])
    voting.pop("round_two_vote_rights_taken", None)
    voting.setdefault("round2_targets", list(voting.get("selected_round_two") or []))
    if key:
        _VOTE_CACHE[key] = dict(voting)
    return voting


def _put_memory(main, voting):
    key = _cache_key(main)
    if key:
        _VOTE_CACHE[key] = voting
    return voting


def _persist(main, voting):
    payload = _state(main)
    payload["voting"] = voting
    return _save(main, payload)


def _put(main, voting):
    _put_memory(main, voting)
    try:
        return _persist(main, voting)
    except Exception:
        logging.exception("VOTE STATE PERSIST FAILED game=%s phase=%s", _gid(main), voting.get("phase"))
        return False


def _active_rights(v):
    return {int(x) for x in (v.get("vote_rights_taken") or [])}


def _scenario(main):
    game = _game(main)
    if not game:
        return {}
    repo = getattr(getattr(_rt(main), "state", None), "scenarios", None)
    scenario_id = game.get("scenario_id")
    try:
        return dict((repo.get_by_id(scenario_id) if repo and scenario_id else None) or {})
    except Exception:
        return {}


def _rules(main):
    config = _scenario(main).get("config") or {}
    voting = config.get("voting") if isinstance(config, dict) else {}
    voting = voting if isinstance(voting, dict) else {}
    r1, r2 = voting.get("round_1") or {}, voting.get("round_2") or {}
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
    kind, n = str(spec.get("type") or "ceil_half").lower(), int(player_count)
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
            return max(1, math.ceil(n * float(spec.get("value")) / 100))
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
                return list(candidates)[:max(0, int(rule.get("value")))]
            except Exception:
                return list(candidates)
        if kind in {"floor_half", "ceil_half"}:
            count = player_count // 2 if kind == "floor_half" else math.ceil(player_count / 2)
            return list(candidates)[:max(0, int(count))]
    try:
        return list(candidates)[:max(0, int(rule))]
    except Exception:
        return list(candidates)


def _round1_voters(main, v):
    return {int(x["player_id"]) for x in _players(main)} - _active_rights(v)


def _round2_voters(main, v, rules):
    voters = _round1_voters(main, v)
    if not bool((rules.get("r2") or {}).get("defenders_can_vote", True)):
        voters -= {int(x) for x in (v.get("round2_targets") or v.get("selected_round_two") or [])}
    return voters


def _current_voters(main, v):
    return _round2_voters(main, v, _rules(main)) if int(v.get("round") or 1) == 2 else _round1_voters(main, v)


async def _resolve_name(main, uid, seat=None):
    value = _name(main, uid, seat)
    if value and not str(value).startswith("بازیکن "):
        return str(value)
    gid = _gid(main)
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
    return {int(x["player_id"]): x for x in _players(main)}


def _settings_kb(v):
    mode = "خودکار" if v.get("mode") == AUTO else "دستی"
    return InlineKeyboardMarkup(row_width=1).add(
        InlineKeyboardButton(f"⏱ زمان انتظار رای‌گیری: {int(v.get('wait_seconds', 20))} ثانیه", callback_data="vote:wait"),
        InlineKeyboardButton(f"⏱ زمان هر رای: {int(v.get('vote_seconds', 20))} ثانیه", callback_data="vote:duration"),
        InlineKeyboardButton(f"🚫 گرفتن حق رای ({len(v.get('vote_rights_taken', []))})", callback_data="vote:rights"),
        InlineKeyboardButton(f"🗳 نوع رای‌گیری: {mode}", callback_data="vote:mode"),
        InlineKeyboardButton("▶️ شروع رای‌گیری", callback_data="vote:start"),
    )


def _choices(prefix, values, current):
    kb = InlineKeyboardMarkup(row_width=1)
    for value in values:
        label = f"{value} ثانیه" if isinstance(value, int) else ("خودکار" if value == AUTO else "دستی")
        if value == current:
            label += " ✅"
        kb.add(InlineKeyboardButton(label, callback_data=f"vote:{prefix}:{value}"))
    kb.add(InlineKeyboardButton("⬅️ تنظیمات رای‌گیری", callback_data="vote:settings"))
    return kb


def _rights_kb(main, v):
    taken = _active_rights(v)
    kb = InlineKeyboardMarkup(row_width=1)
    for row in _players(main):
        uid = int(row["player_id"])
        kb.add(InlineKeyboardButton(f"🚫 {_row_name(main, row)}" + (" ✅" if uid in taken else ""), callback_data=f"vote:right:{uid}"))
    kb.add(InlineKeyboardButton("⬅️ تنظیمات رای‌گیری", callback_data="vote:settings"))
    return kb


def _manual_start_kb():
    return InlineKeyboardMarkup(row_width=1).add(
        InlineKeyboardButton("▶️ شروع رای‌گیری", callback_data="vote:manual_start")
    )


def _manual_next_kb(last=False):
    kb = InlineKeyboardMarkup(row_width=1).add(InlineKeyboardButton("🗳 رای می‌دهم", callback_data="vote:cast"))
    kb.add(InlineKeyboardButton("🏁 اتمام رای‌گیری" if last else "➡️ بعدی", callback_data="vote:manual_end" if last else "vote:manual_next"))
    return kb


def _disabled_vote_kb():
    return InlineKeyboardMarkup(row_width=1).add(InlineKeyboardButton("✅ زمان رأی‌گیری پایان یافت", callback_data="vote:noop"))


def _vote_message_text(main, v, target):
    game = _game(main)
    if not game:
        return "🗳 رأی‌گیری فعال نیست."
    round_no = int(v.get("round") or 1)
    local_votes = [
        dict(x) for x in (v.get("votes") or [])
        if int(x.get("round") or 0) == round_no and int(x.get("target_player_id") or 0) == int(target)
    ]
    try:
        records = local_votes or _VOTES.list_target(game["id"], round_no, int(target))
    except Exception:
        logging.exception("VOTE LIST FAILED game=%s round=%s target=%s", game["id"], round_no, target)
        records = local_votes
    rows = _row_map(main)
    target_name = _name(main, target, rows.get(int(target), {}).get("seat"))
    voters = "• هنوز رایی ثبت نشده"
    if records:
        voters = "\n".join(
            f"• {html.escape(_name(main, int(row['voter_player_id']), rows.get(int(row['voter_player_id']), {}).get('seat')))} — ⏱ {_display_time(row['voted_at'])}"
            for row in records
        )
    timing = "⏱ <b>زمان رأی‌گیری پایان یافت.</b>" if v.get("target_vote_ended") else f"⏱ {int(v.get('vote_seconds', 20))} ثانیه فرصت دارید."
    return f"🗳 <b>رأی برای {html.escape(target_name)}</b>\n\n👥 تعداد رأی ثبت‌شده: <b>{len(records)}</b>\n🗳 <b>رأی‌دهندگان:</b>\n{voters}\n\n{timing}"


async def _edit_vote_message(main, v, target, closed=False):
    mid = v.get("vote_message_id")
    if not mid:
        return
    last = int(v.get("target_index") or 0) >= len(v.get("targets") or []) - 1
    markup = _disabled_vote_kb() if closed else (_manual_next_kb(last) if v.get("mode") == MANUAL else InlineKeyboardMarkup(row_width=1).add(InlineKeyboardButton("🗳 رای می‌دهم", callback_data="vote:cast")))
    try:
        await main.bot.edit_message_text(_vote_message_text(main, v, target), chat_id=_gid(main), message_id=int(mid), parse_mode="HTML", reply_markup=markup)
    except Exception:
        logging.exception("VOTE MESSAGE UPDATE FAILED game=%s message=%s", _gid(main), mid)


async def _start_target(main):
    v = _v(main)
    targets = [int(x) for x in (v.get("targets") or [])]
    idx = int(v.get("target_index") or 0)
    if idx >= len(targets):
        return await _finish_round(main)
    target = targets[idx]
    now = time.time()
    v.update(
        phase="voting",
        started_at=now,
        deadline=None if v.get("mode") == MANUAL else now + int(v.get("vote_seconds", 20)),
        target_vote_ended=False,
        vote_message_id=None,
        votes=[],
        eligible_voters=sorted(_current_voters(main, v)),
    )
    _put(main, v)
    markup = _manual_next_kb(idx >= len(targets) - 1) if v.get("mode") == MANUAL else InlineKeyboardMarkup(row_width=1).add(InlineKeyboardButton("🗳 رای می‌دهم", callback_data="vote:cast"))
    sent = await main.bot.send_message(_gid(main), _vote_message_text(main, v, target), parse_mode="HTML", reply_markup=markup)
    v["vote_message_id"] = int(sent.message_id)
    _put(main, v)
    logging.info("VOTE TARGET START game=%s round=%s index=%s target=%s mode=%s deadline=%s", _gid(main), int(v.get("round") or 1), idx, target, v.get("mode"), v.get("deadline"))


async def _start_wait(main):
    v = _v(main)
    round_no = int(v.get("round") or 1)
    v.update(target_index=0, deadline=None, started_at=None, target_vote_ended=False, vote_message_id=None, votes=[], eligible_voters=sorted(_current_voters(main, v)))
    game = _game(main)
    if game:
        _VOTES.clear_round(game["id"], round_no)
    if v.get("mode") == MANUAL:
        v["phase"] = "manual_ready"
        _put(main, v)
        await main.bot.send_message(_gid(main), "🗳 <b>شروع رای‌گیری</b>\n\nرای‌گیری دستی آماده است. با زدن دکمه زیر توسط گرداننده، رای‌گیری نفر اول شروع می‌شود.", parse_mode="HTML", reply_markup=_manual_start_kb())
        return
    now = time.time()
    v.update(phase="waiting", started_at=now, deadline=now + int(v.get("wait_seconds", 20)))
    _put(main, v)
    blocked = _active_rights(v)
    rows = _row_map(main)
    blocked_text = "\n".join(f"• {html.escape(_row_name(main, rows[uid]))}" for uid in sorted(blocked) if uid in rows) or "• هیچ‌کس"
    await main.bot.send_message(_gid(main), f"🗳 <b>رأی‌گیری دور {round_no} پس از {int(v['wait_seconds'])} ثانیه شروع می‌شود.</b>\nبرای هر هدف {int(v['vote_seconds'])} ثانیه فرصت دارید.\n\n🚫 <b>بازیکنانی که حق رای ندارند:</b>\n{blocked_text}", parse_mode="HTML")
    logging.info("VOTE WAIT START game=%s round=%s deadline=%s", _gid(main), round_no, v["deadline"])


async def _close_target(main):
    v = _v(main)
    if v.get("phase") != "voting" or v.get("target_vote_ended"):
        logging.info("VOTE CLOSE SKIPPED game=%s phase=%s ended=%s", _gid(main), v.get("phase"), v.get("target_vote_ended"))
        return
    v["phase"] = "closing"
    v["target_vote_ended"] = True
    # Persist the closing marker before any Telegram edit/send. This makes the
    # transition visible to another cron worker and prevents duplicate
    # close/start-next races.
    if not _put(main, v):
        logging.warning("VOTE CLOSE STATE PERSIST FAILED game=%s round=%s index=%s", _gid(main), v.get("round"), v.get("target_index"))
    targets = [int(x) for x in (v.get("targets") or [])]
    idx = int(v.get("target_index") or 0)
    if idx >= len(targets):
        return await _finish_round(main)
    target = targets[idx]
    await _edit_vote_message(main, v, target, closed=True)
    v.update(target_index=idx + 1, started_at=None, deadline=None, vote_message_id=None)
    _put(main, v)
    if idx + 1 < len(targets):
        await _start_target(main)
    else:
        await _finish_round(main)


async def _finish_round(main):
    v = _v(main)
    if v.get("phase") == "round_finished":
        logging.info("VOTE FINISH SKIPPED game=%s already finished", _gid(main))
        return
    round_no = int(v.get("round") or 1)
    v.update(phase="round_finished", deadline=None, vote_message_id=None)
    _put_memory(main, v)
    if round_no == 1 and _game(main):
        rules = _rules(main)
        threshold = _threshold(rules, len(_players(main)))
        counts = _VOTES.counts(_game(main)["id"], round_no)
        v.update(
            defense_threshold=threshold,
            defense_candidates=[int(x) for x in (v.get("targets") or []) if counts.get(int(x), 0) >= int(threshold or 0)],
            selected_round_two=[],
            round2_targets=[],
        )
    _put(main, v)
    if round_no == 1:
        candidates = [int(x) for x in (v.get("defense_candidates") or [])]
        if candidates:
            rows = _row_map(main)
            lines = "\n".join(f"• {html.escape(_name(main, uid, rows.get(uid, {}).get('seat')))}" for uid in candidates)
            text = f"✅ <b>رأی‌گیری دور ۱ به پایان رسید.</b>\n\nحدنصاب: <b>{int(v.get('defense_threshold') or 0)}</b> رأی\n🛡 <b>واجدین شرایط دفاع:</b>\n{lines}"
            kb = InlineKeyboardMarkup(row_width=1).add(InlineKeyboardButton("🔄 شروع رای دوم", callback_data="vote:round2"), InlineKeyboardButton("🌌 شروع فاز شب", callback_data="start_night"), InlineKeyboardButton("🏁 اتمام بازی", callback_data="end_game"))
        else:
            text = "✅ <b>رأی‌گیری دور ۱ به پایان رسید.</b>\n\n🛡 هیچ بازیکنی به حدنصاب دفاع نرسید."
            kb = InlineKeyboardMarkup(row_width=1).add(InlineKeyboardButton("🌌 شروع فاز شب", callback_data="start_night"), InlineKeyboardButton("🏁 اتمام بازی", callback_data="end_game"))
    else:
        text = "🏁 <b>رأی‌گیری دور ۲ به پایان رسید.</b>\n\nمرحله بعد را انتخاب کنید."
        kb = InlineKeyboardMarkup(row_width=1).add(InlineKeyboardButton("🌌 شروع فاز شب", callback_data="start_night"), InlineKeyboardButton("🏁 اتمام بازی", callback_data="end_game"))
    await main.bot.send_message(_gid(main), text, parse_mode="HTML", reply_markup=kb)


async def _round2_message(main, callback=None):
    v = _v(main)
    rules = _rules(main)
    candidates = [int(x) for x in (v.get("defense_candidates") or [])]
    if not candidates:
        text = "🛡 <b>هیچ بازیکنی به حدنصاب دفاع نرسیده است.</b>"
        kb = InlineKeyboardMarkup(row_width=1).add(InlineKeyboardButton("🌌 شروع فاز شب", callback_data="start_night"), InlineKeyboardButton("🏁 اتمام بازی", callback_data="end_game"))
    elif _round2_mode(rules) == "automatic":
        selected = _round2_targets_automatic(rules, candidates, len(_players(main)))
        v.update(round=2, round2_targets=selected, selected_round_two=selected, phase="round2_settings", eligible_voters=sorted(_round2_voters(main, v, rules)))
        _put(main, v)
        return await _round2_settings(main, callback)
    else:
        selected = {int(x) for x in (v.get("round2_targets") or v.get("selected_round_two") or [])}
        kb = InlineKeyboardMarkup(row_width=1)
        rows = _row_map(main)
        for uid in candidates:
            name = await _resolve_name(main, uid, rows.get(uid, {}).get("seat"))
            kb.add(InlineKeyboardButton(f"{name}" + (" ✅" if uid in selected else ""), callback_data=f"vote:r2pick:{uid}"))
        kb.add(InlineKeyboardButton("🚫 گرفتن حق رای", callback_data="vote:rights"))
        kb.add(InlineKeyboardButton("✅ تایید بازیکنان دفاع", callback_data="vote:r2confirm"))
        kb.add(InlineKeyboardButton("⬅️ بازگشت", callback_data="vote:r2back"))
        text = "🔄 <b>انتخاب بازیکنان دفاع دور ۲</b>\n\nفقط بازیکنانی که در دور ۱ به حدنصاب رسیده‌اند در این فهرست هستند.\nانتخاب هدف‌های دور ۲ مستقل از حق رأی است."
    if callback is not None:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    else:
        await main.bot.send_message(_gid(main), text, reply_markup=kb, parse_mode="HTML")


async def _round2_settings(main, callback=None):
    v = _v(main)
    rules = _rules(main)
    targets = [int(x) for x in (v.get("round2_targets") or v.get("selected_round_two") or [])]
    voters = _round2_voters(main, v, rules)
    rows = _row_map(main)
    target_names = "\n".join(f"• {html.escape(_name(main, uid, rows.get(uid, {}).get('seat')))}" for uid in targets) or "• هیچ‌کس"
    voter_names = "\n".join(f"• {html.escape(_name(main, uid, rows.get(uid, {}).get('seat')))}" for uid in sorted(voters)) or "• هیچ‌کس"
    defenders_vote = "دارند" if bool((rules.get("r2") or {}).get("defenders_can_vote", True)) else "ندارند"
    text = f"⚙️ <b>تنظیمات رأی‌گیری دور ۲</b>\n\n🛡 <b>هدف‌های دور ۲:</b>\n{target_names}\n\n🗳 <b>رأی‌دهندگان دور ۲:</b> {len(voters)} نفر\n{voter_names}\n\n👤 بازیکنان داخل دفاع حق رأی {defenders_vote}.\n⏱ زمان انتظار: {int(v.get('wait_seconds', 20))} ثانیه\n⏱ زمان هر رأی: {int(v.get('vote_seconds', 20))} ثانیه"
    kb = InlineKeyboardMarkup(row_width=1).add(InlineKeyboardButton(f"⏱ زمان انتظار: {int(v.get('wait_seconds', 20))} ثانیه", callback_data="vote:wait"), InlineKeyboardButton(f"⏱ زمان هر رأی: {int(v.get('vote_seconds', 20))} ثانیه", callback_data="vote:duration"), InlineKeyboardButton("▶️ شروع رأی‌گیری دور ۲", callback_data="vote:start"), InlineKeyboardButton("⬅️ بازگشت به انتخاب دفاع", callback_data="vote:round2"))
    if callback is not None:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    else:
        await main.bot.send_message(_gid(main), text, reply_markup=kb, parse_mode="HTML")


async def _settings(main, callback):
    v = _v(main)
    if int(v.get("round") or 1) == 2 and v.get("phase") == "round2_settings":
        await _round2_settings(main, callback)
        return
    text = f"🗳 <b>تنظیمات رأی‌گیری دور ۱</b>\n\n⏱ زمان انتظار: {int(v.get('wait_seconds', 20))} ثانیه\n⏱ زمان هر رأی: {int(v.get('vote_seconds', 20))} ثانیه\n🚫 بدون حق رأی: {len(v.get('vote_rights_taken', []))} نفر\n🗳 نوع رأی‌گیری: {'خودکار' if v.get('mode') == AUTO else 'دستی'}"
    await callback.message.edit_text(text, reply_markup=_settings_kb(v), parse_mode="HTML")


def _is_mod(main, callback):
    try:
        game = _game(main)
        authoritative = game.get("moderator_id") if game else None
        if authoritative is not None:
            return int(callback.from_user.id) == int(authoritative)
        # Compatibility fallback only when an older game record has no moderator.
        return int(callback.from_user.id) == int(getattr(main, "moderator_id", -1) or -1)
    except Exception:
        return False


async def _deny(callback):
    try:
        await callback.answer("⛔ فقط گرداننده دسترسی دارد.", show_alert=True)
    except Exception:
        pass
    raise CancelHandler()


async def _cast(main, callback):
    v = _v(main)
    uid = int(callback.from_user.id)
    if v.get("phase") != "voting":
        await callback.answer("⏳ زمان رأی‌گیری این هدف تمام شده است.", show_alert=True)
        raise CancelHandler()
    deadline = v.get("deadline")
    if deadline is not None and time.time() >= float(deadline):
        await _close_target(main)
        await callback.answer("⏱ زمان رأی‌گیری تمام شد.", show_alert=True)
        raise CancelHandler()
    eligible = {int(x) for x in (v.get("eligible_voters") or _current_voters(main, v))}
    if uid not in eligible:
        await callback.answer("🚫 شما در این دور حق رأی ندارید.", show_alert=True)
        raise CancelHandler()
    targets = [int(x) for x in (v.get("targets") or [])]
    idx = int(v.get("target_index") or 0)
    if idx >= len(targets):
        await callback.answer("⏳ این رأی‌گیری تمام شده است.", show_alert=True)
        raise CancelHandler()
    target = targets[idx]
    if uid == target and not _rules(main).get("self_vote", False):
        await callback.answer("🚫 نمی‌توانید به خودتان رأی بدهید.", show_alert=True)
        raise CancelHandler()
    # Answer the Telegram callback before touching the database. A slow DB connection
    # must never leave the user's button in the infinite loading state.
    try:
        await callback.answer("⏳ رأی شما ثبت شد.")
    except Exception:
        logging.exception("VOTE CALLBACK ACK FAILED game=%s voter=%s", _gid(main), uid)
    game = _game(main)
    if not game:
        raise CancelHandler()

    round_no = int(v.get("round") or 1)
    votes = [dict(x) for x in (v.get("votes") or [])]
    if any(
        int(x.get("round") or 0) == round_no
        and int(x.get("target_player_id") or 0) == target
        and int(x.get("voter_player_id") or 0) == uid
        for x in votes
    ):
        logging.info("VOTE DUPLICATE LOCAL game=%s round=%s target=%s voter=%s", _gid(main), round_no, target, uid)
        raise CancelHandler()

    record = {
        "round": round_no,
        "target_player_id": target,
        "voter_player_id": uid,
        "voted_at": _timestamp().isoformat(),
    }
    votes.append(record)
    v["votes"] = votes
    _put_memory(main, v)

    logging.info("VOTE CAST game=%s round=%s target=%s voter=%s mode=%s", _gid(main), round_no, target, uid, v.get("mode"))
    # The live message is updated before any synchronous database operation.
    await _edit_vote_message(main, v, target)

    # Persistence is best-effort and intentionally comes last. A slow DB must
    # never prevent the voter from seeing the vote immediately.
    try:
        inserted = _VOTES.cast(game["id"], round_no, target, uid, _timestamp())
        logging.info("VOTE DB PERSIST game=%s round=%s target=%s voter=%s inserted=%s", _gid(main), round_no, target, uid, inserted)
    except Exception:
        logging.exception("VOTE DB PERSIST FAILED game=%s round=%s target=%s voter=%s", _gid(main), round_no, target, uid)

    try:
        _persist(main, v)
    except Exception:
        logging.exception("VOTE STATE SAVE AFTER UI FAILED game=%s", _gid(main))
    raise CancelHandler()


async def _manual_start(main, callback):
    if not _is_mod(main, callback):
        return await _deny(callback)
    v = _v(main)
    if v.get("mode") != MANUAL or v.get("phase") != "manual_ready":
        await callback.answer("⛔ رأی‌گیری دستی آماده نیست.", show_alert=True)
        raise CancelHandler()
    await callback.answer("▶️ رأی‌گیری نفر اول شروع شد.")
    await _start_target(main)
    raise CancelHandler()


async def _manual_next(main, callback):
    if not _is_mod(main, callback):
        return await _deny(callback)
    v = _v(main)
    if v.get("mode") != MANUAL or v.get("phase") != "voting":
        await callback.answer("⛔ رأی‌گیری دستی فعال نیست.", show_alert=True)
        raise CancelHandler()
    await callback.answer("➡️ نفر بعدی")
    await _close_target(main)
    raise CancelHandler()


async def _manual_end(main, callback):
    if not _is_mod(main, callback):
        return await _deny(callback)
    v = _v(main)
    if v.get("mode") != MANUAL or v.get("phase") != "voting":
        await callback.answer("⛔ رأی‌گیری دستی فعال نیست.", show_alert=True)
        raise CancelHandler()
    await callback.answer("🏁 رأی‌گیری این دور به پایان رسید.")
    v["target_index"] = len(list(v.get("targets") or []))
    v["deadline"] = None
    v["target_vote_ended"] = True
    _put(main, v)
    await _finish_round(main)
    raise CancelHandler()


async def _round2_pick(main, callback):
    if not _is_mod(main, callback):
        return await _deny(callback)
    uid = int(str(callback.data).split(":")[-1])
    v = _v(main)
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
    _put(main, v)
    await _round2_message(main, callback)
    await callback.answer("")


async def _round2_confirm(main, callback):
    if not _is_mod(main, callback):
        return await _deny(callback)
    v = _v(main)
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
    v.update(round=2, round2_targets=selected, selected_round_two=selected, target_index=0, phase="round2_settings", deadline=None, vote_message_id=None, eligible_voters=sorted(_round2_voters(main, v, rules)))
    _put(main, v)
    game = _game(main)
    if game:
        _VOTES.clear_round(game["id"], 2)
    await callback.answer("🔄 رای دوم آماده شد.")
    await _round2_settings(main, callback)
    raise CancelHandler()


async def _start(main, callback):
    if not _is_mod(main, callback):
        return await _deny(callback)
    v = _v(main)
    if v.get("phase") in {"waiting", "voting"}:
        await callback.answer("⏳ رای‌گیری در حال اجراست.", show_alert=True)
        raise CancelHandler()
    round_no = int(v.get("round") or 1)
    if round_no == 2 and not (v.get("round2_targets") or v.get("selected_round_two")):
        await callback.answer("⛔ ابتدا بازیکنان دفاع دور ۲ را انتخاب کنید.", show_alert=True)
        raise CancelHandler()
    v.update(
        target_index=0,
        phase="settings",
        deadline=None,
        vote_message_id=None,
        targets=([int(x["player_id"]) for x in _players(main)] if round_no == 1 else [int(x) for x in (v.get("round2_targets") or v.get("selected_round_two") or [])]),
        eligible_voters=sorted(_current_voters(main, v)),
    )
    _put(main, v)
    game = _game(main)
    if game:
        _VOTES.clear_round(game["id"], round_no)
    rt, gid = _rt(main), _gid(main)
    if rt and gid:
        try:
            rt.days.set_phase(gid, "voting", extra={"voting": dict(v)})
        except Exception:
            logging.exception("VOTE set_phase failed")
    await callback.answer("🗳 رای‌گیری آماده شد.")
    await _start_wait(main)
    raise CancelHandler()


async def _set_menu(main, callback, title, prefix, values, current):
    if not _is_mod(main, callback):
        return await _deny(callback)
    await callback.message.edit_text(title, reply_markup=_choices(prefix, values, current), parse_mode="HTML")
    await callback.answer("")


async def _set_value(main, callback, field, allowed):
    if not _is_mod(main, callback):
        return await _deny(callback)
    raw = str(callback.data).split(":")[-1]
    value = raw if field == "mode" else int(raw)
    if value not in allowed:
        await callback.answer("⛔ گزینه نامعتبر است.", show_alert=True)
        raise CancelHandler()
    v = _v(main)
    v[field] = value
    _put(main, v)
    await _settings(main, callback)
    await callback.answer("")


async def _settings_handler(main, callback):
    if not _is_mod(main, callback):
        return await _deny(callback)
    await _settings(main, callback)
    await callback.answer("")


async def _round2_handler(main, callback):
    if not _is_mod(main, callback):
        return await _deny(callback)
    await _round2_message(main, callback)
    await callback.answer("")


async def _rights_handler(main, callback):
    if not _is_mod(main, callback):
        return await _deny(callback)
    await callback.message.edit_text("🚫 <b>بازیکنان بدون حق رای</b>", reply_markup=_rights_kb(main, _v(main)), parse_mode="HTML")
    await callback.answer("")


async def _right_toggle(main, callback):
    if not _is_mod(main, callback):
        return await _deny(callback)
    uid = int(str(callback.data).split(":")[-1])
    v = _v(main)
    rights = _active_rights(v)
    rights.remove(uid) if uid in rights else rights.add(uid)
    v["vote_rights_taken"] = sorted(rights)
    _put(main, v)
    await _rights_handler(main, callback)


async def _mode_handler(main, callback):
    if not _is_mod(main, callback):
        return await _deny(callback)
    await callback.message.edit_text("🗳 <b>نوع رای‌گیری</b>", reply_markup=_choices("mode", (AUTO, MANUAL), _v(main).get("mode")), parse_mode="HTML")
    await callback.answer("")


async def _end(main, callback):
    if not _is_mod(main, callback):
        return await _deny(callback)
    v = _v(main)
    v.update(phase="finished", deadline=None, vote_message_id=None)
    _put(main, v)
    await callback.message.edit_text("🏁 <b>رأی‌گیری به پایان رسید.</b>", parse_mode="HTML")
    await callback.answer("")


async def _noop(callback):
    await callback.answer("این پیام مربوط به مرحله قبلی رأی‌گیری است.")


async def handle_callback(main, callback):
    data = str(getattr(callback, "data", "") or "")
    if not data.startswith("vote:"):
        return False
    try:
        if data == "vote:settings":
            await _settings_handler(main, callback)
        elif data == "vote:wait":
            await _set_menu(main, callback, "⏱ <b>زمان انتظار را انتخاب کنید.</b>", "wait", WAIT_OPTIONS, int(_v(main).get("wait_seconds", 20)))
        elif data.startswith("vote:wait:"):
            await _set_value(main, callback, "wait_seconds", WAIT_OPTIONS)
        elif data == "vote:duration":
            await _set_menu(main, callback, "⏱ <b>زمان هر رای را انتخاب کنید.</b>", "duration", VOTE_OPTIONS, int(_v(main).get("vote_seconds", 20)))
        elif data.startswith("vote:duration:"):
            await _set_value(main, callback, "vote_seconds", VOTE_OPTIONS)
        elif data == "vote:rights":
            await _rights_handler(main, callback)
        elif data.startswith("vote:right:"):
            await _right_toggle(main, callback)
        elif data == "vote:mode":
            await _mode_handler(main, callback)
        elif data.startswith("vote:mode:"):
            await _set_value(main, callback, "mode", (AUTO, MANUAL))
        elif data == "vote:start":
            await _start(main, callback)
        elif data == "vote:manual_start":
            await _manual_start(main, callback)
        elif data == "vote:manual_next":
            await _manual_next(main, callback)
        elif data == "vote:manual_end":
            await _manual_end(main, callback)
        elif data in {"vote:cast", "vote:autocast"}:
            await _cast(main, callback)
        elif data == "vote:noop":
            await _noop(callback)
        elif data == "vote:round2":
            await _round2_handler(main, callback)
        elif data.startswith("vote:r2pick:"):
            await _round2_pick(main, callback)
        elif data in {"vote:r2confirm", "vote:r2confirm_v2"}:
            await _round2_confirm(main, callback)
        elif data in {"vote:r2back", "vote:settings_round2"}:
            await _round2_handler(main, callback)
        elif data == "vote:end":
            await _end(main, callback)
        else:
            return False
    except CancelHandler:
        pass
    except Exception:
        logging.exception("VOTE CALLBACK FAILED data=%s game=%s", data, _gid(main))
        try:
            await callback.answer("❌ خطا در پردازش رأی‌گیری.", show_alert=True)
        except Exception:
            pass
    return True


async def tick(main):
    v = _v(main)
    if v.get("mode") != AUTO:
        return False
    changed = False
    for _ in range(32):
        v = _v(main)
        phase, deadline = v.get("phase"), v.get("deadline")
        if phase not in {"waiting", "voting"} or deadline is None or time.time() < float(deadline):
            break
        if phase == "waiting":
            await _start_target(main)
        else:
            await _close_target(main)
        changed = True
    return changed


def install(main):
    if getattr(main, "_voting_runtime_installed", False):
        return False
    dp = getattr(main, "dp", None)
    if dp is None:
        return False
    async def router(callback):
        await handle_callback(main, callback)
        raise CancelHandler()
    dp.register_callback_query_handler(router, lambda c: str(c.data or "").startswith("vote:"), state="*")
    registry = getattr(getattr(dp, "callback_query_handlers", None), "handlers", None)
    if registry is not None:
        ours = [x for x in list(registry) if getattr(getattr(x, "handler", None), "__module__", "") == __name__]
        for item in reversed(ours):
            try:
                registry.remove(item)
            except ValueError:
                pass
            registry.insert(0, item)
    main._voting_runtime_installed = True
    return True
