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


def install(app: Any) -> bool:
    """Register the production role-distribution callback."""
    dp = app.dp
    bot = app.bot
    scenario_repo = ScenarioRepository()

    async def distribute_roles(callback: types.CallbackQuery):
        group_id = int(callback.message.chat.id)
        uid = int(callback.from_user.id)
        game = app.runtime.state.active_game(group_id)
        if not game:
            await callback.answer("❌ بازی فعالی وجود ندارد.", show_alert=True)
            return

        moderator_id = int(game.get("moderator_id") or 0)
        is_admin = uid == moderator_id
        if not is_admin:
            try:
                member = await bot.get_chat_member(group_id, uid)
                is_admin = member.status in {"creator", "administrator"}
            except Exception:
                is_admin = False
        if not is_admin:
            await callback.answer("⛔ فقط گرداننده یا مدیر گروه می‌تواند نقش‌ها را پخش کند.", show_alert=True)
            return

        scenario_id = game.get("scenario_id")
        scenario = scenario_repo.get_by_id(int(scenario_id)) if scenario_id is not None else None
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
            if row.get("seat") is not None
            and str(row.get("status") or "active") not in {"removed", "dead"}
        ]
        players.sort(key=lambda row: int(row.get("seat") or 999))

        if not players:
            await callback.answer("❌ بازیکنی در لابی نیست.", show_alert=True)
            return
        if len(players) != len(roles):
            await callback.answer(
                f"❌ تعداد بازیکنان ({len(players)}) با ظرفیت سناریو ({len(roles)}) برابر نیست.",
                show_alert=True,
            )
            return

        # Never reuse an existing assignment: every distribution gets a fresh shuffle.
        random.shuffle(roles)
        game_id = game["id"]
        role_map: dict[str, str] = {}
        failures: list[int] = []
        for player, role in zip(players, roles):
            player_id = int(player["player_id"])
            if not app.runtime.state.games.set_player_role(game_id, player_id, str(role)):
                failures.append(player_id)
            role_map[str(player_id)] = str(role)

        if failures:
            await callback.answer("❌ ذخیره یکی از نقش‌ها انجام نشد؛ پخش نقش لغو شد.", show_alert=True)
            logging.error("role distribution failed for players=%s game=%s", failures, game_id)
            return

        state = dict(game.get("state") or {})
        state["last_role_map"] = role_map
        state["players_in_game"] = {
            str(int(row["seat"])): {
                "id": int(row["player_id"]),
                "name": str(row.get("nickname") or row.get("first_name") or row.get("username") or row["player_id"]),
                "role": role_map[str(int(row["player_id"]))],
            }
            for row in players
        }
        state["roles_distributed"] = True
        app.runtime.state.games.update_game(game_id, state=state)

        sent = 0
        for player in players:
            player_id = int(player["player_id"])
            role = role_map[str(player_id)]
            seat = int(player["seat"])
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

        # Give the moderator a private roster as well.
        if moderator_id:
            roster = [
                f"{int(row['seat']):02d}. {html.escape(str(row.get('nickname') or row.get('first_name') or row.get('username') or row['player_id']))} — <b>{html.escape(role_map[str(int(row['player_id']))])}</b>"
                for row in players
            ]
            try:
                await bot.send_message(
                    moderator_id,
                    "༄\n<b>🎭 نقش‌های بازی</b>\n\n" + "\n".join(roster),
                    parse_mode="HTML",
                )
            except Exception:
                logging.exception("failed to send moderator role roster: game=%s", game_id)

        await callback.answer(f"✅ نقش‌ها پخش شد ({sent}/{len(players)} ارسال موفق)")
        logging.info("roles distributed: game=%s scenario=%s players=%d sent=%d", game_id, scenario.get("name"), len(players), sent)

    dp.register_callback_query_handler(distribute_roles, lambda c: c.data == "distribute_roles")
    logging.info("PRODUCTION_ROLE_DISTRIBUTION_ACTIVE")
    return True
