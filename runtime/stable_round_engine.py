"""Single authoritative round/turn engine for MafiaNights.

This module intentionally owns ALL next/start/challenge transitions. It is
installed last so legacy handlers cannot compete with it. A normal day is a
finite sequence: normal speakers -> explicitly selected extra turns -> day end.
The engine never starts a new normal round from NEXT; a new day is started only
by the existing start_new_day action.
"""
from __future__ import annotations

import asyncio
import html
import logging
import time
from aiogram.dispatcher.handler import CancelHandler
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


NEXT_PREFIX = "next_"
CHALLENGE_REQUEST_PREFIX = "challenge_request_"


def _handler(item):
    return getattr(item, "handler", None)


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


def _uid(main, seat):
    try:
        return (getattr(main, "player_slots", {}) or {}).get(int(seat))
    except Exception:
        return None


def _fresh_active_game(main):
    """Read the active game without relying on the short-lived active-game cache."""
    gid = _gid(main)
    if not gid:
        return None
    try:
        cached = main.runtime.state.active_game(gid)
        if not cached:
            return None
        fresh = main.runtime.state.games.get_game(cached["id"])
        return fresh or cached
    except Exception:
        logging.exception("stable round: failed to refresh active game")
        return cached if "cached" in locals() else None



def _hydrate_runtime_players(main, game=None):
    """Rebuild process-local player/seat state from durable game rows."""
    gid = _gid(main)
    if not gid:
        return None, []
    try:
        if game is None:
            game = _fresh_active_game(main)
        else:
            try:
                game = main.runtime.state.games.get_game(game["id"]) or game
            except Exception:
                pass
        if not game:
            return None, []
        rows = [
            row for row in main.runtime.state.games.list_players(game["id"])
            if row.get("seat") is not None
            and str(row.get("status") or "active") not in {"removed", "dead", "finished", "kicked"}
        ]
        slots, players = {}, {}
        for row in rows:
            try:
                seat, uid = int(row["seat"]), int(row["player_id"])
            except (TypeError, ValueError):
                continue
            if uid:
                slots[seat] = uid
                players[uid] = str(row.get("nickname") or row.get("first_name") or row.get("username") or uid)
        main.player_slots = slots
        main.players = players
        return game, rows
    except Exception:
        logging.exception("stable round: failed to hydrate runtime players from DB")
        return game, []


def _restore_persisted_turn_state(main, game):
    """Restore durable turn order/index and discard stale process-local order."""
    state = dict((game or {}).get("state") or {})
    persisted = []
    for raw in state.get("turn_order") or []:
        try:
            persisted.append(int(raw))
        except (TypeError, ValueError):
            continue
    occupied = set((getattr(main, "player_slots", {}) or {}).keys())
    persisted = [seat for seat in persisted if seat in occupied]
    if not persisted:
        persisted = sorted(occupied)
    main.turn_order = list(persisted)
    main._stable_normal_order = list(persisted)
    main._gm_normal_order = list(persisted)
    raw_index = (game or {}).get("current_turn_index")
    if raw_index is None:
        raw_index = state.get("current_turn_index")
    try:
        idx = int(raw_index)
    except (TypeError, ValueError):
        idx = 0
    if idx < 0 or idx >= len(main.turn_order):
        idx = 0
    main.current_turn_index = idx
    # Day lifecycle flags are reset by the explicit head-selection action.
    # A historical day-ended marker must never permanently block the next day.
    main._stable_day_ended = False
    main._stable_day_active = False
    main._stable_phase = "normal"
    return list(main.turn_order), idx

def _seat(main, uid):
    try:
        uid = int(uid)
    except Exception:
        return None
    for seat, player_uid in (getattr(main, "player_slots", {}) or {}).items():
        try:
            if int(player_uid) == uid:
                return int(seat)
        except Exception:
            pass
    return None


def _stored_name(main, uid):
    players = getattr(main, "players", {}) or {}
    try:
        value = players.get(uid)
    except Exception:
        value = None
    if isinstance(value, dict):
        return value.get("nickname") or value.get("full_name") or value.get("first_name")
    if value and str(value).strip() not in {"?", "❓", "None", "بازیکن"}:
        return str(value)
    return None


def _display_name(main, uid, fallback=None):
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
        value = main.display_name(int(uid), fallback)
        if value and str(value).strip() not in {"?", "❓", "None", "بازیکن"}:
            return str(value)
    except Exception:
        pass
    value = _stored_name(main, uid)
    if value:
        return value
    if fallback and str(fallback).strip() not in {"?", "❓", "None", "بازیکن"}:
        return str(fallback)
    return None


