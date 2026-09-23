"""Manual game completion, finished-game history and event publication flow."""
from __future__ import annotations

import html
import logging
from datetime import datetime, timezone, timedelta
from functools import wraps
from typing import Any

from aiogram import types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from repositories.rating_repository import RatingRepository
from runtime.game_management import GameManagement


RESULTS = (
    ("city", "🏘 شهر"),
    ("mafia", "🌃 مافیا"),
    ("independent", "🥷 مستقل"),
    ("draw", "🤝 مساوی"),
)
SIDE_ICONS = {"city": "🏘", "mafia": "🌃", "independent": "🥷"}
WIN_SCORE = 1
DRAW_SCORE = 0


def _is_moderator_id(game: dict[str, Any], user_id: int) -> bool:
    """Return whether the user owns the durable moderator role for this game."""
    return int(user_id) == int(game.get("moderator_id") or 0)

ROLE_SIDE_HINTS = {
    "پدرخوانده": "mafia", "ماتادور": "mafia", "گودمن": "mafia", "مافیا": "mafia",
    "دکتر واتسون": "city", "همشهری کین": "city", "نوستراداموس": "city", "کنستانتین": "city",
    "لئون": "city", "شهر ساده": "city", "کارآگاه": "city", "دکتر": "city",
    "مستقل": "independent", "جک": "independent", "روانپزشک": "independent",
}


def _name(row: dict[str, Any]) -> str:
    return str(row.get("nickname") or row.get("first_name") or row.get("username") or row.get("player_id") or "👤")


def _result_label(result: str) -> str:
    return dict(RESULTS).get(result, result)


