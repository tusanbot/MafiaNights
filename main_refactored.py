"""MafiaNights clean Telegram application target.

This file is intentionally separate from ``main.py`` during migration.
``main.py`` remains the untouched rollback/reference implementation.

Design rules:
- PersistentGameRuntime is the only authoritative game-state boundary.
- No mutable module-level game containers are used.
- Telegram message IDs, asyncio Tasks and anti-spam timestamps live inside
  one application instance and are never persisted as game truth.
- Lobby/turn/challenge/day mutations go through the persistent runtimes.
- The file is a migration target; production entry is switched only after
  integration tests against the real bot/database pass.
"""
from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils import executor
from aiogram.utils.exceptions import MessageCantBeEdited, MessageNotModified, MessageToEditNotFound

from mafia_addons import MafiaAddons
from player_service import player_service
from runtime.game_runtime import PersistentGameRuntime
from runtime.game_state_machine import Phase
from runtime.ephemeral_recovery import EphemeralRecoveryManager


DEFAULT_TURN_DURATION = 120
DEFAULT_CHALLENGE_DURATION = 60
ALLOWED_GROUP_ID = int(os.getenv("ALLOWED_GROUP_ID", "-1001760002160"))
SCENARIOS_FILE = Path("scenarios.json")


class AddScenario(StatesGroup):
    waiting_for_name = State()
    waiting_for_roles = State()
    waiting_for_min_players = State()


@dataclass
class TelegramRuntime:
    """Process-local Telegram/UI state only.

    Nothing in this object is authoritative game state. Recreating it after a
    restart from PersistentGameRuntime is expected and safe.
    """
    group_chat_id: Optional[int] = None
    lobby_message_id: Optional[int] = None
    game_message_id: Optional[int] = None
    current_turn_message_id: Optional[int] = None
    waiting_message_id: Optional[int] = None
    turn_timer_task: Optional[asyncio.Task] = None
    last_next_at: float = 0.0
    recovered_turn_plans: dict[int, dict[str, Any]] = field(default_factory=dict)
    recovered_challenges: list[dict[str, Any]] = field(default_factory=list)