async def _resolve_name(main, uid, fallback=None):
    name = _display_name(main, uid, fallback)
    if name:
        return name
    gid = _gid(main)
    if gid and uid:
        try:
            member = await main.bot.get_chat_member(gid, int(uid))
            user = getattr(member, "user", None)
            name = getattr(user, "full_name", None) or getattr(user, "first_name", None)
            if name:
                players = getattr(main, "players", None)
                if isinstance(players, dict):
                    players[int(uid)] = name
                return str(name)
        except Exception as exc:
            logging.warning("stable round: unable to hydrate name for %s: %s", uid, exc)
    return f"بازیکن {int(_seat(main, uid) or 0)}"


def _active(main):
    try:
        return int(main.turn_order[main.current_turn_index])
    except Exception:
        return None


def _ensure(main):
    defaults = {
        "_stable_day_active": False,
        "_stable_day_ended": False,
        "_stable_phase": "normal",
        "_stable_extra_seats": set(),
        "_stable_extra_used": set(),
        "_stable_normal_order": [],
        "_stable_next_lock": 0.0,
        "_stable_challenge_used": set(),
        "_stable_challenge_locked": set(),
        "_stable_challenge_requests": {},
        "_stable_challenge_request_messages": {},
        "_gm_extra_next_round": set(),
        "_gm_muted_next_round": set(),
        "_gm_muted_active": set(),
        "_gm_extra_phase": False,
        "_gm_extra_turn_active": False,
        "_gm_extra_seats": set(),
        "_gm_normal_order": [],
        "challenge_active": True,
    }
    for key, value in defaults.items():
        if not hasattr(main, key):
            setattr(main, key, value.copy() if isinstance(value, (set, list, dict)) else value)


def _base_order(main):
    occupied = set()
    for seat in (getattr(main, "player_slots", {}) or {}):
        try:
            occupied.add(int(seat))
        except Exception:
            pass
    source = list(getattr(main, "_stable_normal_order", []) or [])
    if not source:
        source = list(getattr(main, "turn_order", []) or [])
    result, seen = [], set()
    for raw in source:
        try:
            seat = int(raw)
        except Exception:
            continue
        if seat in occupied and seat not in seen:
            result.append(seat)
            seen.add(seat)
    for seat in sorted(occupied):
        if seat not in seen:
            result.append(seat)
    return result


async def _cancel_timer(main):
    task = getattr(main, "turn_timer_task", None)
    if task and not task.done():
        task.cancel()
    main.turn_timer_task = None


async def _delete_turn_message(main):
    gid = _gid(main)
    mid = getattr(main, "current_turn_message_id", None)
    if gid and mid:
        try:
            await main.bot.delete_message(gid, int(mid))
        except Exception:
            pass
    main.current_turn_message_id = None


def _keyboard(main, seat, is_challenge=False):
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton("⏭ نکست", callback_data=f"next_{int(seat)}"))
    if is_challenge or getattr(main, "_stable_phase", "normal") != "normal":
        return kb
    if not getattr(main, "challenge_active", False):
        return kb
    if int(seat) in getattr(main, "_stable_challenge_locked", set()):
        return kb
    kb.add(InlineKeyboardButton("🤏🏻 درخواست چالش", callback_data=f"challenge_request_{int(seat)}"))
    return kb


async def _start_turn(main, seat, duration=120, is_challenge=False):
    _ensure(main)
    try:
        seat = int(seat)
    except Exception:
        return None
    uid = _uid(main, seat)
    if not uid:
        logging.error("stable round: seat %s has no player", seat)
        return None
    if getattr(main, "_stable_day_ended", False) and not is_challenge:
        return None
    name = await _resolve_name(main, uid, _stored_name(main, uid))
    mention = f"<a href='tg://user?id={int(uid)}'>{html.escape(name)}</a>"
    await _cancel_timer(main)
    main.challenge_mode = bool(is_challenge)
    if is_challenge:
        main._stable_phase = "challenge"
    elif getattr(main, "_stable_phase", "normal") != "extra":
        main._stable_phase = "normal"
    prefix = "🤏🏻" if is_challenge else "🌅"
    text = f"{prefix} <b>نوبت {mention} شروع شد.</b>\n⏱ {duration//60} دقیقه می‌تونی صحبت کنی."
    try:
        game = _fresh_active_game(main)
        if game and not is_challenge:
            state = dict(game.get("state") or {})
            state["turn_order"] = [int(x) for x in main.turn_order]
            state["current_turn_index"] = int(main.current_turn_index)
            state["current_turn_seat"] = int(seat)
            main.runtime.state.games.update_game(
                game["id"],
                state=state,
                current_turn_index=int(main.current_turn_index),
                current_turn_seat=int(seat),
            )
    except Exception:
        logging.exception("stable round: failed to persist active turn before send")
    msg = await main.bot.send_message(_gid(main), text, parse_mode="HTML", reply_markup=_keyboard(main, seat, is_challenge))
    main.current_turn_message_id = msg.message_id
    if not is_challenge:
        try:
            game = main.runtime.state.active_game(_gid(main)); state = dict((game or {}).get("state") or {})
            settings = dict(state.get("challenge_settings") or {})
            if bool(settings.get("enabled", getattr(main,"challenge_active",True))):
                stats = dict(state.get("challenge_score_stats") or {})
                stats["eligible_turns"] = int(stats.get("eligible_turns") or 0) + 1
                state["challenge_score_stats"] = stats
                main.runtime.state.games.update_game(game["id"], state=state)
        except Exception: logging.exception("stable challenge: failed to record eligible speaking turn")
    countdown = getattr(main, "countdown", None)
    if countdown:
        main.turn_timer_task = asyncio.create_task(countdown(seat, duration, msg.message_id, is_challenge))
    return msg.message_id


