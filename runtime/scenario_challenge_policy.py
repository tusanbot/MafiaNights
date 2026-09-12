"""Scenario-driven challenge quotas.

The quota is intentionally scoped to the game unit selected by the scenario:
- limited: one challenge request per player per round/day;
- free: one challenge request per player per active speaking turn.

The quota is stored in game.state, so it survives bot restarts and does not
need a separate reset job. A new scope key automatically gives the player a
new allowance.
"""
from __future__ import annotations

from typing import Any, Optional

from repositories.scenario_repository import ScenarioRepository


class ScenarioChallengePolicy:
    def __init__(self, app: Any):
        self.app = app
        self.scenarios = ScenarioRepository()

    def _game(self, group_id: int) -> Optional[dict[str, Any]]:
        return self.app.runtime.state.active_game(int(group_id))

    def _config(self, game: dict[str, Any]) -> dict[str, Any]:
        cfg = game.get("scenario_config")
        if isinstance(cfg, dict):
            return cfg
        scenario_id = game.get("scenario_id")
        if not scenario_id:
            return {}
        row = self.scenarios.get_by_id(int(scenario_id))
        cfg = (row or {}).get("config") or {}
        if isinstance(cfg, str):
            import json
            try:
                cfg = json.loads(cfg)
            except Exception:
                cfg = {}
        return cfg if isinstance(cfg, dict) else {}

    def mode(self, group_id: int) -> str:
        game = self._game(group_id)
        if not game:
            return "limited"
        mode = str(self._config(game).get("challenge_mode") or "limited").lower()
        return "free" if mode == "free" else "limited"

    def scope_key(self, group_id: int, player_id: int) -> tuple[str, str]:
        game = self._game(group_id)
        if not game:
            return "limited", f"unknown:player:{int(player_id)}"

        mode = self.mode(group_id)
        state = dict(game.get("state") or {})
        if mode == "free":
            turn = self.app.runtime.current_turn(group_id)
            turn_id = str((turn or {}).get("id") or "")
            return mode, f"turn:{turn_id}:player:{int(player_id)}"

        day_number = int(state.get("day_number") or 1)
        return mode, f"round:{day_number}:player:{int(player_id)}"

    def check(self, group_id: int, player_id: int) -> tuple[bool, str, str]:
        game = self._game(group_id)
        if not game:
            return False, "🚫 بازی فعالی وجود ندارد.", ""

        mode, key = self.scope_key(group_id, player_id)
        if mode == "free" and key.startswith("turn::"):
            return False, "⚠️ چالش آزاد فقط در نوبت فعال صحبت قابل استفاده است.", key

        usage = dict((game.get("state") or {}).get("challenge_usage") or {})
        if usage.get(key):
            if mode == "free":
                return False, "⚠️ در این نوبت صحبت قبلاً یک چالش گرفته‌اید.", key
            return False, "⚠️ در این دور قبلاً یک چالش گرفته‌اید.", key
        return True, "", key

    def mark(self, group_id: int, player_id: int, key: str, mode: str) -> bool:
        game = self._game(group_id)
        if not game or not key:
            return False
        state = dict(game.get("state") or {})
        usage = dict(state.get("challenge_usage") or {})
        usage[key] = {
            "player_id": int(player_id),
            "scope": mode,
        }
        state["challenge_usage"] = usage
        game["state"] = state
        return bool(self.app.runtime.state.games.update_game(game["id"], state=state))
