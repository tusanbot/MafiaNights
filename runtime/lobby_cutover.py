"""Compatibility cut-over for the legacy lobby globals in main.py.

The legacy handlers remain responsible for Telegram UX, but every lobby
mutation is mirrored into the persistent lobby runtime after the handler and
state is hydrated from persistence before the next handler. This gives the
migration a safe, reversible boundary without duplicating callback logic.
"""
from __future__ import annotations

import logging
from typing import Any

from aiogram.dispatcher.middlewares import BaseMiddleware


class LobbyCutover:
    def __init__(self, main_module: Any, runtime: Any):
        self.main = main_module
        self.runtime = runtime

    @staticmethod
    def _user_id(item: Any):
        if isinstance(item, int):
            return int(item)
        if isinstance(item, dict):
            value = item.get("id", item.get("player_id"))
            return int(value) if value is not None else None
        return None

    def hydrate(self, group_id: int) -> dict[str, Any]:
        snapshot = self.runtime.lobby_snapshot(group_id)
        game = snapshot.get("game") or {}
        self.main.group_chat_id = int(group_id)
        self.main.moderator_id = game.get("moderator_id")
        self.main.selected_scenario = game.get("scenario_id")
        self.main.lobby_active = game.get("status") == "lobby"
        if not self.main.lobby_active:
            return snapshot

        players = snapshot.get("players") or []
        self.main.player_slots = {
            int(row["seat"]): int(row["player_id"])
            for row in players if row.get("seat") is not None
        }
        waiting = []
        for row in players:
            if row.get("seat") is None and row.get("status") == "waiting":
                waiting.append({"id": int(row["player_id"]),
                                "name": row.get("nickname") or row.get("first_name") or row.get("username") or str(row["player_id"])})
        self.main.waiting_list = type(self.main.waiting_list)(waiting)
        for row in players:
            uid = row.get("player_id")
            if uid is not None:
                self.main.players[int(uid)] = row.get("nickname") or row.get("first_name") or row.get("username") or str(uid)
        return snapshot

    def persist(self, group_id: int) -> dict[str, Any]:
        if getattr(self.main, "game_running", False) or not getattr(self.main, "lobby_active", False):
            return self.runtime.lobby_snapshot(group_id)

        moderator = getattr(self.main, "moderator_id", None)
        scenario = getattr(self.main, "selected_scenario", None)
        game = self.runtime.lobby.ensure(group_id, moderator, scenario)
        if moderator is not None:
            self.runtime.lobby.set_moderator(group_id, int(moderator))
        if scenario:
            self.runtime.lobby.set_scenario(group_id, str(scenario))

        represented: set[int] = set()
        slots = getattr(self.main, "player_slots", {}) or {}
        for seat, uid in slots.items():
            uid = int(uid)
            represented.add(uid)
            try:
                self.runtime.lobby.join(group_id, uid, int(seat), moderator, scenario)
            except ValueError:
                # A DB seat conflict is authoritative; leave it for the next
                # hydration rather than overwriting another player's seat.
                logging.warning("lobby seat conflict group=%s seat=%s user=%s", group_id, seat, uid)

        for item in getattr(self.main, "waiting_list", []) or []:
            uid = self._user_id(item)
            if uid is None:
                continue
            represented.add(uid)
            self.runtime.lobby.join(group_id, uid, None, moderator, scenario)

        # Only reconcile players while the game is genuinely in lobby. This
        # avoids deleting active game participants when legacy globals are
        # intentionally incomplete after the game starts.
        current = self.runtime.lobby.snapshot(group_id)
        for row in current.get("players", []):
            uid = row.get("player_id")
            if uid is not None and int(uid) not in represented:
                self.runtime.lobby.leave(group_id, int(uid))

        self.runtime.lobby.persist_legacy_state(group_id, state={
            "phase": "lobby",
            "waiting": [self._user_id(x) for x in (getattr(self.main, "waiting_list", []) or []) if self._user_id(x) is not None],
            "seat_count": len(slots),
        })
        return self.runtime.lobby_snapshot(group_id)


class LobbyPersistenceMiddleware(BaseMiddleware):
    """Hydrate lobby state before handlers and persist it after mutations."""

    def __init__(self, cutover: LobbyCutover):
        super().__init__()
        self.cutover = cutover

    @staticmethod
    def _group_id(obj: Any):
        message = getattr(obj, "message", None) or obj
        chat = getattr(message, "chat", None)
        chat_type = getattr(chat, "type", None)
        if chat_type not in {"group", "supergroup"}:
            return None
        return getattr(chat, "id", None)

    async def on_pre_process_update(self, update: Any, data: dict):
        group_id = self._group_id(update)
        if group_id is None:
            return
        try:
            self.cutover.hydrate(int(group_id))
        except Exception:
            logging.exception("lobby hydration failed for group %s", group_id)

    async def on_post_process_update(self, update: Any, result: Any, data: dict):
        group_id = self._group_id(update)
        if group_id is None:
            return
        try:
            self.cutover.persist(int(group_id))
        except Exception:
            logging.exception("lobby persistence failed for group %s", group_id)


def install_legacy_lobby_cutover(main_module: Any, runtime: Any) -> dict[str, Any]:
    """Install the lobby persistence boundary exactly once."""
    existing = getattr(main_module, "_persistent_lobby_cutover", None)
    if existing is not None:
        return existing
    cutover = LobbyCutover(main_module, runtime)
    middleware = LobbyPersistenceMiddleware(cutover)
    dp = getattr(main_module, "dp", None)
    if dp is not None:
        dp.middleware.setup(middleware)
    result = {"cutover": cutover, "middleware": middleware, "installed": dp is not None}
    main_module._persistent_lobby_cutover = result
    return result
