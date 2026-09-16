"""Authoritative scenario adapter used by the live game runtime."""
from __future__ import annotations
import json
from typing import Any, Optional
from sqlalchemy import text
from repositories.scenario_repository import ScenarioRepository

class ScenarioRuntime:
    def __init__(self, app: Any):
        self.app = app
        self.repo = ScenarioRepository()

    @staticmethod
    def _config(row):
        value = row.get("config") or {}
        if isinstance(value, str):
            try: value = json.loads(value)
            except Exception: value = {}
        return value if isinstance(value, dict) else {}

    def get(self, scenario_id: Optional[str]):
        if not scenario_id: return None
        row = self.repo.get_by_id(str(scenario_id))
        if not row or not row.get("is_active", True): return None
        row = dict(row); row["id"] = str(row["id"]); row["config"] = self._config(row); row["roles"] = list(row.get("roles") or [])
        return row

    def snapshot(self, scenario_id: Optional[str]):
        row = self.get(scenario_id)
        if not row: return None
        cfg = row["config"]
        return {"id": str(row["id"]), "name": row.get("name"), "description": row.get("description"),
                "min_players": int(row.get("min_players") or 0), "max_players": int(row.get("max_players") or len(row["roles"])),
                "roles": row["roles"], "role_rules": cfg.get("roles") or {}, "sides": cfg.get("sides") or {},
                "challenge_mode": "free" if cfg.get("challenge_mode") == "free" else "limited",
                "challenge_limit": cfg.get("challenge_limit"), "settings": cfg.get("settings") or {}}

    def apply_to_game(self, game_id: str, scenario_id: str, group_id: Optional[int] = None):
        scenario = self.snapshot(str(scenario_id))
        if not scenario: raise ValueError("سناریوی انتخاب‌شده معتبر یا فعال نیست")
        games = self.app.runtime.state.games
        group_id = group_id if group_id is not None else getattr(self.app, "group_chat_id", None)
        game = None
        if group_id is not None:
            try: game = self.app.runtime.state.active_game(int(group_id))
            except Exception: game = None
        if not game:
            try: game = games.get_game(game_id)
            except Exception: game = None
        if not game: raise ValueError("بازی پیدا نشد")
        state = dict(game.get("state") or {})
        state.update({"scenario": scenario,
                      "scenario_config": {"roles": scenario["role_rules"], "sides": scenario["sides"],
                                          "challenge_mode": scenario["challenge_mode"], "challenge_limit": scenario["challenge_limit"],
                                          "settings": scenario["settings"]},
                      "scenario_name": scenario["name"], "challenge_usage": {}})
        persisted = False
        if group_id is not None:
            with games.SessionLocal() as session:
                result = session.execute(text("""
                    update public.mafia_games
                    set scenario_id=:scenario_id, state=cast(:state as jsonb), updated_at=now()
                    where id=(select id from public.mafia_games
                              where group_chat_id=:group_chat_id and status in ('lobby','running','paused')
                              order by created_at desc limit 1)
                """), {"scenario_id": str(scenario_id), "state": json.dumps(state, ensure_ascii=False), "group_chat_id": int(group_id)})
                session.commit(); persisted = result.rowcount > 0
        if not persisted:
            persisted = games.update_game(game["id"], scenario_id=str(scenario_id), state=state)
        if not persisted: raise ValueError("ذخیره سناریو روی بازی انجام نشد")
        games._active_cache.clear()
        try: games._invalidate(game_id=game["id"])
        except Exception: pass
        return scenario

    def current(self, group_id: int):
        game = self.app.runtime.state.active_game(group_id)
        if not game: return None
        cached = dict(game.get("state") or {}).get("scenario")
        return cached if isinstance(cached, dict) and cached.get("id") else self.snapshot(game.get("scenario_id"))
