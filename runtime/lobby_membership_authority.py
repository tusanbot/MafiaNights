"""Canonical persistent player membership authority for an active Mafia lobby.

The database-backed lobby runtime is the only source of truth for membership,
seat assignment and waiting/reservation state. UI modules call this boundary;
they do not manipulate legacy globals.
"""
from __future__ import annotations

import logging
from typing import Any


class LobbyMembershipAuthority:
    def __init__(self, app: Any):
        self.app = app

    @property
    def lobby(self):
        return self.app.runtime.state.lobby

    @property
    def games(self):
        return self.app.runtime.state.games

    def rows(self, game_id: int) -> list[dict[str, Any]]:
        return self.games.list_players(int(game_id))

    def player(self, game_id: int, player_id: int) -> dict[str, Any] | None:
        uid = int(player_id)
        return next((row for row in self.rows(game_id) if int(row.get("player_id") or 0) == uid), None)

    def join(self, game_id: int, player_id: int, seat: int | None, *, substitute: bool = False) -> Any:
        uid = int(player_id)
        current = self.player(game_id, uid)
        if current and str(current.get("status") or "") not in {"removed", "finished", "kicked", "dead"}:
            if seat is not None and current.get("seat") is None:
                return self.assign_seat(game_id, uid, seat)
            return current
        if current:
            reactivate = getattr(self.games, "reactivate_player", None)
            if reactivate is not None and reactivate(int(game_id), uid, seat, bool(substitute)):
                return self.player(game_id, uid)
        return self.lobby.join(int(game_id), uid, seat, is_substitute=bool(substitute))

    def leave(self, game_id: int, player_id: int) -> bool:
        return bool(self.lobby.leave(int(game_id), int(player_id)))

    def assign_seat(self, game_id: int, player_id: int, seat: int) -> Any:
        return self.lobby.assign_seat(int(game_id), int(player_id), int(seat))

    def promote_waiting(self, game_id: int, seat: int | None = None) -> Any:
        if seat is None:
            return self.lobby.promote_waiting(int(game_id))
        return self.lobby.promote_waiting(int(game_id), int(seat))

    def ensure_consistency(self, game_id: int) -> dict[str, int]:
        """Report membership invariants without rewriting user state."""
        rows = self.rows(game_id)
        active = [
            row for row in rows
            if row.get("seat") is not None
            and str(row.get("status") or "active") not in {"removed", "dead", "finished", "kicked"}
        ]
        waiting = [
            row for row in rows
            if row.get("seat") is None
            and str(row.get("status") or "waiting") in {"waiting", "substitute"}
        ]
        seen: set[int] = set()
        duplicate_seats = 0
        for row in active:
            seat = int(row["seat"])
            if seat in seen:
                duplicate_seats += 1
            seen.add(seat)
        return {
            "total_rows": len(rows),
            "active": len(active),
            "waiting": len(waiting),
            "duplicate_seats": duplicate_seats,
        }


def install(app: Any) -> LobbyMembershipAuthority:
    existing = getattr(app, "lobby_membership", None)
    if existing is not None:
        return existing
    authority = LobbyMembershipAuthority(app)
    app.lobby_membership = authority
    logging.info("LOBBY MEMBERSHIP AUTHORITY active: source=mafia_game_players")
    return authority
