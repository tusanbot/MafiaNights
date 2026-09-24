"""Canonical owner for Mafia lobby lifecycle: creation, scenario and moderator."""
from __future__ import annotations
import logging
from typing import Any


class LobbyLifecycleAuthority:
    def __init__(self, app: Any):
        self.app = app

    @property
    def runtime(self):
        return self.app.runtime

    def get(self, group_id: int):
        return self.runtime.state.active_game(int(group_id))

    def create(self, group_id: int, *, event_number: int | None = None):
        return self.runtime.lobby.start_new(int(group_id), event_number)

    def ensure(self, group_id: int, *, event_number: int | None = None):
        return self.runtime.lobby.ensure(int(group_id), event_number=event_number)

    def set_scenario(self, group_id: int, scenario_id: str) -> bool:
        return bool(self.runtime.lobby.set_scenario(int(group_id), str(scenario_id)))

    def set_moderator(self, group_id: int, moderator_id: int, moderator_name: str | None = None) -> bool:
        ok = bool(self.runtime.lobby.set_moderator(int(group_id), int(moderator_id)))
        if not ok:
            return False
        game = self.get(group_id)
        if game is not None:
            state = dict(game.get("state") or {})
            if moderator_name:
                state["moderator_name"] = str(moderator_name)
            state["lifecycle_owner"] = "lobby_lifecycle_authority"
            self.runtime.state.games.update_game(game["id"], state=state)
        return True

    def snapshot(self, group_id: int):
        return self.runtime.lobby.snapshot(int(group_id))


def install(app: Any) -> LobbyLifecycleAuthority:
    existing = getattr(app, "lobby_lifecycle", None)
    if existing is not None:
        return existing
    authority = LobbyLifecycleAuthority(app)
    app.lobby_lifecycle = authority
    logging.info("LOBBY LIFECYCLE AUTHORITY active: source=mafia_games")
    return authority
