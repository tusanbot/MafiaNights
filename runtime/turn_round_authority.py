"""Canonical persistent authority for turn order and round position.

StableRoundEngine remains the Telegram/UI transition executor. This boundary owns
the durable turn order/index/seat and roster hydration so Vercel workers never
treat process-local globals as authoritative.
"""
from __future__ import annotations
import logging
from typing import Any


class TurnRoundAuthority:
    def __init__(self, app: Any):
        self.app = app

    def game(self, group_id: int):
        return self.app.runtime.state.active_game(int(group_id))

    def hydrate(self, group_id: int):
        gid = int(group_id)
        game = self.game(gid)
        if not game:
            return None, []
        try:
            fresh = self.app.runtime.state.games.get_game(game["id"]) or game
        except Exception:
            fresh = game
        rows = [
            row for row in self.app.runtime.state.games.list_players(fresh["id"])
            if row.get("seat") is not None
            and str(row.get("status") or "active") not in {"removed", "dead", "finished", "kicked"}
        ]
        slots, players = {}, {}
        for row in rows:
            try:
                seat, uid = int(row["seat"]), int(row["player_id"])
            except (TypeError, ValueError):
                continue
            slots[seat] = uid
            players[uid] = str(row.get("nickname") or row.get("first_name") or row.get("username") or uid)
        self.app.player_slots = slots
        self.app.players = players
        state = dict(fresh.get("state") or {})
        order = []
        for raw in state.get("turn_order") or []:
            try:
                seat = int(raw)
            except (TypeError, ValueError):
                continue
            if seat in slots and seat not in order:
                order.append(seat)
        if not order:
            order = sorted(slots)
        raw_index = fresh.get("current_turn_index")
        if raw_index is None:
            raw_index = state.get("current_turn_index", 0)
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            index = 0
        if index < 0 or index > len(order):
            index = 0
        self.app.turn_order = list(order)
        self.app.current_turn_index = index
        self.app.current_turn_seat = (
            int(fresh.get("current_turn_seat"))
            if fresh.get("current_turn_seat") is not None else
            (int(order[index]) if index < len(order) else None)
        )
        return fresh, rows

    def persist_position(self, group_id: int, *, order=None, index=None, seat=None, extra_state=None) -> bool:
        game = self.game(int(group_id))
        if not game:
            return False
        state = dict(game.get("state") or {})
        if order is not None:
            state["turn_order"] = [int(x) for x in order]
        if index is not None:
            state["current_turn_index"] = int(index)
        if seat is not None:
            state["current_turn_seat"] = int(seat)
        elif index is not None and order is not None:
            state["current_turn_seat"] = int(order[int(index)]) if int(index) < len(order) else None
        if extra_state:
            state.update(extra_state)
        kwargs = {"state": state}
        if index is not None:
            kwargs["current_turn_index"] = int(index)
        if seat is not None:
            kwargs["current_turn_seat"] = int(seat)
        elif index is not None and order is not None:
            kwargs["current_turn_seat"] = int(order[int(index)]) if int(index) < len(order) else None
        return bool(self.app.runtime.state.games.update_game(game["id"], **kwargs))

    def snapshot(self, group_id: int) -> dict[str, Any]:
        game = self.game(int(group_id))
        if not game:
            return {"game": None, "turn_order": [], "current_turn_index": 0, "current_turn_seat": None}
        state = dict(game.get("state") or {})
        return {
            "game": game,
            "turn_order": [int(x) for x in (state.get("turn_order") or [])],
            "current_turn_index": game.get("current_turn_index", state.get("current_turn_index", 0)),
            "current_turn_seat": game.get("current_turn_seat", state.get("current_turn_seat")),
        }


def install(app: Any) -> TurnRoundAuthority:
    existing = getattr(app, "turn_round_authority", None)
    if existing is not None:
        return existing
    authority = TurnRoundAuthority(app)
    app.turn_round_authority = authority
    logging.info("TURN/ROUND AUTHORITY active: source=mafia_games + mafia_game_players")
    return authority
