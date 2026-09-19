from __future__ import annotations

import html
import logging
from typing import Any

from repositories.rating_repository import RatingRepository


def install(app: Any) -> bool:
    if getattr(app, "_dual_winner_support", False):
        return False
    app._dual_winner_support = True

    from runtime import game_end

    results = tuple(game_end.RESULTS)
    if not any(key == "city_independent" for key, _ in results):
        game_end.RESULTS = results + (("city_independent", "🏙 شهروند / 🟣 مستقل"),)

    original_score = game_end._score_players
    original_final_text = game_end._final_text

    def score_players(app_obj: Any, game: dict[str, Any], rows: list[dict[str, Any]], winner: str) -> None:
        if winner != "city_independent":
            original_score(app_obj, game, rows, winner)
            return

        repo = RatingRepository()
        state = dict(game.get("state") or {})
        recorded = set(str(x) for x in (state.get("rating_recorded_players") or []))
        for row in rows:
            uid = int(row["player_id"])
            key = str(uid)
            if key in recorded:
                continue
            side = game_end._role_side(row, state)
            score = game_end.WIN_SCORE if side in {"city", "independent"} else 0
            result = "win" if side in {"city", "independent"} else "loss"
            try:
                repo.record(uid, int(game["id"]), int(score), result, str(row.get("role") or ""))
                recorded.add(key)
            except Exception:
                logging.exception("failed to record dual-winner rating game=%s user=%s", game.get("id"), uid)
        state["rating_recorded_players"] = sorted(recorded)
        app_obj.runtime.state.games.update_game(game["id"], state=state)

    def final_text(game: dict[str, Any], rows: list[dict[str, Any]]) -> str:
        text = original_final_text(game, rows)
        winner = str(dict(game.get("state") or {}).get("game_result") or "")
        if winner != "city_independent":
            return text

        state = dict(game.get("state") or {})
        for row in rows:
            if game_end._role_side(row, state) not in {"city", "independent"}:
                continue
            name = html.escape(str(row.get("nickname") or row.get("first_name") or row.get("username") or row.get("player_id") or "👤"))
            role = html.escape(str(row.get("role") or "---"))
            plain = f"{name} — {role}"
            marked = f"<b>{name}</b> — {role} 🏆"
            text = text.replace(plain, marked, 1)
        return text

    game_end._score_players = score_players
    game_end._final_text = final_text
    return True
