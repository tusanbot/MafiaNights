"""Durable manual game completion flow.

This module intentionally does not depend on the unfinished voting engine. The
moderator can end a running game, choose the winning side/result, persist the
result, mark all game players finished, stop transient timers, and show a
final result in the group and private chat.
"""
from __future__ import annotations

import html
import logging
from datetime import datetime, timezone
from functools import wraps
from typing import Any

from aiogram import types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from runtime.game_management import GameManagement


RESULTS = (
    ("city", "🏙 شهر"),
    ("mafia", "🔴 مافیا"),
    ("independent", "🟣 مستقل"),
    ("draw", "🤝 مساوی"),
)


def _name(row: dict[str, Any]) -> str:
    return str(row.get("nickname") or row.get("first_name") or row.get("username") or row.get("player_id") or "👤")


def _stop_transient_tasks(app: Any) -> None:
    for obj_name, attr in (("ui", "turn_timer_task"), ("ui", "voting_timer_task"), ("ui", "day_timer_task")):
        obj = getattr(app, obj_name, None)
        task = getattr(obj, attr, None) if obj else None
        if task and not task.done():
            try:
                task.cancel()
            except Exception:
                logging.exception("failed to cancel %s.%s", obj_name, attr)


def _finish_markup(game_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(row_width=2)
    for key, label in RESULTS:
        kb.insert(InlineKeyboardButton(label, callback_data=f"game_end:{int(game_id)}:{key}"))
    kb.row(InlineKeyboardButton("❌ انصراف", callback_data=f"game_end:{int(game_id)}:back"))
    return kb


def _final_markup(game_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(row_width=2).add(
        InlineKeyboardButton("📊 نتیجه بازی", callback_data=f"game_end:{int(game_id)}:result"),
        InlineKeyboardButton("✖️ بستن", callback_data=f"game_end:{int(game_id)}:close"),
    )


def _result_label(result: str) -> str:
    return dict(RESULTS).get(result, result)


def _result_text(game: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    state = dict(game.get("state") or {})
    result = str(state.get("game_result") or "draw")
    scenario = str(state.get("scenario_name") or game.get("scenario") or game.get("scenario_id") or "---")
    number = int(game.get("event_number") or 1)
    alive = [r for r in rows if bool(r.get("is_alive", True)) and str(r.get("status") or "") not in {"removed", "finished"}]
    dead = [r for r in rows if r not in alive]
    lines = [
        "༄",
        "<b>🏁 پایان بازی Mafia Nights</b>",
        "",
        f"🔢 شماره بازی: <b>{number}</b>",
        f"🎭 سناریو: <b>{html.escape(scenario)}</b>",
        f"🏆 نتیجه: <b>{html.escape(_result_label(result))}</b>",
        "",
        f"👥 بازیکنان: <b>{len(rows)}</b>",
        f"🟢 زنده: <b>{len(alive)}</b>",
        f"💀 حذف‌شده: <b>{len(dead)}</b>",
        "",
        "<b>بازیکنان</b>",
    ]
    for row in sorted(rows, key=lambda r: int(r.get("seat") or 999)):
        status = "🟢" if bool(row.get("is_alive", True)) and str(row.get("status") or "") != "removed" else "💀"
        role = str(row.get("role") or "---")
        lines.append(f"{status} {int(row.get('seat') or 0):02d}. {html.escape(_name(row))} — {html.escape(role)}")
    return "\n".join(lines)


def install(app: Any) -> bool:
    """Register end-game callbacks and add the button to the management panel."""
    dp = app.dp

    original_panel = getattr(GameManagement, "panel", None)
    if original_panel and not getattr(GameManagement, "_game_end_panel_wrapped", False):
        @wraps(original_panel)
        def panel(self, game_id):
            kb = original_panel(self, game_id)
            kb.row(InlineKeyboardButton("🏁 اتمام بازی", callback_data=f"mgmt:{int(game_id)}:finish"))
            return kb
        GameManagement.panel = panel
        GameManagement._game_end_panel_wrapped = True

    async def allowed(callback: types.CallbackQuery, game: dict[str, Any]) -> bool:
        uid = int(callback.from_user.id)
        if uid == int(game.get("moderator_id") or 0):
            return True
        try:
            return (await app.bot.get_chat_member(int(callback.message.chat.id), uid)).status in {"creator", "administrator"}
        except Exception:
            return False

    async def show_finish_menu(callback: types.CallbackQuery, game: dict[str, Any]) -> None:
        await callback.message.edit_text(
            "🏁 <b>اتمام بازی</b>\n\nنتیجه نهایی بازی را انتخاب کنید:",
            parse_mode="HTML", reply_markup=_finish_markup(int(game["id"])),
        )
        await callback.answer()

    async def finish_menu(callback: types.CallbackQuery):
        parts = str(callback.data or "").split(":")
        if len(parts) != 3 or parts[0] != "mgmt" or parts[2] != "finish":
            return
        gid = int(callback.message.chat.id)
        game = app.runtime.state.active_game(gid)
        if not game or int(game.get("id")) != int(parts[1]):
            await callback.answer("❌ بازی فعال نیست.", show_alert=True)
            return
        if not await allowed(callback, game):
            await callback.answer("⛔ فقط گرداننده یا مدیر گروه.", show_alert=True)
            return
        if str(game.get("status") or "") != "running":
            await callback.answer("❌ فقط بازی در حال اجرا قابل اتمام است.", show_alert=True)
            return
        await show_finish_menu(callback, game)

    async def end_game_legacy(callback: types.CallbackQuery):
        """Bridge the legacy day-end callback into the canonical manual flow."""
        if str(callback.data or "") != "end_game":
            return
        gid = int(callback.message.chat.id)
        game = app.runtime.state.active_game(gid)
        if not game:
            await callback.answer("❌ بازی فعالی وجود ندارد.", show_alert=True)
            return
        if not await allowed(callback, game):
            await callback.answer("⛔ فقط گرداننده یا مدیر گروه.", show_alert=True)
            return
        if str(game.get("status") or "") != "running":
            await callback.answer("❌ فقط بازی در حال اجرا قابل اتمام است.", show_alert=True)
            return
        await show_finish_menu(callback, game)

    async def finish(callback: types.CallbackQuery):
        parts = str(callback.data or "").split(":")
        if len(parts) != 3 or parts[0] != "game_end":
            return
        gid = int(callback.message.chat.id)
        game = app.runtime.state.active_game(gid)
        if not game or int(game.get("id")) != int(parts[1]):
            await callback.answer("❌ بازی فعال نیست.", show_alert=True)
            return
        if not await allowed(callback, game):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
            return
        action = parts[2]
        if action == "back":
            manager = GameManagement(app)
            await callback.message.edit_text("⚙️ <b>مدیریت بازی</b>", parse_mode="HTML", reply_markup=manager.panel(int(game["id"])))
            await callback.answer()
            return
        if action == "close":
            await callback.message.delete()
            await callback.answer()
            return
        if action == "result":
            rows = app.runtime.state.games.list_players(game["id"])
            await callback.message.edit_text(_result_text(game, rows), parse_mode="HTML", reply_markup=_final_markup(int(game["id"])))
            await callback.answer()
            return
        if action not in {x[0] for x in RESULTS}:
            await callback.answer("❌ نتیجه نامعتبر است.", show_alert=True)
            return
        if str(game.get("status") or "") != "running":
            await callback.answer("❌ این بازی قبلاً بسته شده است.", show_alert=True)
            return

        rows = app.runtime.state.games.list_players(game["id"])
        now = datetime.now(timezone.utc)
        state = dict(game.get("state") or {})
        state.update({
            "game_result": action,
            "game_result_label": _result_label(action),
            "finished_manually": True,
            "finished_at": now.isoformat(),
        })
        scenario_name = state.get("scenario_name") or game.get("scenario") or game.get("scenario_id")
        if scenario_name:
            state["scenario_name"] = str(scenario_name)

        # Persist the final state before Telegram calls so a timeout cannot leave
        # the game looking active after the moderator has already ended it.
        if not app.runtime.state.games.update_game(
            game["id"], status="finished", state=state, finished_at=now,
        ):
            await callback.answer("❌ ثبت پایان بازی انجام نشد.", show_alert=True)
            return

        for row in rows:
            try:
                app.runtime.state.games.set_player_status(game["id"], int(row["player_id"]), "finished")
            except Exception:
                logging.exception("failed to finalize player game=%s user=%s", game["id"], row.get("player_id"))

        _stop_transient_tasks(app)
        text = _result_text({**game, "state": state}, rows)
        try:
            await callback.message.edit_text(text, parse_mode="HTML", reply_markup=_final_markup(int(game["id"])))
        except Exception:
            logging.exception("failed to render final game result game=%s", game["id"])
            await callback.message.answer(text, parse_mode="HTML", reply_markup=_final_markup(int(game["id"])))

        # The group result is the source of truth. A short PV notification is
        # sent best-effort and never blocks game finalization.
        for row in rows:
            try:
                await app.bot.send_message(
                    int(row["player_id"]),
                    "🏁 <b>بازی به پایان رسید.</b>\n\n" +
                    f"🏆 نتیجه: <b>{html.escape(_result_label(action))}</b>\n" +
                    f"🎭 سناریو: <b>{html.escape(str(scenario_name or '---'))}</b>",
                    parse_mode="HTML",
                )
            except Exception:
                pass
        await callback.answer("🏁 بازی با موفقیت به پایان رسید.")

    dp.register_callback_query_handler(
        finish_menu,
        lambda c: str(c.data or "").startswith("mgmt:") and str(c.data or "").split(":")[-1] == "finish",
        state="*",
    )
    dp.register_callback_query_handler(
        end_game_legacy,
        lambda c: str(c.data or "") == "end_game",
        state="*",
    )
    dp.register_callback_query_handler(
        finish,
        lambda c: str(c.data or "").startswith("game_end:"),
        state="*",
    )
    app._game_end_installed = True
    return True