async def _start_extra(main, seat):
    _ensure(main)
    uid = _uid(main, seat)
    if not uid or seat in main._stable_extra_used:
        return await _advance(main)
    main._stable_extra_used.add(int(seat))
    main._stable_phase = "extra"
    name = await _resolve_name(main, uid, _stored_name(main, uid))
    mention = f"<a href='tg://user?id={int(uid)}'>{html.escape(name)}</a>"
    await _cancel_timer(main)
    main._gm_extra_turn_active = True
    main.challenge_mode = False
    msg = await main.bot.send_message(
        _gid(main),
        f"➕ <b>ترن اضافه</b>\n🎙 نوبت اضافه {mention} است.\n🚫 این ترن امکان چالش ندارد.",
        parse_mode="HTML",
        reply_markup=_keyboard(main, seat, True),
    )
    main.current_turn_message_id = msg.message_id
    countdown = getattr(main, "countdown", None)
    if countdown:
        main.turn_timer_task = asyncio.create_task(countdown(seat, 120, msg.message_id, False))
    return msg.message_id


async def _end_day(main):
    _ensure(main)
    if main._stable_day_ended:
        return
    main._stable_day_ended = True
    main._stable_day_active = False
    main._stable_phase = "ended"
    main._gm_extra_turn_active = False
    main._gm_extra_phase = False
    await _cancel_timer(main)
    await _delete_turn_message(main)
    main.challenge_mode = False
    main.pending_challenges = {}
    main.active_challenger_seats = set()
    main.current_turn_index = len(getattr(main, "turn_order", []) or [])
    gid = _gid(main)
    if gid:
        try:
            game = _fresh_active_game(main)
            if game:
                state = dict(game.get("state") or {})
                state["turn_order"] = [int(x) for x in (getattr(main, "turn_order", []) or [])]
                state["current_turn_index"] = int(main.current_turn_index)
                state["current_turn_seat"] = None
                state["stable_day_active"] = False
                state["stable_day_ended"] = True
                main.runtime.state.games.update_game(
                    game["id"],
                    state=state,
                    current_turn_index=int(main.current_turn_index),
                    current_turn_seat=None,
                )
        except Exception:
            logging.exception("stable round: failed to persist day-end state")
        await main.bot.send_message(
            gid,
            "✅ همه بازیکنا صحبت کردن. فاز روز تموم شد.",
            reply_markup=InlineKeyboardMarkup(row_width=1).add(
                InlineKeyboardButton("🗳 رای‌گیری", callback_data="vote:settings"),
                InlineKeyboardButton("🌙 شروع فاز شب", callback_data="start_night"),
                InlineKeyboardButton("🏁 اتمام بازی", callback_data="end_game")
            ),
        )


