"""Authoritative scenario adapter used by the live game runtime."""
from __future__ import annotations

import json
from typing import Any, Optional

from repositories.scenario_repository import ScenarioRepository


class ScenarioRuntime:
    """Resolve a persisted scenario and expose its gameplay configuration."""

    def __init__(self, app: Any):
        self.app = app
        self.repo = ScenarioRepository()

    @staticmethod
    def _config(row: dict[str, Any]) -> dict[str, Any]:
        value = row.get("config") or {}
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except Exception:
                value = {}
        return value if isinstance(value, dict) else {}

    def get(self, scenario_id: Optional[str]) -> Optional[dict[str, Any]]:
        if not scenario_id:
            return None
        row = self.repo.get_by_id(str(scenario_id))
        if not row or not row.get("is_active", True):
            return None
        row = dict(row)
        row["id"] = str(row["id"])
        row["config"] = self._config(row)
        row["roles"] = list(row.get("roles") or [])
        return row

    def snapshot(self, scenario_id: Optional[str]) -> Optional[dict[str, Any]]:
        row = self.get(scenario_id)
        if not row:
            return None
        cfg = row["config"]
        return {
            "id": str(row["id"]),
            "name": row.get("name"),
            "description": row.get("description"),
            "min_players": int(row.get("min_players") or 0),
            "max_players": int(row.get("max_players") or len(row["roles"])),
            "roles": row["roles"],
            "role_rules": cfg.get("roles") or {},
            "sides": cfg.get("sides") or {},
            "challenge_mode": "free" if cfg.get("challenge_mode") == "free" else "limited",
            "challenge_limit": cfg.get("challenge_limit"),
            "settings": cfg.get("settings") or {},
        }

    def apply_to_game(self, game_id: str, scenario_id: str) -> dict[str, Any]:
        scenario = self.snapshot(str(scenario_id))
        if not scenario:
            raise ValueError("سناریوی انتخاب‌شده معتبر یا فعال نیست")

        games = self.app.runtime.state.games
        game = None

        # The group chat is the authoritative context for a lobby callback.
        # Older lobby/private-recovery handlers may carry an event number or a
        # stale in-memory id instead of the canonical UUID. Prefer the active
        # game for the current group whenever that context is available.
        group_id = getattr(self.app, "group_chat_id", None)
        if group_id is not None:
            try:
                game = self.app.runtime.state.active_game(int(group_id))
            except Exception:
                game = None

        # Keep direct callers compatible: if no group context is available,
        # resolve the supplied game id normally.
        if not game:
            try:
                game = games.get_game(game_id)
            except Exception:
                game = None

        if not game:
            raise ValueError("بازی پیدا نشد")

        resolved_game_id = game["id"]
        state = dict(game.get("state") or {})
        state["scenario"] = scenario
        state["scenario_config"] = {
            "roles": scenario["role_rules"],
            "sides": scenario["sides"],
            "challenge_mode": scenario["challenge_mode"],
            "challenge_limit": scenario["challenge_limit"],
            "settings": scenario["settings"],
        }
        state["scenario_name"] = scenario["name"]
        state["challenge_usage"] = {}
        if not games.update_game(
            resolved_game_id,
            scenario_id=str(scenario_id),
            state=state,
        ):
            raise ValueError("ذخیره سناریو روی بازی انجام نشد")
        return scenario

    def current(self, group_id: int) -> Optional[dict[str, Any]]:
        game = self.app.runtime.state.active_game(group_id)
        if not game:
            return None
        state = dict(game.get("state") or {})
        cached = state.get("scenario")
        if isinstance(cached, dict) and cached.get("id"):
            return cached
        return self.snapshot(game.get("scenario_id"))
