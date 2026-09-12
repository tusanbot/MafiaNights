"""Game information, history and event recording UI.

Keeps archived game data in mafia_games.state JSONB so finished games remain
addressable after they leave the active-game lifecycle.
"""
from __future__ import annotations

import html
from datetime import datetime, timezone, timedelta
from functools import wraps
from typing import Any

from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from runtime.game_management import GameManagement


class ArchiveState(StatesGroup):
    waiting_game_number = State()
    waiting_events = State()


SIDE_ICONS = {"city": "🏙️", "mafia": "🌃", "independent": "🏴‍☠️"}
SIDE_NAMES = {"city": "شهر", "mafia": "مافیا", "independent": "مستقل"}
ROLE_SIDE_HINTS = {
    "پدرخوانده": "mafia", "ماتادور": "mafia", "گودمن": "mafia", "مافیا": "mafia",
    "لئون": "city", "دکتر": "city", "کنستانتین": "city", "همشهری کین": "city",
    "نوستراداموس": "independent", "جک": "independent", "مستقل": "independent",
}


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        value = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(value)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _local(dt: datetime | None) -> datetime | None:
    return dt.astimezone(timezone(timedelta(hours=3, minutes=30))) if dt else None


def _name(row: dict[str, Any]) -> str:
    return str(row.get("nickname") or row.get("first_name") or row.get("username") or row.get("player_id") or "👤")


def _side(row: dict[str, Any], state: dict[str, Any]) -> str:
    value = str(row.get("side") or "").lower().strip()
    if value in SIDE_ICONS:
        return value
    mapping = state.get("player_sides") or {}
    value = mapping.get(str(row.get("player_id")))
    if value in SIDE_ICONS:
        return value
    role = str(row.get("role") or "")
    for hint, side in ROLE_SIDE_HINTS.items():
        if hint in role:
            return side
    return "city"


def _events(game: dict[str, Any]) -> dict[str, Any]:
    state = dict(game.get("state") or {})
    value = state.get("game_events")
    if not isinstance(value, dict):
        value = {}
    value.setdefault("enabled", False)
    value.setdefault("text", "")
    value.setdefault("recorded", bool(value.get("text")))
    value.setdefault("published", False)
    return value


def _winner(game: dict[str, Any]) -> str:
    return str((game.get("state") or {}).get("game_result") or "")


def _winner_label(value: str) -> str:
    return {"city": "🏙 شهر", "mafia": "🔴 مافیا", "independent": "🟣 مستقل", "draw": "🤝 مساوی"}.get(value, "تعیین نشده")


def _duration(game: dict[str, Any]) -> str:
    start = _parse_dt(game.get("started_at")) or _parse_dt(game.get("created_at"))
    end = _parse_dt(game.get("finished_at")) or datetime.now(timezone.utc)
    if not start:
        return "---"
    seconds = max(0, int((end - start).total_seconds()))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h} ساعت و {m} دقیقه"
    if m:
        return f"{m} دقیقه و {s} ثانیه"
    return f"{s} ثانیه"


def _game_title(game: dict[str, Any]) -> str:
    number = int(game.get("event_number") or 1)
    status = str(game.get("status") or "")
    return f"📓 بازی {number}" + (" ✅" if status == "finished" else " 🟢")


