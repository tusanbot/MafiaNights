"""Role distribution for the canonical production lobby."""
from __future__ import annotations

import html
import json
import logging
import random
from typing import Any

from aiogram import types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from repositories.scenario_repository import ScenarioRepository


def _sync_gameplay_bridge(app: Any, group_id: int, game: dict[str, Any], players: list[dict[str, Any]]) -> None:
    app.group_chat_id = int(group_id)
    app.ui.group_chat_id = int(group_id)
    app.moderator_id = int(game.get("moderator_id") or 0) or None
    app.player_slots = {int(row["seat"]): int(row["player_id"]) for row in players if row.get("seat") is not None}
    app.players = {
        int(row["player_id"]): str(row.get("nickname") or row.get("first_name") or row.get("username") or row["player_id"])
        for row in players
    }
    app.turn_order = sorted(app.player_slots)
    app.current_turn_index = 0
    app.game_running = True
    app._stable_day_active = False
    app._stable_day_ended = False
    app._stable_phase = "normal"
    app.challenge_mode = False
    app.pending_challenges = {}
    app.active_challenger_seats = set()


def install(app: Any) -> bool:
    """Register exactly one role-distribution handler and expose it to Lobby."""
    dp, bot = app.dp, app.bot
    scenario_repo = ScenarioRepository()

    async def distribute_roles(callback: types.CallbackQuery):
        group_id = int(callback.message.chat.id)
        uid = int(callback.from_user.id)
        game = app.runtime.state.active_game(group_id)
        if not game:
            await callback.answer("❌ بازی فعالی وجود ندارد.", show_alert=True)
            return

        canonical_game_id = getattr(callback, "_canonical_lobby_game_id", None)
        if canonical_game_id is not None and int(game["id"]) != int(canonical_game_id):
            await callback.answer("⚠️ این دکمه مربوط به بازی قبلی است.", show_alert=True)
            return
        if str(game.get("status") or "") != "lobby":
            await callback.answer("❌ لابی فعال نیست.", show_alert=True)
            return

        moderator_id = int(game.get("moderator_id") or 0)
        allowed = uid == moderator_id
        if not allowed:
            try:
                member = await bot.get_chat_member(group_id, uid)
                allowed = member.status in {"creator", "administrator"}
            except Exception:
                allowed = False
        if not allowed:
            await callback.answer("⛔ فقط گرداننده یا مدیر گروه می‌تواند نقش‌ها را پخش کند.", show_alert=True)
            return

        scenario_id = game.get("scenario_id")
        try:
            scenario = scenario_repo.get_by_id(int(scenario_id)) if scenario_id is not None else None
        except (TypeError, ValueError):
            scenario = None
        if not scenario:
            await callback.answer("❌ سناریوی بازی مشخص نیست.", show_alert=True)
            return

        roles = scenario.get("roles") or []
        if isinstance(roles, str):
            try:
                roles = json.loads(roles)
            except Exception:
                roles = [x.strip() for x in roles.split(",") if x.strip()]
        roles = list(roles)

        players = [
            row for row in app.runtime.lobby_snapshot(group_id).get("players", [])
            if row.get("seat") is not None and str(row.get("status") or "active") not in {"removed", "dead"}
        ]
        players.sort(key=lambda row: int(row.get("seat") or 999))
        if not players:
            await callback.answer("❌ بازیکنی در لابی نیست.", show_alert=True)
            return
        if len(players) != len(roles):
            await callback.answer(f"❌ تعداد بازیکنان ({len(players)}) با ظرفیت سناریو ({len(roles)}) برابر نیست.", show_alert=True)
            return

        random.shuffle(roles)
        game_id = int(game["id"])
        role_map: dict[str, str] = {}
        failures: list[int] = []
        for player, role in zip(players, roles):
            player_id = int(player["player_id"])
            if not app.runtime.state.games.set_player_role(game_id, player_id, str(role)):
                failures.append(player_id)
            role_map[str(player_id)] = str(role)
        if failures:
            await callback.answer("❌ ذخیره نقش‌ها کامل نشد؛ بازی شروع نشد.", show_alert=True)
            logging.error("role distribution failed players=%s game=%s", failures, game_id)
            return

        state = dict(game.get("state") or {})
        state.update({
            "last_role_map": role_map,
            "players_in_game": {
                str(int(row["seat"])): {
                    "id": int(row["player_id"]),
                    "name": str(row.get("nickname") or row.get("first_name") or row.get("username") or row["player_id"]),
                    "role": role_map[str(int(row["player_id"]))],
                } for row in players
            },
            "roles_distributed": True,
            "gameplay_ready": True,
            "turn_order": [int(row["seat"]) for row in players],
            "current_turn_index": 0,
        })
        if not app.runtime.state.games.update_game(game_id, status="running", state=state, current_turn_index=0, current_turn_seat=None):
            await callback.answer("❌ انتقال بازی به مرحله اجرا انجام نشد.", show_alert=True)
            return
        game = app.runtime.state.active_game(group_id) or game
        _sync_gameplay_bridge(app, group_id, game, players)

        sent = 0
        for player in players:
            player_id = int(player["player_id"]); role = role_map[str(player_id)]; seat = int(player["seat"])
            try:
                await bot.send_message(
                    player_id,
                    "༄\n<b>🎭 MAFIA NIGHTS</b>\n\n"
                    f"🎭 <b>نقش شما:</b> {html.escape(role)}\n"
                    f"💺 <b>صندلی:</b> {seat}\n"
                    f"📝 <b>سناریو:</b> {html.escape(str(scenario.get('name') or scenario_id))}",
                    parse_mode="HTML",
                )
                sent += 1
            except Exception:
                logging.exception("failed to send role privately: user=%s game=%s", player_id, game_id)

        if moderator_id:
            roster = [
                f"{int(row['seat']):02d}. {html.escape(str(row.get('nickname') or row.get('first_name') or row.get('username') or row['player_id']))} — <b>{html.escape(role_map[str(int(row['player_id']))])}</b>"
                for row in players
            ]
            try:
                await bot.send_message(moderator_id, "༄\n<b>🎭 نقش‌های بازی</b>\n\n" + "\n".join(roster), parse_mode="HTML")
            except Exception:
                logging.exception("failed to send moderator role roster: game=%s", game_id)

        start_markup = InlineKeyboardMarkup(row_width=1).add(
            InlineKeyboardButton("▶️ شروع دور اول", callback_data="start_round")
        )
        await bot.send_message(
            group_id,
            "🎭 <b>نقش‌ها پخش شد.</b>\n\n"
            f"👥 بازیکنان: {len(players)}\n"
            f"📨 ارسال خصوصی موفق: {sent}/{len(players)}\n\n"
            "گرداننده برای شروع فاز روز روی «▶️ شروع دور اول» بزند.",
            parse_mode="HTML", reply_markup=start_markup,
        )
        await callback.answer(f"✅ نقش‌ها پخش شد ({sent}/{len(players)} ارسال موفق)")
        logging.info("roles distributed and gameplay armed: game=%s scenario=%s players=%d sent=%d", game_id, scenario.get("name"), len(players), sent)

    app._role_distribution_handler = distribute_roles
    dp.register_callback_query_handler(distribute_roles, lambda c: c.data == "distribute_roles", state="*")
    logging.info("PRODUCTION_ROLE_DISTRIBUTION_ACTIVE")
    return True