async def _advance(main):
    _ensure(main)
    if main._stable_day_ended:
        return
    while True:
        order = [int(x) for x in (getattr(main, "turn_order", []) or [])]
        idx = int(getattr(main, "current_turn_index", 0))
        if idx < len(order):
            seat = order[idx]
            if main._stable_phase == "extra":
                if seat in main._stable_extra_seats:
                    return await _start_extra(main, seat)
                main.current_turn_index += 1
                continue
            muted = {int(x) for x in getattr(main, "_gm_muted_active", set()) or set()}
            if seat in muted:
                await _cancel_timer(main)
                uid = _uid(main, seat)
                name = await _resolve_name(main, uid)
                await main.bot.send_message(_gid(main), f"🔇 {html.escape(name)} این دور سکوت است و نوبت صحبت ندارد.")
                main.current_turn_index += 1
                continue
            return await _start_turn(main, seat, 120, False)

        if main._stable_phase == "normal":
            pending = {int(x) for x in getattr(main, "_gm_extra_next_round", set()) or set()}
            base = list(main._stable_normal_order or _base_order(main))
            extras = [seat for seat in base if seat in pending]
            main._gm_extra_next_round.clear()
            if extras:
                main._stable_extra_seats = set(extras)
                main._stable_extra_used.clear()
                main._stable_phase = "extra"
                main._gm_extra_phase = True
                main._gm_extra_turn_active = False
                main.turn_order = list(extras)
                main.current_turn_index = 0
                continue
            return await _end_day(main)

        return await _end_day(main)


def _clear_legacy_handlers(reg):
    """Remove all old transition handlers; stable engine is sole authority."""
    kept = []
    for item in list(reg):
        fn = _handler(item)
        name = getattr(fn, "__name__", "")
        if (
            name in {
                "next_turn", "next_v3", "next_v6", "next_v7", "next_authoritative",
                "next_terminal", "next_turn_day_end_guard", "start_round_handler",
                "handle_start_turn", "challenge_request", "challenge_choice",
                "handle_challenge_response",
                "start_round_clean", "start_turn_clean",
            }
            or getattr(fn, "_v5_next", False)
            or getattr(fn, "_v8_next", False)
            or getattr(fn, "_v10_next", False)
            or getattr(fn, "_day_end_guard", False)
            or getattr(fn, "_callback_prefix", "") in {
                CHALLENGE_REQUEST_PREFIX, "accept_", "reject_"
            }
        ):
            continue
        kept.append(item)
    reg[:] = kept