def _game_options(game_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(row_width=2).add(
        InlineKeyboardButton("👥 لیست بازی", callback_data=f"game_info:{game_id}:players"),
        InlineKeyboardButton("📊 آمار بازی", callback_data=f"game_info:{game_id}:stats"),
        InlineKeyboardButton("📝 اتفاقات بازی", callback_data=f"game_info:{game_id}:events"),
        InlineKeyboardButton("ℹ️ اطلاعات کلی", callback_data=f"game_info:{game_id}:overview"),
        InlineKeyboardButton("⬅️ انتخاب بازی", callback_data=f"game_archive:menu:{game_id}"),
    )


def _archive_menu_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(row_width=2).add(
        InlineKeyboardButton("🟢 آخرین بازی فعال", callback_data="game_archive:active:0"),
        InlineKeyboardButton("🏁 آخرین بازی تمام‌شده", callback_data="game_archive:latest:0"),
        InlineKeyboardButton("🔢 وارد کردن شماره بازی", callback_data="game_archive:input:0"),
        InlineKeyboardButton("📚 فهرست بازی‌ها", callback_data="game_archive:list:0"),
    )


def _history_markup(games: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(row_width=1)
    for game in games:
        kb.add(InlineKeyboardButton(_game_title(game), callback_data=f"game_archive:select:{int(game['id'])}"))
    kb.add(InlineKeyboardButton("⬅️ بازگشت", callback_data="game_archive:menu:0"))
    return kb


def _overview(game: dict[str, Any]) -> str:
    state = dict(game.get("state") or {})
    start = _local(_parse_dt(game.get("started_at")) or _parse_dt(game.get("created_at")))
    end = _local(_parse_dt(game.get("finished_at")))
    scenario = state.get("scenario_name") or game.get("scenario") or game.get("scenario_id") or "---"
    return (
        f"🎮 <b>{_game_title(game)}</b>\n\n"
        f"🔢 شماره بازی: <b>{int(game.get('event_number') or 1)}</b>\n"
        f"📌 وضعیت: <b>{html.escape(str(game.get('status') or '---'))}</b>\n"
        f"🎭 سناریو: <b>{html.escape(str(scenario))}</b>\n"
        f"▶️ شروع: <b>{start:%H:%M:%S}</b>\n" if start else "▶️ شروع: <b>---</b>\n"
    ) + (
        f"⏹ پایان: <b>{end:%H:%M:%S}</b>\n" if end else "⏹ پایان: <b>---</b>\n"
    ) + f"⏱ مدت: <b>{_duration(game)}</b>\n🏆 برنده: <b>{html.escape(_winner_label(_winner(game)))}</b>"


def _players_text(game: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    state = dict(game.get("state") or {})
    winner = _winner(game)
    lines = [f"👥 <b>لیست بازی {int(game.get('event_number') or 1)}</b>", ""]
    for row in sorted(rows, key=lambda r: int(r.get("seat") or 999)):
        side = _side(row, state)
        icon = SIDE_ICONS.get(side, "👤")
        trophy = " 🏆" if winner and side == winner and winner != "draw" else ""
        seat = int(row.get("seat") or 0)
        lines.append(f"{icon} {seat:02d}. <b>{html.escape(_name(row))}</b} — {html.escape(str(row.get('role') or '---'))}{trophy}")
    return "\n".join(lines)


def _stats_text(game: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    state = dict(game.get("state") or {})
    counts = {key: 0 for key in SIDE_NAMES}
    alive = dead = 0
    for row in rows:
        side = _side(row, state)
        counts[side] = counts.get(side, 0) + 1
        if bool(row.get("is_alive", True)):
            alive += 1
        else:
            dead += 1
    return (
        f"📊 <b>آمار بازی {int(game.get('event_number') or 1)}</b>\n\n"
        f"👥 تعداد بازیکنان: <b>{len(rows)}</b>\n"
        f"❤️ زنده: <b>{alive}</b>\n💀 حذف‌شده: <b>{dead}</b>\n\n"
        f"🏙 شهر: <b>{counts['city']}</b>\n🌃 مافیا: <b>{counts['mafia']}</b>\n🏴‍☠️ مستقل: <b>{counts['independent']}</b>\n\n"
        f"🏆 نتیجه: <b>{html.escape(_winner_label(_winner(game)))}</b>\n"
        f"⏱ مدت بازی: <b>{_duration(game)}</b>"
    )


def _events_text(game: dict[str, Any]) -> str:
    value = _events(game)
    text = str(value.get("text") or "").strip()
    status = "🟢 فعال" if value.get("enabled") else "⚪ غیرفعال"
    if not text:
        text = "فعلا اتفاقات بازی ثبت نشده"
    return f"📝 <b>اتفاقات بازی {int(game.get('event_number') or 1)}</b>\n{status}\n\n{html.escape(text)}"


def install(app: Any) -> bool:
    dp = app.dp

    original_panel = getattr(GameManagement, "panel", None)
    if original_panel and not getattr(GameManagement, "_archive_panel_wrapped", False):
        @wraps(original_panel)
        def panel(self, game_id):
            kb = original_panel(self, game_id)
            kb.row(
                InlineKeyboardButton("🎮 اطلاعات بازی", callback_data=f"game_archive:menu:{int(game_id)}"),
                InlineKeyboardButton("📝 ثبت اتفاقات", callback_data=f"game_archive:events_menu:{int(game_id)}"),
            )
            return kb
        GameManagement.panel = panel
        GameManagement._archive_panel_wrapped = True

    def get_game(game_id: int):
        return app.runtime.state.games.get_game(int(game_id))

    def games_for_group(group_id: int, finished_only: bool = False):
        games = app.runtime.state.games.list_games(int(group_id), limit=100)
        if finished_only:
            games = [g for g in games if str(g.get("status")) == "finished"]
        return games

    async def allowed(callback: types.CallbackQuery, game: dict[str, Any]) -> bool:
        uid = int(callback.from_user.id)
        if uid == int(game.get("moderator_id") or 0):
            return True
        gid = int(game.get("group_chat_id") or callback.message.chat.id)
        try:
            return (await app.bot.get_chat_member(gid, uid)).status in {"creator", "administrator"}
        except Exception:
            return False

    async def archive_callback(callback: types.CallbackQuery, state: FSMContext):
        parts = str(callback.data or "").split(":")
        if len(parts) != 3 or parts[0] != "game_archive":
            return
        action = parts[1]
        ref = int(parts[2])
        if action == "input":
            await state.update_data(archive_origin_chat=int(callback.message.chat.id), archive_message_id=int(callback.message.message_id))
            await state.set_state(ArchiveState.waiting_game_number)
            await callback.message.edit_text("🔢 <b>شماره بازی</b>\n\nشماره بازی را وارد کنید:", parse_mode="HTML")
            await callback.answer()
            return
        if action == "menu":
            game = get_game(ref) if ref else None
            if game and not await allowed(callback, game):
                await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
            await callback.message.edit_text("🎮 <b>اطلاعات بازی‌ها</b>\n\nآخرین بازی، بازی تمام‌شده یا شماره دلخواه را انتخاب کنید:", parse_mode="HTML", reply_markup=_archive_menu_markup())
            await callback.answer(); return
        if action == "active":
            gid = int(callback.message.chat.id)
            game = app.runtime.state.active_game(gid)
            if not game:
                await callback.answer("ℹ️ بازی فعالی وجود ندارد.", show_alert=True); return
            if not await allowed(callback, game):
                await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
            await callback.message.edit_text(_overview(game), parse_mode="HTML", reply_markup=_game_options(int(game["id"])))
            await callback.answer(); return
        if action == "latest":
            gid = int(callback.message.chat.id)
            games = games_for_group(gid, True)
            if not games:
                await callback.answer("ℹ️ هنوز بازی تمام‌شده‌ای ثبت نشده.", show_alert=True); return
            game = games[0]
            if not await allowed(callback, game):
                await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
            await callback.message.edit_text(_overview(game), parse_mode="HTML", reply_markup=_game_options(int(game["id"])))
            await callback.answer(); return
        if action == "list":
            gid = int(callback.message.chat.id)
            games = games_for_group(gid, True)[:30]
            if not games:
                await callback.answer("ℹ️ آرشیو خالی است.", show_alert=True); return
            if not await allowed(callback, games[0]):
                await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
            await callback.message.edit_text("📚 <b>بازی‌های گذشته</b>\n\nبازی موردنظر را انتخاب کنید:", parse_mode="HTML", reply_markup=_history_markup(games))
            await callback.answer(); return
        if action == "select":
            game = get_game(ref)
            if not game or not await allowed(callback, game):
                await callback.answer("❌ بازی پیدا نشد یا دسترسی ندارید.", show_alert=True); return
            await callback.message.edit_text(_overview(game), parse_mode="HTML", reply_markup=_game_options(ref))
            await callback.answer(); return
        if action == "events_menu":
            game = get_game(ref)
            if not game or not await allowed(callback, game):
                await callback.answer("❌ بازی پیدا نشد یا دسترسی ندارید.", show_alert=True); return
            await state.update_data(events_game_id=ref, events_group_id=int(game.get("group_chat_id") or callback.message.chat.id), events_message_id=int(callback.message.message_id))
            await state.set_state(ArchiveState.waiting_events)
            await callback.message.edit_text(
                f"📝 <b>ثبت اتفاقات بازی {int(game.get('event_number') or 1)}</b>\n\n"
                "متن کامل اتفاقات را در یک پیام ارسال کنید.\n"
                "می‌توانید تیتر شب‌ها، سایدها و اقدامات نقش‌ها را دقیقاً با قالب دلخواه وارد کنید.",
                parse_mode="HTML",
            )
            await callback.answer(); return

    async def info_callback(callback: types.CallbackQuery):
        parts = str(callback.data or "").split(":")
        if len(parts) != 3 or parts[0] != "game_info":
            return
        game = get_game(int(parts[1]))
        if not game or not await allowed(callback, game):
            await callback.answer("❌ بازی پیدا نشد یا دسترسی ندارید.", show_alert=True); return
        rows = app.runtime.state.games.list_players(int(game["id"]))
        action = parts[2]
        if action == "players":
            text = _players_text(game, rows)
        elif action == "stats":
            text = _stats_text(game, rows)
        elif action == "events":
            text = _events_text(game)
        else:
            text = _overview(game)
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=_game_options(int(game["id"])))
        await callback.answer()

    async def game_number(message: types.Message, state: FSMContext):
        data = await state.get_data()
        raw = (message.text or "").strip().replace("٬", "").replace(",", "")
        if not raw.isdigit() or int(raw) < 1:
            await message.reply("❌ شماره بازی باید یک عدد مثبت باشد.")
            return
        number = int(raw)
        games = games_for_group(int(data.get("archive_origin_chat") or message.chat.id))
        game = next((g for g in games if int(g.get("event_number") or 0) == number), None)
        await state.finish()
        if not game:
            await message.reply(f"❌ بازی شماره <b>{number}</b> پیدا نشد.", parse_mode="HTML", reply_markup=_archive_menu_markup())
            return
        if not await allowed(message, game):
            await message.reply("⛔ دسترسی ندارید.")
            return
        await message.reply(_overview(game), parse_mode="HTML", reply_markup=_game_options(int(game["id"])))

    async def events_value(message: types.Message, state: FSMContext):
        data = await state.get_data()
        game_id = int(data.get("events_game_id") or 0)
        game = get_game(game_id)
        if not game or not await allowed(message, game):
            await state.finish(); await message.reply("⛔ دسترسی ندارید."); return
        text = (message.text or "").strip()
        if not text:
            await message.reply("❌ متن اتفاقات خالی است. دوباره ارسال کنید.")
            return
        game_state = dict(game.get("state") or {})
        events = _events(game)
        events.update({"text": text, "recorded": True, "updated_at": datetime.now(timezone.utc).isoformat()})
        game_state["game_events"] = events
        app.runtime.state.games.update_game(game_id, state=game_state)
        await state.finish()
        await message.reply(f"✅ اتفاقات بازی <b>{int(game.get('event_number') or 1)}</b> ذخیره شد.", parse_mode="HTML")
        if events.get("enabled") and str(game.get("status")) == "finished" and not events.get("published"):
            try:
                await app.bot.send_message(int(game["group_chat_id"]), _events_text({**game, "state": game_state}), parse_mode="HTML")
                events["published"] = True
                game_state["game_events"] = events
                app.runtime.state.games.update_game(game_id, state=game_state)
            except Exception:
                pass

    dp.register_callback_query_handler(archive_callback, lambda c: str(c.data or "").startswith("game_archive:"))
    dp.register_callback_query_handler(info_callback, lambda c: str(c.data or "").startswith("game_info:"))
    dp.register_message_handler(game_number, state=ArchiveState.waiting_game_number, content_types=types.ContentTypes.TEXT)
    dp.register_message_handler(events_value, state=ArchiveState.waiting_events, content_types=types.ContentTypes.TEXT)
    return True