class MafiaApplication:
    """Clean application shell around the persistent Mafia runtime."""

    def __init__(self, token: str):
        self.bot = Bot(token=token, parse_mode="HTML")
        self.dp = Dispatcher(self.bot, storage=MemoryStorage())
        self.runtime = PersistentGameRuntime()
        self.ui = TelegramRuntime()
        self.addons = MafiaAddons(self.bot)
        self.scenarios = self._load_scenarios()
        self.challenge_enabled: dict[int, bool] = {}
        self.roles: dict[int, dict[int, str]] = {}
        self.recovery = EphemeralRecoveryManager(self.runtime, self)
        self._register_handlers()

    @staticmethod
    def _load_scenarios() -> dict[str, dict[str, Any]]:
        if SCENARIOS_FILE.exists():
            try:
                data = json.loads(SCENARIOS_FILE.read_text(encoding="utf-8"))
                return data if isinstance(data, dict) else {}
            except (OSError, json.JSONDecodeError):
                logging.exception("failed to load scenarios")
        return {
            "سناریو کلاسیک": {
                "roles": ["مافیا", "مافیا", "شهروند", "شهروند", "شهروند"],
                "min_players": 5,
            }
        }

    def _save_scenarios(self) -> None:
        SCENARIOS_FILE.write_text(
            json.dumps(self.scenarios, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _scenario_roles(self, scenario: str) -> list[str]:
        value = self.scenarios.get(scenario) or {}
        return list(value.get("roles") or [])

    def _max_players(self, scenario: Optional[str]) -> int:
        return len(self._scenario_roles(scenario)) if scenario else 0

    async def _ensure_player(self, user: types.User) -> None:
        try:
            player_service.ensure_player(user)
        except Exception:
            logging.exception("player profile sync failed for %s", user.id)

    def _name(self, user_id: int, fallback: str = "❓") -> str:
        try:
            return player_service.display_name(user_id, fallback)
        except Exception:
            return fallback

    def _snapshot(self, group_id: int) -> dict[str, Any]:
        return self.runtime.snapshot(group_id)

    def _players_by_seat(self, group_id: int) -> dict[int, dict[str, Any]]:
        snapshot = self.runtime.lobby_snapshot(group_id)
        return {
            int(row["seat"]): row
            for row in snapshot.get("players", [])
            if row.get("seat") is not None
            and row.get("status") in {"active", "substitute"}
        }

    def _turn_order(self, group_id: int) -> list[int]:
        game = self.runtime.state.active_game(group_id)
        if not game:
            return []
        state = dict(game.get("state") or {})
        order = state.get("turn_order") or []
        return [int(seat) for seat in order]

    def _current_index(self, group_id: int) -> int:
        game = self.runtime.state.active_game(group_id)
        return int((game or {}).get("current_turn_index") or 0)

    def _persist_turn_pointer(self, group_id: int, order: list[int], index: int) -> None:
        game = self.runtime.state.active_game(group_id)
        if not game:
            return
        seat = order[index] if order and 0 <= index < len(order) else None
        state = dict(game.get("state") or {})
        state["turn_order"] = [int(x) for x in order]
        self.runtime.state.games.update_game(
            game["id"],
            state=state,
            current_turn_index=int(index),
            current_turn_seat=seat,
        )

    def _keyboard_main(self) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(row_width=1).add(
            InlineKeyboardButton("🎮 بازی جدید", callback_data="new_game"),
            InlineKeyboardButton("📖 راهنما", callback_data="help"),
        )

    def _keyboard_lobby(self, scenario: Optional[str], group_id: int) -> InlineKeyboardMarkup:
        kb = InlineKeyboardMarkup(row_width=5)
        maximum = self._max_players(scenario)
        occupied = self._players_by_seat(group_id)
        for seat in range(1, maximum + 1):
            label = str(seat)
            if seat in occupied:
                label = f"{seat} ({self._name(int(occupied[seat]['player_id']))})"
            kb.insert(InlineKeyboardButton(label, callback_data=f"seat:{seat}"))
        kb.row(
            InlineKeyboardButton("✅ ورود", callback_data="join"),
            InlineKeyboardButton("❌ خروج", callback_data="leave"),
        )
        if scenario:
            minimum = int((self.scenarios.get(scenario) or {}).get("min_players") or 0)
            if len(occupied) >= minimum:
                kb.add(InlineKeyboardButton("🎭 پخش نقش", callback_data="roles"))
        kb.add(InlineKeyboardButton("🚫 لغو بازی", callback_data="cancel_game"))
        return kb

    async def _render_lobby(self, group_id: int) -> None:
        snapshot = self.runtime.lobby_snapshot(group_id)
        game = snapshot.get("game") or {}
        scenario = game.get("scenario_id")
        moderator_id = game.get("moderator_id")
        players = snapshot.get("players") or []
        text = "📋 <b>لابی Mafia Nights</b>\n\n"
        text += f"🗓 سناریو: {html.escape(str(scenario or 'انتخاب نشده'))}\n"
        text += f"👑 گرداننده: {html.escape(self._name(int(moderator_id), 'انتخاب نشده')) if moderator_id else 'انتخاب نشده'}\n\n"
        if players:
            for row in sorted(players, key=lambda item: (item.get("seat") is None, item.get("seat") or 999)):
                uid = int(row["player_id"])
                seat = row.get("seat")
                state = "رزرو" if seat is None else f"صندلی {seat}"
                text += f"• <a href='tg://user?id={uid}'>{html.escape(self._name(uid))}</a> — {state}\n"
        else:
            text += "هنوز بازیکنی وارد نشده است.\n"
        kb = self._keyboard_lobby(scenario, group_id)
        message_id = self.ui.lobby_message_id
        try:
            if message_id:
                await self.bot.edit_message_text(
                    text, group_id, message_id, parse_mode="HTML", reply_markup=kb
                )
            else:
                msg = await self.bot.send_message(group_id, text, parse_mode="HTML", reply_markup=kb)
                self.ui.lobby_message_id = msg.message_id
        except (MessageNotModified, MessageCantBeEdited):
            pass
        except MessageToEditNotFound:
            msg = await self.bot.send_message(group_id, text, parse_mode="HTML", reply_markup=kb)
            self.ui.lobby_message_id = msg.message_id

    async def new_game(self, callback: types.CallbackQuery) -> None:
        group_id = int(callback.message.chat.id)
        if group_id != ALLOWED_GROUP_ID:
            await callback.answer("❌ این ربات در این گروه فعال نیست.", show_alert=True)
            return
        self.ui.group_chat_id = group_id
        game = self.runtime.lobby.ensure(group_id)
        await self._render_lobby(group_id)
        await callback.answer("🎮 لابی جدید آماده شد.")

    async def join(self, callback: types.CallbackQuery) -> None:
        group_id = int(callback.message.chat.id)
        user = callback.from_user
        await self._ensure_player(user)
        game = self.runtime.state.active_game(group_id)
        if not game or game.get("status") != Phase.LOBBY.value:
            await callback.answer("❌ لابی فعال نیست.", show_alert=True)
            return
        snapshot = self.runtime.lobby_snapshot(group_id)
        if any(int(row["player_id"]) == user.id for row in snapshot.get("players", [])):
            await callback.answer("⚠️ شما قبلاً وارد شده‌اید.", show_alert=True)
            return
        scenario = (snapshot.get("game") or {}).get("scenario_id")
        occupied = self._players_by_seat(group_id)
        maximum = self._max_players(scenario)
        if len(occupied) >= maximum:
            self.runtime.lobby.join(group_id, user.id, None)
            await callback.answer("📌 ظرفیت پر است؛ به لیست رزرو اضافه شدید.")
        else:
            seat = next(seat for seat in range(1, maximum + 1) if seat not in occupied)
            self.runtime.lobby.join(group_id, user.id, seat)
            await callback.answer(f"✅ صندلی {seat} برای شما ثبت شد.")
        await self._render_lobby(group_id)

    async def leave(self, callback: types.CallbackQuery) -> None:
        group_id = int(callback.message.chat.id)
        self.runtime.lobby.leave(group_id, callback.from_user.id)
        await self._render_lobby(group_id)
        await callback.answer("❌ از بازی خارج شدید.")

    async def choose_scenario(self, callback: types.CallbackQuery) -> None:
        group_id = int(callback.message.chat.id)
        scenarios = InlineKeyboardMarkup(row_width=1)
        for name in self.scenarios:
            scenarios.add(InlineKeyboardButton(name, callback_data=f"scenario:{name}"))
        await callback.message.edit_text("📝 سناریو را انتخاب کنید:", reply_markup=scenarios)
        await callback.answer()

    async def scenario_selected(self, callback: types.CallbackQuery) -> None:
        group_id = int(callback.message.chat.id)
        scenario = callback.data.split(":", 1)[1]
        if scenario not in self.scenarios:
            await callback.answer("⚠️ سناریو وجود ندارد.", show_alert=True)
            return
        self.runtime.lobby.set_scenario(group_id, scenario)
        await self._render_lobby(group_id)
        await callback.answer("✅ سناریو انتخاب شد.")

    async def roles(self, callback: types.CallbackQuery) -> None:
        group_id = int(callback.message.chat.id)
        snapshot = self.runtime.lobby_snapshot(group_id)
        game = snapshot.get("game") or {}
        scenario = game.get("scenario_id")
        moderator_id = game.get("moderator_id")
        rows = self._players_by_seat(group_id)
        minimum = int((self.scenarios.get(scenario) or {}).get("min_players") or 0)
        if not scenario or len(rows) < minimum:
            await callback.answer("⚠️ شرایط پخش نقش کامل نیست.", show_alert=True)
            return
        if moderator_id and int(moderator_id) != callback.from_user.id:
            await callback.answer("⛔ فقط گرداننده می‌تواند نقش‌ها را پخش کند.", show_alert=True)
            return
        roles = self._scenario_roles(scenario)[:len(rows)]
        random.shuffle(roles)
        mapping: dict[int, str] = {}
        state = dict((game.get("state") or {}))
        players_in_game: dict[str, dict[str, Any]] = {}
        for role, (seat, row) in zip(roles, sorted(rows.items())):
            uid = int(row["player_id"])
            mapping[uid] = role
            players_in_game[str(seat)] = {"id": uid, "name": self._name(uid), "role": role}
            try:
                await self.bot.send_message(uid, f"🎭 نقش شما: <b>{html.escape(role)}</b>")
            except Exception:
                logging.warning("private role delivery failed for %s", uid)
        state["players_in_game"] = players_in_game
        state["turn_order"] = sorted(rows)
        state["last_role_map"] = {str(k): v for k, v in mapping.items()}
        self.runtime.state.games.update_game(game["id"], state=state, status=Phase.RUNNING.value)
        self.roles[group_id] = mapping
        await self._render_game_start(group_id)
        await callback.answer("✅ نقش‌ها پخش شد.")

    async def _render_game_start(self, group_id: int) -> None:
        rows = self._players_by_seat(group_id)
        text = "🎮 <b>بازی شروع شد</b>\n\n"
        for seat, row in sorted(rows.items()):
            uid = int(row["player_id"])
            text += f"{seat:02d}. <a href='tg://user?id={uid}'>{html.escape(self._name(uid))}</a>\n"
        kb = InlineKeyboardMarkup(row_width=1).add(
            InlineKeyboardButton("🎯 انتخاب سر صحبت", callback_data="choose_head"),
            InlineKeyboardButton("⚔ چالش روشن/خاموش", callback_data="toggle_challenge"),
        )
        msg = await self.bot.send_message(group_id, text, reply_markup=kb)
        self.ui.game_message_id = msg.message_id

    async def start_turn(self, group_id: int, seat: int, index: int, *, challenge: bool = False) -> None:
        rows = self._players_by_seat(group_id)
        row = rows.get(int(seat))
        if not row:
            return
        uid = int(row["player_id"])
        duration = DEFAULT_CHALLENGE_DURATION if challenge else DEFAULT_TURN_DURATION
        order = self._turn_order(group_id)
        self._persist_turn_pointer(group_id, order, index)
        turn = self.runtime.start_turn(
            group_id,
            max(1, index + 1),
            seat=int(seat),
            player_id=uid,
            turn_type="challenge" if challenge else "main",
            duration_seconds=duration,
            current_turn_index=index,
            state={"challenge": challenge},
        )
        text = f"{'⚔' if challenge else '🎙'} ⏳ {duration // 60:02d}:{duration % 60:02d}\n"
        text += f"نوبت <a href='tg://user?id={uid}'>{html.escape(self._name(uid))}</a> است."
        msg = await self.bot.send_message(
            group_id, text, reply_markup=self.turn_keyboard(int(seat), challenge)
        )
        self.ui.current_turn_message_id = msg.message_id
        if self.ui.turn_timer_task and not self.ui.turn_timer_task.done():
            self.ui.turn_timer_task.cancel()
        self.ui.turn_timer_task = asyncio.create_task(
            self._countdown(group_id, str(turn["id"]), int(seat), msg.message_id, duration, challenge)
        )

    def turn_keyboard(self, seat: int, challenge: bool = False) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(row_width=2).add(
            InlineKeyboardButton("⏭ نکست", callback_data=f"next:{seat}"),
            InlineKeyboardButton("⚔ چالش", callback_data=f"challenge:{seat}") if not challenge else InlineKeyboardButton("⚔ پایان چالش", callback_data=f"challenge_end:{seat}"),
        )

    async def _countdown(self, group_id: int, turn_id: str, seat: int, message_id: int, duration: int, challenge: bool) -> None:
        try:
            recovery = self.runtime.turns.recover(group_id)
            deadline = recovery.get("deadline_epoch") or (time.time() + duration)
            while True:
                current = self.runtime.current_turn(group_id)
                if not current or str(current.get("id")) != turn_id:
                    return
                remaining = max(0, int(deadline - time.time()))
                uid = self._players_by_seat(group_id).get(seat, {}).get("player_id")
                text = f"{'⚔' if challenge else '🎙'} ⏳ {remaining // 60:02d}:{remaining % 60:02d}\n"
                text += f"نوبت <a href='tg://user?id={uid}'>{html.escape(self._name(int(uid)))}</a> است."
                try:
                    await self.bot.edit_message_text(
                        text, group_id, message_id, parse_mode="HTML",
                        reply_markup=self.turn_keyboard(seat, challenge),
                    )
                except Exception:
                    pass
                if remaining <= 0:
                    break
                await asyncio.sleep(min(5, remaining))
            current = self.runtime.current_turn(group_id)
            if current and str(current.get("id")) == turn_id:
                self.runtime.finish_turn(turn_id, {"finish_reason": "timer_expired"})
                await self._advance(group_id)
        except asyncio.CancelledError:
            return

    async def _advance(self, group_id: int) -> None:
        order = self._turn_order(group_id)
        index = self._current_index(group_id) + 1
        if index >= len(order):
            await self.bot.send_message(
                group_id,
                "✅ همه بازیکنان صحبت کردند. فاز روز پایان یافت.",
                reply_markup=InlineKeyboardMarkup().add(
                    InlineKeyboardButton("🌙 شروع شب", callback_data="start_night")
                ),
            )
            return
        await self.start_turn(group_id, order[index], index)

    async def next_turn(self, callback: types.CallbackQuery) -> None:
        group_id = int(callback.message.chat.id)
        now = time.monotonic()
        if now - self.ui.last_next_at < 3:
            await callback.answer("⏳ کمی صبر کنید.", show_alert=True)
            return
        self.ui.last_next_at = now
        seat = int(callback.data.split(":", 1)[1])
        current_index = self._current_index(group_id)
        order = self._turn_order(group_id)
        if not order or current_index >= len(order) or int(order[current_index]) != seat:
            await callback.answer("⚠️ این نوبت دیگر فعال نیست.", show_alert=True)
            return
        current = self.runtime.current_turn(group_id)
        if current:
            self.runtime.finish_turn(str(current["id"]), {"finish_reason": "manual_next"})
        if self.ui.turn_timer_task and not self.ui.turn_timer_task.done():
            self.ui.turn_timer_task.cancel()
        await self._advance(group_id)
        await callback.answer("⏭ نوبت بعدی")

    async def choose_head(self, callback: types.CallbackQuery) -> None:
        group_id = int(callback.message.chat.id)
        game = self.runtime.state.active_game(group_id)
        if not game or int(game.get("moderator_id") or 0) != callback.from_user.id:
            await callback.answer("⛔ فقط گرداننده.", show_alert=True)
            return
        rows = self._players_by_seat(group_id)
        kb = InlineKeyboardMarkup(row_width=2)
        for seat, row in sorted(rows.items()):
            kb.add(InlineKeyboardButton(self._name(int(row["player_id"])), callback_data=f"head:{seat}"))
        await callback.message.edit_text("🎯 سر صحبت را انتخاب کنید:", reply_markup=kb)
        await callback.answer()

    async def set_head(self, callback: types.CallbackQuery) -> None:
        group_id = int(callback.message.chat.id)
        seat = int(callback.data.split(":", 1)[1])
        order = self._turn_order(group_id)
        if seat not in order:
            await callback.answer("⚠️ صندلی معتبر نیست.", show_alert=True)
            return
        start = order.index(seat)
        order = order[start:] + order[:start]
        self._persist_turn_pointer(group_id, order, 0)
        await callback.message.edit_text("🎯 سر صحبت انتخاب شد. برای شروع روی دکمه زیر بزنید.", reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("▶ شروع دور", callback_data="start_round")))
        await callback.answer()

    async def start_round(self, callback: types.CallbackQuery) -> None:
        group_id = int(callback.message.chat.id)
        order = self._turn_order(group_id)
        if not order:
            await callback.answer("⚠️ ترتیب نوبت مشخص نیست.", show_alert=True)
            return
        await self.start_turn(group_id, order[0], 0)
        await callback.answer("▶ دور شروع شد.")

    async def start_night(self, callback: types.CallbackQuery) -> None:
        group_id = int(callback.message.chat.id)
        game = self.runtime.state.active_game(group_id)
        if not game or int(game.get("moderator_id") or 0) != callback.from_user.id:
            await callback.answer("⛔ فقط گرداننده.", show_alert=True)
            return
        self.runtime.start_night(group_id)
        await callback.message.answer("🌙 فاز شب شروع شد.", reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("🌞 روز جدید", callback_data="new_day")))
        await callback.answer()

    async def new_day(self, callback: types.CallbackQuery) -> None:
        group_id = int(callback.message.chat.id)
        game = self.runtime.state.active_game(group_id)
        if not game or int(game.get("moderator_id") or 0) != callback.from_user.id:
            await callback.answer("⛔ فقط گرداننده.", show_alert=True)
            return
        self.runtime.start_new_day(group_id, extra={"turn_order": [], "current_turn_index": 0})
        await callback.message.answer("🌞 روز جدید شروع شد.", reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("🎯 انتخاب سر صحبت", callback_data="choose_head")))
        await callback.answer()

    async def toggle_challenge(self, callback: types.CallbackQuery) -> None:
        group_id = int(callback.message.chat.id)
        self.challenge_enabled[group_id] = not self.challenge_enabled.get(group_id, True)
        await callback.answer("⚔ چالش " + ("روشن شد." if self.challenge_enabled[group_id] else "خاموش شد."))

    async def challenge(self, callback: types.CallbackQuery) -> None:
        group_id = int(callback.message.chat.id)
        if not self.challenge_enabled.get(group_id, True):
            await callback.answer("⚔ چالش خاموش است.", show_alert=True)
            return
        target_seat = int(callback.data.split(":", 1)[1])
        target = self._players_by_seat(group_id).get(target_seat)
        if not target:
            await callback.answer("⚠️ بازیکن پیدا نشد.", show_alert=True)
            return
        challenger_id = callback.from_user.id
        target_id = int(target["player_id"])
        if challenger_id == target_id:
            await callback.answer("❌ نمی‌توانید خودتان را به چالش بکشید.", show_alert=True)
            return
        challenge = self.runtime.create_challenge(group_id, challenger_id, target_id, "before", pause_main_turn=True)
        await self.bot.send_message(group_id, f"⚔ درخواست چالش از {html.escape(self._name(challenger_id))} برای {html.escape(self._name(target_id))} ثبت شد.")
        await callback.answer("⚔ درخواست ثبت شد.")

    async def challenge_end(self, callback: types.CallbackQuery) -> None:
        group_id = int(callback.message.chat.id)
        active = self.runtime.challenges.active(group_id)
        if active:
            self.runtime.resolve_challenge(group_id, str(active[-1]["id"]), "resolved", resume_main_turn=True)
        await callback.answer("⚔ چالش پایان یافت.")

    async def cancel_game(self, callback: types.CallbackQuery) -> None:
        group_id = int(callback.message.chat.id)
        game = self.runtime.state.active_game(group_id)
        if not game or int(game.get("moderator_id") or 0) != callback.from_user.id:
            await callback.answer("⛔ فقط گرداننده.", show_alert=True)
            return
        self.runtime.state.games.update_game(game["id"], status=Phase.FINISHED.value)
        if self.ui.turn_timer_task and not self.ui.turn_timer_task.done():
            self.ui.turn_timer_task.cancel()
        await callback.message.edit_text("🚫 بازی لغو شد.")
        await callback.answer("بازی لغو شد.")

    async def help(self, callback: types.CallbackQuery) -> None:
        await callback.message.edit_text(
            "📖 <b>راهنما</b>\n\n"
            "🎮 بازی جدید — ساخت لابی\n"
            "✅ ورود — ورود به بازی\n"
            "🎭 پخش نقش — اختصاص نقش‌ها\n"
            "🎯 انتخاب سر صحبت — تعیین اولین نوبت\n"
            "⏭ نکست — پایان نوبت\n"
            "⚔ چالش — ثبت چالش\n"
            "🌙 شروع شب / 🌞 روز جدید — تغییر فاز بازی",
            reply_markup=self._keyboard_main(),
        )
        await callback.answer()

    async def startup(self) -> None:
        await self.bot.delete_webhook(drop_pending_updates=True)
        plans = await self.recovery.start()
        logging.info("recovered %d persisted turn plans", len(plans))

    async def shutdown(self) -> None:
        await self.recovery.stop()
        await self.bot.session.close()

    def _register_handlers(self) -> None:
        self.dp.register_callback_query_handler(self.new_game, lambda c: c.data == "new_game")
        self.dp.register_callback_query_handler(self.join, lambda c: c.data == "join")
        self.dp.register_callback_query_handler(self.leave, lambda c: c.data == "leave")
        self.dp.register_callback_query_handler(self.choose_scenario, lambda c: c.data == "choose_scenario")
        self.dp.register_callback_query_handler(self.scenario_selected, lambda c: c.data.startswith("scenario:"))
        self.dp.register_callback_query_handler(self.roles, lambda c: c.data == "roles")
        self.dp.register_callback_query_handler(self.choose_head, lambda c: c.data == "choose_head")
        self.dp.register_callback_query_handler(self.set_head, lambda c: c.data.startswith("head:"))
        self.dp.register_callback_query_handler(self.start_round, lambda c: c.data == "start_round")
        self.dp.register_callback_query_handler(self.next_turn, lambda c: c.data.startswith("next:"))
        self.dp.register_callback_query_handler(self.toggle_challenge, lambda c: c.data == "toggle_challenge")
        self.dp.register_callback_query_handler(self.challenge, lambda c: c.data.startswith("challenge:"))
        self.dp.register_callback_query_handler(self.challenge_end, lambda c: c.data.startswith("challenge_end:"))
        self.dp.register_callback_query_handler(self.start_night, lambda c: c.data == "start_night")
        self.dp.register_callback_query_handler(self.new_day, lambda c: c.data == "new_day")
        self.dp.register_callback_query_handler(self.cancel_game, lambda c: c.data == "cancel_game")
        self.dp.register_callback_query_handler(self.help, lambda c: c.data == "help")
        self.dp.register_message_handler(self._start_command, commands=["start"])

    async def _start_command(self, message: types.Message) -> None:
        if message.chat.type == "private":
            await message.answer("📋 منوی ربات:", reply_markup=self._keyboard_main())
        else:
            await message.answer("🏠 منوی بازی:", reply_markup=self._keyboard_main())


TOKEN = os.getenv("API_TOKEN")
if not TOKEN:
    raise ValueError("API_TOKEN environment variable is not set!")

app = MafiaApplication(TOKEN)
bot = app.bot
dp = app.dp


async def on_startup(dp: Dispatcher) -> None:
    await app.startup()


async def on_shutdown(dp: Dispatcher) -> None:
    await app.shutdown()


if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup, on_shutdown=on_shutdown)