def install(main):
    _ensure(main)
    dp = getattr(main, "dp", None)
    reg = getattr(getattr(dp, "callback_query_handlers", None), "handlers", None)
    if reg is None or getattr(main, "_stable_round_engine_installed", False):
        return False
    _clear_legacy_handlers(reg)

    async def start_round(callback):
        if callback.message and callback.message.chat.type == "private":
            await callback.answer("این عملیات فقط داخل گروه انجام می‌شود.", show_alert=True)
            raise CancelHandler()
        if callback.from_user.id != getattr(main, "moderator_id", None):
            await callback.answer("⛔ فقط گرداننده می‌تواند دور را شروع کند.", show_alert=True)
            raise CancelHandler()
        _ensure(main)

        # The webhook may land on a fresh Vercel worker. Never use the
        # process-local game_running flag as the authority for starting a round.
        try:
            game, _rows = _hydrate_runtime_players(main)
            _restore_persisted_turn_state(main, game)
        except Exception:
            logging.exception("stable round: failed to restore durable player/turn state")
            game = _fresh_active_game(main)

        if not game or str(game.get("status") or "") not in {"running", "paused"}:
            await callback.answer("⚠️ بازی در حال اجرا نیست.", show_alert=True)
            raise CancelHandler()
        main.game_running = True

        if main._stable_day_ended:
            await callback.answer("ℹ️ فاز روز قبلاً تمام شده است.", show_alert=True)
            raise CancelHandler()

        if main._stable_day_active:
            await callback.answer("⚠️ این دور قبلاً شروع شده است.", show_alert=True)
            raise CancelHandler()
        base = _base_order(main)
        if not base:
            await callback.answer("⚠️ بازیکنی برای شروع نوبت وجود ندارد.", show_alert=True)
            raise CancelHandler()

        head_seat = None
        try:
            head_seat = dict((game or {}).get("state") or {}).get("head_seat")
            if head_seat is not None:
                head_seat = int(head_seat)
        except (TypeError, ValueError):
            head_seat = None
        if head_seat is None or head_seat not in base:
            await callback.answer("⚠️ ابتدا از «انتخاب سردست» یک بازیکن را انتخاب کنید.", show_alert=True)
            raise CancelHandler()

        main._stable_day_active = True
        main._stable_day_ended = False
        main._stable_phase = "normal"
        try:
            game = main.runtime.state.active_game(_gid(main))
            settings = dict((game or {}).get("state") or {}).get("challenge_settings") or {}
            if "enabled" in settings:
                main.challenge_active = bool(settings.get("enabled"))
        except Exception:
            logging.exception("stable round: failed to restore challenge setting")
        main._stable_normal_order = list(base)
        main._stable_extra_seats = set()
        main._stable_extra_used = set()
        main._stable_challenge_used = set()
        main._stable_challenge_locked = set()
        main._stable_challenge_requests = {}
        main._stable_challenge_request_messages = {}
        main.challenge_active = bool(getattr(main, "challenge_enabled", {}).get(_gid(main), True))
        main.challenge_mode = False
        main.pending_challenges = {}
        main.active_challenger_seats = set()
        main.turn_order = list(base)
        main.current_turn_index = 0
        main._gm_extra_phase = False
        main._gm_extra_turn_active = False
        main._gm_extra_seats = set()
        main._gm_normal_order = list(base)
        try:
            game_now = main.runtime.state.active_game(_gid(main))
            if game_now:
                state_now = dict(game_now.get("state") or {})
                state_now["turn_order"] = [int(x) for x in base]
                state_now["current_turn_index"] = 0
                state_now["stable_day_active"] = True
                state_now["stable_day_ended"] = False
                main.runtime.state.games.update_game(
                    game_now["id"], state=state_now, current_turn_index=0, current_turn_seat=int(base[0])
                )
        except Exception:
            logging.exception("stable round: failed to persist initial turn state")
        roster = []
        for seat in base:
            uid = _uid(main, seat)
            name = await _resolve_name(main, uid)
            roster.append(f"{int(seat):02d}. <a href=\"tg://user?id={int(uid)}\">{html.escape(name)}</a>")
        if roster:
            await main.bot.send_message(
                _gid(main),
                "📋 <b>لیست بازیکنان</b>\n\n" + "\n".join(roster),
                parse_mode="HTML",
            )
        await _advance(main)
        await callback.answer("✅ دور شروع شد.")
        raise CancelHandler()

    async def next_handler(callback):
        _ensure(main)
        if callback.message and callback.message.chat.type == "private":
            await callback.answer("این عملیات فقط داخل گروه انجام می‌شود.", show_alert=True)
            raise CancelHandler()

        # Rehydrate the roster and exact durable turn position on EVERY NEXT.
        # A Vercel callback can land on a different worker from the one that
        # rendered the button, so process-local turn_order is never authoritative.
        game = None
        try:
            game, _rows = _hydrate_runtime_players(main)
            _restore_persisted_turn_state(main, game)
        except Exception:
            logging.exception("stable round: failed to hydrate turn state for NEXT")

        if main._stable_day_ended:
            await callback.answer("ℹ️ فاز روز قبلاً تمام شده است.", show_alert=True)
            raise CancelHandler()

        active = _active(main)
        if active is None:
            logging.warning(
                "stable round: no active seat game=%s index=%s order=%s",
                game.get("id") if game else None,
                getattr(main, "current_turn_index", None),
                getattr(main, "turn_order", None),
            )
            await callback.answer("⚠️ نوبت فعالی وجود ندارد.", show_alert=True)
            raise CancelHandler()
        try:
            clicked = int(str(callback.data).split("_", 1)[1])
        except Exception:
            await callback.answer("⚠️ نوبت نامعتبر است.", show_alert=True)
            raise CancelHandler()
        if clicked != active and not getattr(main, "challenge_mode", False):
            await callback.answer("⚠️ این نوبت دیگر فعال نیست.", show_alert=True)
            raise CancelHandler()
        uid = int(callback.from_user.id)
        owner = _uid(main, active)
        challenger_seats = {int(x) for x in getattr(main, "active_challenger_seats", set()) or set()}
        challenger_uids = {int(_uid(main, s) or -1) for s in challenger_seats}
        try:
            game = _fresh_active_game(main)
        except Exception:
            pass
        next_settings = dict((game or {}).get("state", {}).get("next_settings") or {})
        allow_players = bool(next_settings.get("allow_players_next", True))
        allow_moderator = bool(next_settings.get("allow_moderator_next", True))
        is_moderator = uid == int(getattr(main, "moderator_id", -1) or -1)
        is_owner = uid == int(owner or -1)
        is_challenger = uid in challenger_uids
        if is_moderator and not allow_moderator:
            await callback.answer("⛔ نکست برای گرداننده توسط مدیریت بازی غیرفعال است.", show_alert=True)
            raise CancelHandler()
        if (is_owner or is_challenger) and not allow_players:
            await callback.answer("⛔ نکست بازیکنان توسط مدیریت بازی غیرفعال است.", show_alert=True)
            raise CancelHandler()
        if not is_moderator and not is_owner and not is_challenger:
            await callback.answer("⛔ فقط صاحب نوبت، چالش‌گر یا گرداننده می‌تواند نکست بزند.", show_alert=True)
            raise CancelHandler()
        now = time.time()
        if now - float(getattr(main, "_stable_next_lock", 0.0)) < 0.8:
            await callback.answer("⏳ لطفاً کمی صبر کنید.", show_alert=True)
            raise CancelHandler()
        main._stable_next_lock = now
        await callback.answer()
        await _cancel_timer(main)
        await _delete_turn_message(main)

        if getattr(main, "challenge_mode", False):
            target = getattr(main, "paused_main_player", None)
            after = bool(getattr(main, "post_challenge_advance", False))
            try:
                game = main.runtime.state.active_game(_gid(main))
                runtime_state = dict((game or {}).get("state") or {}).get("challenge_runtime") or {}
                if target is None:
                    target = runtime_state.get("target_seat")
                if not after:
                    after = bool(runtime_state.get("post_challenge_advance", False))
            except Exception:
                logging.exception("stable challenge: failed to restore active challenge")
            main.challenge_mode = False
            main.active_challenger_seats = set()
            main._stable_phase = "normal"
            main._gm_extra_turn_active = False
            main.paused_main_player = None
            main.paused_main_duration = None
            main.post_challenge_advance = False
            try:
                game = main.runtime.state.active_game(_gid(main))
                state = dict((game or {}).get("state") or {})
                runtime = dict(state.get("challenge_runtime") or {})
                challenge_id = runtime.get("challenge_id")
                if challenge_id:
                    try: main.runtime.state.challenges.resolve_challenge(challenge_id, "executed")
                    except Exception: logging.exception("stable challenge: failed to mark executed challenge")
                state.pop("challenge_runtime", None)
                main.runtime.state.games.update_game(game["id"], state=state)
            except Exception:
                logging.exception("stable challenge: failed to clear active challenge")
            if target is not None:
                if after:
                    main.current_turn_index += 1
                else:
                    try:
                        main.current_turn_index = main.turn_order.index(int(target))
                    except ValueError:
                        pass
            return await _advance(main)

        pending = getattr(main, "pending_challenges", {}) or {}
        if main._stable_phase == "normal" and active in pending:
            challenger_id = pending.pop(active)
            challenger_seat = _seat(main, challenger_id)
            if challenger_seat is not None:
                main.paused_main_player = active
                main.paused_main_duration = 120
                main.post_challenge_advance = True
                main.challenge_mode = True
                main.active_challenger_seats = {int(challenger_seat)}
                main._stable_phase = "challenge"
                return await _start_turn(main, challenger_seat, 60, True)

        main.current_turn_index += 1
        try:
            game_now = main.runtime.state.active_game(_gid(main))
            if game_now:
                state_now = dict(game_now.get("state") or {})
                state_now["turn_order"] = [int(x) for x in main.turn_order]
                state_now["current_turn_index"] = int(main.current_turn_index)
                main.runtime.state.games.update_game(
                    game_now["id"],
                    state=state_now,
                    current_turn_index=int(main.current_turn_index),
                    current_turn_seat=(int(main.turn_order[main.current_turn_index]) if main.current_turn_index < len(main.turn_order) else None),
                )
        except Exception:
            logging.exception("stable round: failed to persist next transition")
        return await _advance(main)

    async def challenge_request(callback):
        _ensure(main)
        if callback.from_user.id == getattr(main, "moderator_id", None):
            await callback.answer("⛔ گرداننده نمی‌تواند چالش را درخواست کند.", show_alert=True)
            raise CancelHandler()
        if main._stable_day_ended or main._stable_phase != "normal":
            await callback.answer("⚠️ در این مرحله امکان درخواست چالش نیست.", show_alert=True)
            raise CancelHandler()
        try:
            target_seat = int(str(callback.data).removeprefix(CHALLENGE_REQUEST_PREFIX))
        except Exception:
            await callback.answer("⚠️ نوبت نامعتبر است.", show_alert=True)
            raise CancelHandler()
        active = _active(main)
        if active != target_seat:
            await callback.answer("⚠️ فقط برای نوبت فعال می‌توان چالش درخواست کرد.", show_alert=True)
            raise CancelHandler()
        challenger_id = int(callback.from_user.id)
        challenger_seat = _seat(main, challenger_id)
        if challenger_seat is None:
            await callback.answer("⚠️ شما بازیکن این بازی نیستید.", show_alert=True)
            raise CancelHandler()
        if challenger_seat == target_seat:
            await callback.answer("⚠️ بازیکن نمی‌تواند خودش را به چالش بکشد.", show_alert=True)
            raise CancelHandler()
        if target_seat in main._stable_challenge_locked:
            await callback.answer("⚠️ برای این نوبت قبلاً چالش ثبت شده است.", show_alert=True)
            raise CancelHandler()
        # Persist the challenge itself as the canonical record used later by
        # scoring/statistics. Do this before mutating the in-memory lock so a
        # database failure cannot leave a phantom "already requested" challenge.
        try:
            game = main.runtime.state.active_game(_gid(main))
            if not game:
                await callback.answer("⚠️ بازی فعال پیدا نشد.", show_alert=True)
                raise CancelHandler()
            challenge_id = main.runtime.state.challenges.create_challenge(
                game["id"], challenger_id, int(_uid(main, target_seat)), "turn", "pending"
            )
            pending_challenges = dict((game.get("state") or {}).get("challenge_requests") or {})
            pending_challenges[str(target_seat)] = {
                "challenger_id": int(challenger_id),
                "challenge_id": str(challenge_id),
            }
            state = dict(game.get("state") or {})
            state["challenge_requests"] = pending_challenges
            main.runtime.state.games.update_game(game["id"], state=state)
            main._stable_challenge_requests[target_seat] = challenger_id
            main._stable_challenge_locked.add(target_seat)
            main._stable_challenge_request_ids = getattr(main, "_stable_challenge_request_ids", {})
            main._stable_challenge_request_ids[target_seat] = challenge_id
        except CancelHandler:
            raise
        except Exception:
            logging.exception("stable challenge: failed to persist pending request")
            await callback.answer("❌ ثبت درخواست چالش انجام نشد.", show_alert=True)
            raise CancelHandler()
        name = await _resolve_name(main, challenger_id, _stored_name(main, challenger_id))
        target_uid = _uid(main, target_seat)
        target_name = await _resolve_name(main, target_uid, _stored_name(main, target_uid))
        msg = await main.bot.send_message(
            _gid(main),
            f"🤏🏻 <b>درخواست چالش</b>\n\n{name} از {target_name} چالش می‌خواد.",
            reply_markup=InlineKeyboardMarkup(row_width=2).add(
                InlineKeyboardButton("✅ قبول", callback_data=f"accept_{target_seat}"),
                InlineKeyboardButton("❌ رد", callback_data=f"reject_{target_seat}"),
            ),
            parse_mode="HTML",
        )
        main._stable_challenge_request_messages[target_seat] = msg.message_id
        await callback.answer("🤏🏻 درخواست چالش فرستاده شد.")
        raise CancelHandler()

    async def challenge_choice(callback):
        _ensure(main)
        try:
            target_seat = int(str(callback.data).split("_", 1)[1])
        except Exception:
            await callback.answer("⚠️ درخواست نامعتبر است.", show_alert=True)
            raise CancelHandler()
        target_uid = _uid(main, target_seat)
        if int(callback.from_user.id) != int(target_uid or -1):
            await callback.answer("⛔ فقط بازیکن نوبت می‌تواند پاسخ دهد.", show_alert=True)
            raise CancelHandler()
        challenger_id = main._stable_challenge_requests.get(target_seat)
        challenge_id = getattr(main, "_stable_challenge_request_ids", {}).get(target_seat)
        if not challenger_id:
            try:
                game = main.runtime.state.active_game(_gid(main))
                persisted = dict((game or {}).get("state") or {}).get("challenge_requests") or {}
                saved = persisted.get(str(target_seat)) or {}
                if isinstance(saved, dict):
                    challenger_id = int(saved.get("challenger_id") or 0)
                    challenge_id = saved.get("challenge_id")
                else:
                    challenger_id = int(saved or 0)
                if challenger_id:
                    main._stable_challenge_requests[target_seat] = challenger_id
                    if challenge_id:
                        main._stable_challenge_request_ids = getattr(main, "_stable_challenge_request_ids", {})
                        main._stable_challenge_request_ids[target_seat] = challenge_id
            except Exception:
                logging.exception("stable challenge: failed to restore pending request")
        if not challenger_id:
            await callback.answer("⚠️ درخواست چالش پیدا نشد.", show_alert=True)
            raise CancelHandler()
        accept = str(callback.data).startswith("accept_")
        main._stable_challenge_requests.pop(target_seat, None)
        main._stable_challenge_request_ids = getattr(main, "_stable_challenge_request_ids", {})
        challenge_id = main._stable_challenge_request_ids.pop(target_seat, challenge_id)
        if not accept:
            if challenge_id:
                try:
                    main.runtime.state.challenges.resolve_challenge(challenge_id, "rejected")
                except Exception:
                    logging.exception("stable challenge: failed to resolve rejected challenge")
            main._stable_challenge_used.add(target_seat)
            main._stable_challenge_locked.add(target_seat)
            try:
                game = main.runtime.state.active_game(_gid(main))
                state = dict((game or {}).get("state") or {})
                requests = dict(state.get("challenge_requests") or {})
                requests.pop(str(target_seat), None)
                state["challenge_requests"] = requests
                main.runtime.state.games.update_game(game["id"], state=state)
            except Exception:
                logging.exception("stable challenge: failed to clear rejected request")
            mid = main._stable_challenge_request_messages.pop(target_seat, None)
            if mid:
                try:
                    await main.bot.delete_message(_gid(main), mid)
                except Exception:
                    pass
            await callback.answer("❌ چالش رد شد.")
            raise CancelHandler()
        if challenge_id:
            try:
                main.runtime.state.challenges.resolve_challenge(challenge_id, "accepted")
            except Exception:
                logging.exception("stable challenge: failed to resolve accepted challenge")
        main._stable_challenge_used.add(target_seat)
        main._stable_challenge_locked.add(target_seat)
        try:
            game = main.runtime.state.active_game(_gid(main))
            state = dict((game or {}).get("state") or {})
            requests = dict(state.get("challenge_requests") or {})
            requests.pop(str(target_seat), None)
            state["challenge_requests"] = requests
            main.runtime.state.games.update_game(game["id"], state=state)
        except Exception:
            logging.exception("stable challenge: failed to clear accepted request")
        mid = main._stable_challenge_request_messages.pop(target_seat, None)
        if mid:
            try:
                await main.bot.delete_message(_gid(main), mid)
            except Exception:
                pass
        # Acceptance immediately transfers control to the challenger. The old
        # implementation only queued the challenge and waited for another
        # "next" click, which made an accepted challenge appear stuck.
        challenger_seat = _seat(main, int(challenger_id))
        if challenger_seat is None:
            await callback.answer("❌ صندلی چالش‌گر پیدا نشد.", show_alert=True)
            raise CancelHandler()
        main.paused_main_player = int(target_seat)
        main.paused_main_duration = 120
        main.post_challenge_advance = True
        main.challenge_mode = True
        main.active_challenger_seats = {int(challenger_seat)}
        main._stable_phase = "challenge"
        main.pending_challenges.pop(int(target_seat), None)
        try:
            game = main.runtime.state.active_game(_gid(main))
            state = dict((game or {}).get("state") or {})
            state["challenge_runtime"] = {
                "target_seat": int(target_seat),
                "challenger_seat": int(challenger_seat),
                "challenger_id": int(challenger_id),
                "challenge_id": str(challenge_id or ""),
                "post_challenge_advance": True,
            }
            main.runtime.state.games.update_game(game["id"], state=state)
        except Exception:
            logging.exception("stable challenge: failed to persist active challenge")
        await _cancel_timer(main)
        await _delete_turn_message(main)
        challenger_name = await _resolve_name(main, int(challenger_id), _stored_name(main, int(challenger_id)))
        target_name = await _resolve_name(main, int(target_uid), _stored_name(main, int(target_uid)))
        try:
            await main.bot.send_message(
                _gid(main),
                f"🤏🏻 <b>{html.escape(challenger_name)}</b> به <b>{html.escape(target_name)}</b> چالش داد.",
            )
        except Exception:
            logging.exception("stable challenge: failed to announce accepted challenge")
        await callback.answer("🤏🏻 چالش تایید شد.")
        started = await _start_turn(main, int(challenger_seat), 60, True)
        if started and challenge_id:
            try: main.runtime.state.challenges.resolve_challenge(challenge_id, "active")
            except Exception: logging.exception("stable challenge: failed to mark active challenge")
        raise CancelHandler()

    main._stable_round_start_handler = start_round
    main._stable_next_handler = next_handler
    main._stable_challenge_request_handler = challenge_request
    dp.register_callback_query_handler(start_round, lambda c: c.data == "start_round", state="*")
    dp.register_callback_query_handler(next_handler, lambda c: str(c.data).startswith(NEXT_PREFIX), state="*")
    dp.register_callback_query_handler(challenge_request, lambda c: str(c.data).startswith(CHALLENGE_REQUEST_PREFIX), state="*")
    dp.register_callback_query_handler(challenge_choice, lambda c: str(c.data).startswith("accept_"), state="*")
    dp.register_callback_query_handler(challenge_choice, lambda c: str(c.data).startswith("reject_"), state="*")
    main._stable_round_engine_installed = True
    return True