def _result_options_markup(game_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(row_width=2)
    for key, label in RESULTS:
        kb.insert(InlineKeyboardButton(label, callback_data=f"game_end:{int(game_id)}:winner_set:{key}"))
    kb.row(InlineKeyboardButton("⬅️ بازگشت", callback_data=f"game_end:{int(game_id)}:menu"))
    return kb


def _main_markup(game_id: int, winner: str | None, events_enabled: bool) -> InlineKeyboardMarkup:
    winner_label = _result_label(winner) if winner else "تعیین نشده"
    events_label = "🟢 فعال" if events_enabled else "⚪ غیرفعال"
    return InlineKeyboardMarkup(row_width=1).add(
        InlineKeyboardButton(f"🏆 ثبت برنده: {winner_label}", callback_data=f"game_end:{int(game_id)}:winner"),
        InlineKeyboardButton(f"📝 اتفاقات بازی: {events_label}", callback_data=f"game_end:{int(game_id)}:events"),
        InlineKeyboardButton("✅ ثبت نهایی", callback_data=f"game_end:{int(game_id)}:finalize"),
        InlineKeyboardButton("✖️ بستن", callback_data=f"game_end:{int(game_id)}:close"),
    )


def _events_markup(game_id: int, group_id: int, enabled: bool) -> InlineKeyboardMarkup:
    """PV event controls: exactly two choices, no redundant third button."""
    return InlineKeyboardMarkup(row_width=1).add(
        InlineKeyboardButton("🟢 فعال" + (" ✅" if enabled else ""), callback_data=f"game_event:{int(game_id)}:enable:{int(group_id)}"),
        InlineKeyboardButton("⚪ غیرفعال" + (" ✅" if not enabled else ""), callback_data=f"game_event:{int(game_id)}:disable:{int(group_id)}"),
    )


def _final_markup(game_id: int, from_history: bool = False) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(row_width=2).add(
        InlineKeyboardButton("📊 نتیجه بازی", callback_data=f"game_end:{int(game_id)}:result"),
        InlineKeyboardButton("ℹ️ اطلاعات بازی", callback_data=f"game_end:{int(game_id)}:info"),
        InlineKeyboardButton("📝 اتفاقات بازی", callback_data=f"game_end:{int(game_id)}:events"),
        InlineKeyboardButton("📚 بازی‌های گذشته", callback_data=f"game_history:list:{int(game_id)}"),
    )
    if from_history:
        kb.add(InlineKeyboardButton("⬅️ بازگشت به بازی‌های گذشته", callback_data=f"game_history:list:{int(game_id)}"))
    else:
        kb.add(InlineKeyboardButton("✖️ بستن", callback_data=f"game_end:{int(game_id)}:close"))
    return kb


def _stop_transient_tasks(app: Any) -> None:
    for obj_name, attr in (("ui", "turn_timer_task"), ("ui", "voting_timer_task"), ("ui", "day_timer_task")):
        obj = getattr(app, obj_name, None)
        task = getattr(obj, attr, None) if obj else None
        if task and not task.done():
            try:
                task.cancel()
            except Exception:
                logging.exception("failed to cancel %s.%s", obj_name, attr)


def _role_side(row: dict[str, Any], state: dict[str, Any]) -> str:
    explicit = str(row.get("side") or "").strip().lower()
    if explicit in {"city", "mafia", "independent"}:
        return explicit
    by_player = state.get("player_sides") or {}
    value = by_player.get(str(int(row.get("player_id") or 0)))
    if value in {"city", "mafia", "independent"}:
        return value
    by_seat = state.get("players_in_game") or {}
    item = by_seat.get(str(int(row.get("seat") or 0))) or {}
    value = str(item.get("side") or "").strip().lower()
    if value in {"city", "mafia", "independent"}:
        return value
    role = str(row.get("role") or "").strip()
    for hint, side in ROLE_SIDE_HINTS.items():
        if hint in role:
            return side
    return "city"


def _jalali_date(dt: datetime) -> str:
    gy, gm, gd = dt.year, dt.month, dt.day
    gdm = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy + 1 if gm > 2 else gy
    days = 355666 + (365 * gy) + ((gy2 + 3) // 4) - ((gy2 + 99) // 100) + ((gy2 + 399) // 400) + gd + gdm[gm - 1]
    jy = -1595 + 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm, jd = 1 + days // 31, 1 + days % 31
    else:
        jm, jd = 7 + (days - 186) // 30, 1 + (days - 186) % 30
    return f"{jy:04d}/{jm:02d}/{jd:02d}"


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except Exception:
            return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _game_times(game: dict[str, Any]) -> tuple[datetime, datetime]:
    start = _parse_dt(game.get("started_at")) or _parse_dt(game.get("created_at")) or datetime.now(timezone.utc)
    end = _parse_dt(game.get("finished_at")) or datetime.now(timezone.utc)
    return start, end


def _duration_text(game: dict[str, Any]) -> str:
    start, end = _game_times(game)
    seconds = max(0, int((end - start).total_seconds()))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours} ساعت و {minutes} دقیقه"
    if minutes:
        return f"{minutes} دقیقه و {secs} ثانیه"
    return f"{secs} ثانیه"


def _local_dt(dt: datetime) -> datetime:
    return dt.astimezone(timezone(timedelta(hours=3, minutes=30)))


def _events_state(game: dict[str, Any]) -> dict[str, Any]:
    state = dict(game.get("state") or {})
    events = state.get("game_events")
    if not isinstance(events, dict):
        events = {"enabled": False, "text": None, "recorded": False, "published": False}
        state["game_events"] = events
    events.setdefault("enabled", False)
    events.setdefault("text", None)
    events.setdefault("recorded", bool(events.get("text")))
    events.setdefault("published", False)
    return events


def _final_text(game: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    state = dict(game.get("state") or {})
    snapshot = state.get("final_players")
    if isinstance(snapshot, list) and snapshot:
        rows = [dict(row) for row in snapshot]
    winner = str(state.get("game_result") or "")
    start, end = _game_times(game)
    start = _local_dt(start)
    end = _local_dt(end)
    scenario = str(state.get("scenario_name") or game.get("scenario") or game.get("scenario_id") or "---")
    moderator_id = int(game.get("moderator_id") or 0)
    moderator_row = next((r for r in rows if int(r.get("player_id") or 0) == moderator_id), None)
    moderator = str(state.get("moderator_name") or game.get("moderator_name") or (_name(moderator_row) if moderator_row else (game.get("moderator_id") or "---")))
    status = str(game.get("status") or "")
    number = int(game.get("event_number") or 0)
    number_text = "لغو شده" if status == "cancelled" else (str(number) if number > 0 else "---")
    lines = [
        "༄",
        "<b>Mafia Nights</b>",
        "",
        f"▶️ شروع: <b>{start:%H:%M}</b>",
        f"⏹ پایان: <b>{end:%H:%M}</b>",
        f"⏱ مدت بازی: <b>{_duration_text(game)}</b>",
        f"📆 تاریخ: <b>{_jalali_date(start)}</b>",
        f"🗓 Scenario: <b>{html.escape(scenario)}</b>",
        f"👮‍♂ گرداننده: <b>{html.escape(moderator)}</b>",
        f"📓 شماره بازی: <b>{html.escape(number_text)}</b>",
        "",
        "◤◢◣◥◤◢◣◥◤◢◣◥",
    ]
    for row in sorted(rows, key=lambda r: int(r.get("seat") or 999)):
        seat = int(row.get("seat") or 0)
        name = _name(row)
        role = str(row.get("role") or "---")
        side = _role_side(row, state)
        icon = SIDE_ICONS.get(side, "👤")
        is_winner = winner in {"city", "mafia", "independent"} and side == winner
        display_name = f"<b>{html.escape(name)}</b>" if is_winner else html.escape(name)
        trophy = " 🏆" if is_winner else ""
        lines.append(f"{icon}{seat:02d} {display_name} — {html.escape(role)}{trophy}")
    lines.extend(["", "◤◢◣◥◤◢◣◥◤◢◣◥", f"برنده: <b>{html.escape(_result_label(winner))}</b> 🏆", "༄"])
    return "\n".join(lines)


def _summary_text(game: dict[str, Any]) -> str:
    state = dict(game.get("state") or {})
    winner = str(state.get("game_result") or "")
    scenario = str(state.get("scenario_name") or game.get("scenario") or game.get("scenario_id") or "---")
    return (
        "🏁 <b>اتمام بازی</b>\n\n"
        "بازی به پایان رسید.\n"
        "لطفاً جهت رعایت نظم گروه اصلی، در گروه چت پیام بفرستین تا گرداننده نتیجه و اتفاقات بازی رو ثبت کنه.\n\n"
        f"📓 شماره بازی: <b>{'لغو شده' if str(game.get('status') or '') == 'cancelled' else (str(int(game.get('event_number') or 0)) if int(game.get('event_number') or 0) > 0 else '---')}</b>\n"
        f"🗓 سناریو: <b>{html.escape(scenario)}</b>\n"
        f"🏆 برنده: <b>{html.escape(_result_label(winner) if winner else 'تعیین نشده')}</b>"
    )


def _final_player_rows(rows: list[dict[str, Any]], state: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Return the immutable set of players who actually started this game."""
    state = state or {}
    snapshot = state.get("started_participants") or []
    current = {int(r.get("player_id") or 0): dict(r) for r in rows}
    result = []
    if snapshot:
        for saved in snapshot:
            uid = int(saved.get("player_id") or 0)
            row = dict(current.get(uid) or {})
            # Keep the original seat for dead/removed/kicked participants.
            row["player_id"] = uid
            row["seat"] = int(saved.get("seat") or row.get("seat") or 0)
            row.setdefault("nickname", saved.get("nickname"))
            if not row.get("role"):
                row["role"] = saved.get("role") or ""
            result.append(row)
        return sorted(result, key=lambda r: int(r.get("seat") or 999))

    # Backward compatibility for games created before the immutable snapshot.
    excluded = {"left", "waiting", "substitute", "replacement"}
    for row in rows:
        status = str(row.get("status") or "active").strip().lower()
        if row.get("seat") is None or status in excluded:
            continue
        result.append(row)
    return sorted(result, key=lambda r: int(r.get("seat") or 999))

def _score_players(app: Any, game: dict[str, Any], rows: list[dict[str, Any]], winner: str) -> None:
    score_for = (lambda side: DRAW_SCORE) if winner == "draw" else (lambda side: WIN_SCORE if side == winner else 0)
    repo = RatingRepository()
    state = dict(game.get("state") or {})
    rows = _final_player_rows(rows, state)
    recorded = set(str(x) for x in (state.get("rating_recorded_players") or []))
    for row in rows:
        uid = int(row["player_id"])
        key = str(uid)
        if key in recorded:
            continue
        side = _role_side(row, state)
        score = int(score_for(side))
        result = "draw" if winner == "draw" else ("win" if side == winner else "loss")
        try:
            repo.record(uid, int(game["id"]), score, result, str(row.get("role") or ""))
            recorded.add(key)
        except Exception:
            logging.exception("failed to record rating game=%s user=%s", game.get("id"), uid)
    state["rating_recorded_players"] = sorted(recorded)
    app.runtime.state.games.update_game(game["id"], state=state)


def _stop_and_finalize_players(app: Any, game: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    for row in rows:
        try:
            app.runtime.state.games.set_player_status(game["id"], int(row["player_id"]), "finished")
        except Exception:
            logging.exception("failed to finalize player game=%s user=%s", game.get("id"), row.get("player_id"))
    _stop_transient_tasks(app)


def _days_played(game: dict[str, Any]) -> int:
    state = dict(game.get("state") or {})
    for key in ("days_played", "day_count", "day_number", "current_day"):
        try:
            value = int(state.get(key) or 0)
            if value > 0:
                return value
        except (TypeError, ValueError):
            pass
    # Older runtimes did not persist a dedicated day counter. A completed
    # game necessarily contains at least the day on which it was finished.
    return max(1, int(state.get("round") or 1))


def _private_player_final_text(
    app: Any,
    game: dict[str, Any],
    row: dict[str, Any],
    winner: str,
) -> str:
    """Build the player's private, game-specific final report."""
    rating = RatingRepository()
    uid = int(row.get("player_id") or 0)
    try:
        details = rating.game_score_details(uid, game["id"])
    except Exception:
        logging.exception("failed to load game score details game=%s user=%s", game.get("id"), uid)
        details = {"score_delta": 0, "result": "", "role": row.get("role") or ""}
    try:
        summary = rating.player_summary(uid)
    except Exception:
        logging.exception("failed to load player total score game=%s user=%s", game.get("id"), uid)
        summary = {"score": 0, "games": 0, "wins": 0, "losses": 0, "draws": 0}
    state = dict(game.get("state") or {})
    scenario = str(state.get("scenario_name") or game.get("scenario") or game.get("scenario_id") or "—")
    start, end = _game_times(game)
    start = _local_dt(start)
    end = _local_dt(end)
    side = _role_side(row, state)
    side_label = {"city": "🏙 شهر", "mafia": "🔴 مافیا", "independent": "🟣 مستقل"}.get(side, "—")
    result_label = _result_label(winner) if winner else "تعیین نشده"
    score_delta = int(details.get("score_delta") or 0)
    total_score = int(summary.get("score") or 0)
    earned = f"+{score_delta}" if score_delta > 0 else str(score_delta)
    return (
        "🏁 <b>گزارش پایان بازی</b>\n\n"
        f"📓 شماره بازی: <b>{int(game.get('event_number') or 0) or '—'}</b>\n"
        f"🎭 سناریو: <b>{html.escape(scenario)}</b>\n"
        f"📅 تاریخ: <b>{_jalali_date(start)}</b>\n"
        f"▶️ شروع: <b>{start:%H:%M}</b>  |  ⏹ پایان: <b>{end:%H:%M}</b>\n"
        f"⏱ مدت بازی: <b>{_duration_text(game)}</b>\n"
        f"📆 تعداد روزهای حضور در بازی: <b>{_days_played(game)}</b>\n\n"
        f"👤 بازیکن: <b>{html.escape(_name(row))}</b>\n"
        f"🪑 صندلی: <b>{int(row.get('seat') or 0) or '—'}</b>\n"
        f"🎭 نقش: <b>{html.escape(str(row.get('role') or details.get('role') or '—'))}</b>\n"
        f"🏷️ ساید: <b>{side_label}</b>\n"
        f"🏆 نتیجه بازی: <b>{html.escape(result_label)}</b>\n\n"
        f"⭐ امتیاز این بازی: <b>{earned}</b>\n"
        f"📊 امتیاز کل: <b>{total_score}</b>\n"
        f"🎮 تعداد بازی‌های ثبت‌شده: <b>{int(summary.get('games') or 0)}</b>\n"
        f"🏆 برد: <b>{int(summary.get('wins') or 0)}</b>  |  ❌ باخت: <b>{int(summary.get('losses') or 0)}</b>  |  🤝 مساوی: <b>{int(summary.get('draws') or 0)}</b>\n\n"
        "ℹ️ این گزارش فقط در پیام خصوصی شما ارسال شده است."
    )


def _events_message(events: dict[str, Any]) -> str:
    text = str(events.get("text") or "").strip()
    if text:
        return "📝 <b>اتفاقات بازی</b>\n\n" + html.escape(text)
    return "📝 <b>اتفاقات بازی</b>\n\nفعلا اتفاقات بازی ثبت نشده"


def _history_markup(games: list[dict[str, Any]], back_game_id: int | None = None) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(row_width=1)
    for game in games:
        number = int(game.get("event_number") or 1)
        state = dict(game.get("state") or {})
        winner = _result_label(str(state.get("game_result") or ""))
        kb.add(InlineKeyboardButton(f"📓 بازی {number} — {winner or 'بدون نتیجه'}", callback_data=f"game_history:view:{int(game['id'])}"))
    if back_game_id is not None:
        kb.add(InlineKeyboardButton("⬅️ بازگشت به نتیجه بازی", callback_data=f"game_end:{int(back_game_id)}:result"))
    return kb


def install(app: Any) -> bool:
    dp = app.dp

    # Management UI ownership is final: management_surface_final owns the panel.
    # The end-game runtime only owns the finish callback and result/history screens.

    def _is_moderator(callback: types.CallbackQuery, game: dict[str, Any]) -> bool:
        """Sensitive game mutations are owned exclusively by the durable moderator."""
        return _is_moderator_id(game, int(callback.from_user.id))

    async def allowed_view(callback: types.CallbackQuery, game: dict[str, Any]) -> bool:
        """Allow the moderator or a group admin to inspect game/history screens."""
        if _is_moderator(callback, game):
            return True
        try:
            group_id = int(game.get("group_chat_id") or callback.message.chat.id)
            return (await app.bot.get_chat_member(group_id, int(callback.from_user.id))).status in {"creator", "administrator"}
        except Exception:
            return False

    def get_game(game_id: int):
        return app.runtime.state.games.get_game(int(game_id))

    async def show_main_menu(callback: types.CallbackQuery, game: dict[str, Any]) -> None:
        state = dict(game.get("state") or {})
        events = _events_state(game)
        await callback.message.edit_text(
            _summary_text(game), parse_mode="HTML",
            reply_markup=_main_markup(int(game["id"]), state.get("game_result"), bool(events.get("enabled"))),
        )
        await callback.answer()

    async def open_finish(callback: types.CallbackQuery, game: dict[str, Any]) -> None:
        await show_main_menu(callback, game)

    async def finish_menu(callback: types.CallbackQuery):
        parts = str(callback.data or "").split(":")
        if len(parts) != 3 or parts[0] != "mgmt" or parts[2] != "finish": return
        gid = int(callback.message.chat.id)
        game = app.runtime.state.active_game(gid)
        if not game or int(game.get("id")) != int(parts[1]):
            await callback.answer("❌ بازی فعال نیست.", show_alert=True); return
        if not _is_moderator(callback, game):
            await callback.answer("⛔ فقط گرداننده بازی می‌تواند بازی را مدیریت و تمام کند.", show_alert=True); return
        if str(game.get("status") or "") not in {"running", "paused", "turn"}:
            await callback.answer("❌ فقط بازی فعال قابل اتمام است.", show_alert=True); return
        await open_finish(callback, game)

    async def end_game_legacy(callback: types.CallbackQuery):
        if str(callback.data or "") != "end_game": return
        gid = int(callback.message.chat.id)
        game = app.runtime.state.active_game(gid)
        if not game:
            await callback.answer("❌ بازی فعالی وجود ندارد.", show_alert=True); return
        if not await allowed(callback, game):
            await callback.answer("⛔ فقط گرداننده یا مدیر گروه.", show_alert=True); return
        if str(game.get("status") or "") not in {"running", "paused", "turn"}:
            await callback.answer("❌ فقط بازی فعال قابل اتمام است.", show_alert=True); return
        await open_finish(callback, game)

    async def game_end(callback: types.CallbackQuery):
        parts = str(callback.data or "").split(":")
        if len(parts) < 3 or parts[0] != "game_end": return
        game_id = int(parts[1])
        game = get_game(game_id)
        if not game:
            await callback.answer("❌ بازی پیدا نشد.", show_alert=True); return
        action = parts[2]
        if action in {"menu", "winner", "winner_set", "finalize", "confirm_final"} and not _is_moderator(callback, game):
            await callback.answer("⛔ فقط گرداننده بازی می‌تواند این عملیات را انجام دهد.", show_alert=True); return
        if action in {"close", "events", "info", "result"}:
            if not await allowed_view(callback, game):
                await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        elif action not in {"menu", "winner", "winner_set", "finalize", "confirm_final"} and not await allowed_view(callback, game):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        state = dict(game.get("state") or {})
        events = _events_state(game)

        if action == "menu":
            if str(game.get("status") or "") != "running":
                await callback.answer("ℹ️ این بازی ثبت نهایی شده است.", show_alert=True); return
            await show_main_menu(callback, game); return
        if action == "close":
            await callback.message.delete(); await callback.answer(); return
        if action == "winner":
            if str(game.get("status") or "") != "running":
                await callback.answer("❌ بازی قبلاً نهایی شده است.", show_alert=True); return
            await callback.message.edit_text("🏆 <b>ثبت برنده</b>\n\nساید برنده بازی را انتخاب کنید:", parse_mode="HTML", reply_markup=_result_options_markup(game_id))
            await callback.answer(); return
        if action == "winner_set":
            if len(parts) != 4 or parts[3] not in dict(RESULTS):
                await callback.answer("❌ نتیجه نامعتبر است.", show_alert=True); return
            if str(game.get("status") or "") != "running":
                await callback.answer("❌ این بازی قبلاً بسته شده است.", show_alert=True); return
            winner = parts[3]
            # Persist the moderator's human-readable name before rendering the
            # final result. Older games may only have moderator_id.
            if not state.get("moderator_name"):
                try:
                    gid = int(game.get("group_chat_id") or callback.message.chat.id)
                    moderator_id = int(game.get("moderator_id") or 0)
                    if moderator_id:
                        member = await app.bot.get_chat_member(gid, moderator_id)
                        user = getattr(member, "user", None)
                        moderator_name = getattr(user, "full_name", None) or getattr(user, "first_name", None) or getattr(user, "username", None)
                        if moderator_name:
                            state["moderator_name"] = str(moderator_name)
                except Exception:
                    logging.exception("failed to hydrate moderator name game=%s", game.get("id"))
            state["game_result"] = winner
            state["game_result_label"] = _result_label(winner)
            state["winner_selected_at"] = datetime.now(timezone.utc).isoformat()
            state["winner_selected"] = True
            if not app.runtime.state.games.update_game(game_id, state=state):
                await callback.answer("❌ ثبت برنده انجام نشد.", show_alert=True); return
            game = get_game(game_id) or {**game, "state": state}
            rows = _final_player_rows(app.runtime.state.games.list_players(game_id), state)
            _score_players(app, game, rows, winner)
            events = _events_state(game)
            await callback.message.edit_text(_summary_text(game), parse_mode="HTML", reply_markup=_main_markup(game_id, winner, bool(events.get("enabled"))))
            await callback.answer(f"🏆 برنده ثبت شد: {_result_label(winner)}")
            return
        if action == "events":
            await callback.message.edit_text(
                _events_message(events),
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup().add(
                    InlineKeyboardButton("⬅️ بازگشت به نتیجه بازی", callback_data=f"game_end:{game_id}:result")
                ),
            )
            await callback.answer()
            return
        if action == "info":
            rows = app.runtime.state.games.list_players(game_id)
            started = _parse_dt(game.get("started_at"))
            finished = _parse_dt(game.get("finished_at"))
            state = dict(game.get("state") or {})
            await callback.message.edit_text(
                "ℹ️ <b>اطلاعات بازی</b>\n\n"
                f"📓 شماره بازی: <b>{int(game.get('event_number') or 0) or '—'}</b>\n"
                f"🎭 سناریو: <b>{html.escape(str(state.get('scenario_name') or game.get('scenario') or game.get('scenario_id') or '—'))}</b>\n"
                f"🎩 گرداننده: <b>{html.escape(str(state.get('moderator_name') or game.get('moderator_name') or game.get('moderator_id') or '—'))}</b>\n"
                f"👥 بازیکنان ثبت‌شده: <b>{len([r for r in rows if r.get('seat') is not None])}</b>\n"
                f"▶️ شروع: <b>{_local_dt(started).strftime('%Y/%m/%d %H:%M') if started else '—'}</b>\n"
                f"⏹ پایان: <b>{_local_dt(finished).strftime('%Y/%m/%d %H:%M') if finished else '—'}</b>\n"
                f"🏆 نتیجه: <b>{html.escape(_result_label(str(state.get('game_result') or '')))}</b>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup().add(
                    InlineKeyboardButton("⬅️ بازگشت به نتیجه بازی", callback_data=f"game_end:{game_id}:result")
                ),
            )
            await callback.answer()
            return
        if action == "finalize":
            winner = str(state.get("game_result") or "")
            if winner not in dict(RESULTS):
                await callback.answer("⚠️ ابتدا باید برنده بازی ثبت شود.", show_alert=True); return
            await callback.message.edit_text(
                "⚠️ <b>تأیید ثبت نهایی</b>\n\nبا ثبت نهایی، بازی از فهرست بازی فعال خارج و در آرشیو بازی‌های گذشته نگهداری می‌شود.\n\nآیا ادامه می‌دهید؟",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(row_width=2).add(
                    InlineKeyboardButton("✅ ثبت نهایی", callback_data=f"game_end:{game_id}:confirm_final"),
                    InlineKeyboardButton("⬅️ بازگشت", callback_data=f"game_end:{game_id}:menu"),
                ),
            )
            await callback.answer(); return
        if action == "confirm_final":
            winner = str(state.get("game_result") or "")
            if winner not in dict(RESULTS):
                await callback.answer("⚠️ ابتدا برنده را ثبت کنید.", show_alert=True); return
            rows = _final_player_rows(app.runtime.state.games.list_players(game_id), state)
            now = datetime.now(timezone.utc)
            if not game.get("started_at"):
                started = _parse_dt(game.get("created_at")) or now
                game["started_at"] = started
            state["finished_manually"] = True
            state["finished_at"] = now.isoformat()
            state["finalized"] = True
            state["final_players"] = [
                {
                    "player_id": int(row.get("player_id") or 0),
                    "seat": int(row.get("seat")),
                    "role": str(row.get("role") or ""),
                    "side": _role_side(row, state),
                    "nickname": _name(row),
                }
                for row in rows
            ]
            state["game_archive"] = {
                "status": "finished",
                "winner": winner,
                "finished_at": now.isoformat(),
                "duration": _duration_text({**game, "finished_at": now}),
            }
            if not app.runtime.state.games.update_game(game_id, status="finished", state=state, started_at=game.get("started_at"), finished_at=now):
                await callback.answer("❌ ثبت نهایی انجام نشد.", show_alert=True); return
            final_game = {**game, "state": state, "status": "finished", "finished_at": now}
            scorer = getattr(app, "_score_finished_game", None)
            if scorer:
                try:
                    scorer(final_game, rows, winner)
                except Exception:
                    logging.exception("final game scoring failed game=%s", game_id)
            _stop_and_finalize_players(app, final_game, rows)
            try:
                from runtime.end_game_control import _clear_runtime_flags
                _clear_runtime_flags(app)
            except Exception:
                logging.exception("failed to clear runtime flags after finalization game=%s", game_id)
            try:
                app.runtime.state.games._invalidate(
                    group_chat_id=int(game.get("group_chat_id") or callback.message.chat.id),
                    game_id=game_id,
                )
            except Exception:
                logging.exception("failed to invalidate game caches after finalization game=%s", game_id)
            final_game = {**game, "state": state, "status": "finished", "finished_at": now}
            text = _final_text(final_game, rows)
            try:
                await callback.message.edit_text(text, parse_mode="HTML", reply_markup=_final_markup(game_id, from_history=True))
            except Exception:
                await callback.message.answer(text, parse_mode="HTML", reply_markup=_final_markup(game_id))
            events = _events_state(final_game)
            if events.get("enabled"):
                await callback.message.answer(_events_message(events), parse_mode="HTML")
            for row in rows:
                try:
                    await app.bot.send_message(
                        int(row["player_id"]),
                        _private_player_final_text(app, final_game, row, winner),
                        parse_mode="HTML",
                        reply_markup=InlineKeyboardMarkup(row_width=1).add(
                            InlineKeyboardButton("📊 نتیجه بازی", callback_data=f"game_end:{game_id}:result")
                        ),
                    )
                except Exception:
                    logging.exception("failed to send private final report game=%s user=%s", game_id, row.get("player_id"))
            await callback.answer("🏁 بازی با موفقیت ثبت نهایی شد.")
            return
        if action == "result":
            rows = app.runtime.state.games.list_players(game_id)
            await callback.message.edit_text(_final_text(game, rows), parse_mode="HTML", reply_markup=_final_markup(game_id, from_history=str(game.get("status") or "") == "finished"))
            await callback.answer(); return
        await callback.answer("❌ عملیات نامعتبر است.", show_alert=True)

    async def game_event(callback: types.CallbackQuery):
        parts = str(callback.data or "").split(":")
        if len(parts) != 4 or parts[0] != "game_event": return
        game_id, action, group_id = int(parts[1]), parts[2], int(parts[3])
        game = get_game(game_id)
        if not game or int(game.get("group_chat_id") or 0) != group_id:
            await callback.answer("❌ بازی پیدا نشد.", show_alert=True); return
        if not _is_moderator(callback, game):
            await callback.answer("⛔ فقط گرداننده بازی می‌تواند وضعیت اتفاقات را تغییر دهد.", show_alert=True); return
        if action not in {"enable", "disable"}:
            await callback.answer("❌ عملیات نامعتبر است.", show_alert=True); return
        state = dict(game.get("state") or {})
        events = _events_state(game)
        events["enabled"] = action == "enable"
        state["game_events"] = events
        app.runtime.state.games.update_game(game_id, state=state)
        await callback.message.edit_text(
            "📝 <b>پنل اتفاقات بازی</b>\n\n"
            f"وضعیت ارسال اتفاقات: <b>{'فعال' if events['enabled'] else 'غیرفعال'}</b>",
            parse_mode="HTML", reply_markup=_events_markup(game_id, group_id, bool(events.get("enabled"))),
        )
        await callback.answer("✅ وضعیت اتفاقات ذخیره شد.")

    async def game_history(callback: types.CallbackQuery):
        parts = str(callback.data or "").split(":")
        if len(parts) < 3 or parts[0] != "game_history": return
        action = parts[1]
        reference_id = int(parts[2])
        reference = get_game(reference_id)
        if not reference:
            await callback.answer("❌ بازی پیدا نشد.", show_alert=True); return
        if not await allowed_view(callback, reference):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        group_id = int(reference.get("group_chat_id") or callback.message.chat.id)
        if action == "list":
            games = app.runtime.state.games.list_finished_games(group_id, limit=20)
            if not games:
                await callback.answer("ℹ️ هنوز بازی ثبت نهایی‌شده‌ای وجود ندارد.", show_alert=True); return
            await callback.message.edit_text("📚 <b>بازی‌های گذشته</b>\n\nبازی موردنظر را انتخاب کنید:", parse_mode="HTML", reply_markup=_history_markup(games, reference_id))
            await callback.answer(); return
        if action == "view":
            game = app.runtime.state.games.get_finished_game(reference_id)
            if not game:
                await callback.answer("❌ این بازی در آرشیو پیدا نشد.", show_alert=True); return
            rows = app.runtime.state.games.list_players(reference_id)
            await callback.message.edit_text(_final_text(game, rows), parse_mode="HTML", reply_markup=_final_markup(reference_id, from_history=True))
            await callback.answer(); return

    dp.register_callback_query_handler(finish_menu, lambda c: str(c.data or "").startswith("mgmt:") and str(c.data or "").split(":")[-1] == "finish", state="*")
    dp.register_callback_query_handler(end_game_legacy, lambda c: str(c.data or "") == "end_game", state="*")
    dp.register_callback_query_handler(game_event, lambda c: str(c.data or "").startswith("game_event:"), state="*")
    dp.register_callback_query_handler(game_history, lambda c: str(c.data or "").startswith("game_history:"), state="*")
    dp.register_callback_query_handler(game_end, lambda c: str(c.data or "").startswith("game_end:"), state="*")
    app._game_end_installed = True
    return True
