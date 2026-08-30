"""Compatibility boundary for migrating the legacy Telegram turn flow."""
from __future__ import annotations

from typing import Any, Optional

from runtime.game_runtime import PersistentGameRuntime
from runtime.turn_runtime import PersistentTurnRuntime


class MigrationAdapter:
    """Bridge legacy Telegram callbacks to the persistent runtimes."""

    def __init__(
        self,
        game_runtime: Optional[PersistentGameRuntime] = None,
        turn_runtime: Optional[PersistentTurnRuntime] = None,
    ) -> None:
        self.game_runtime = game_runtime or PersistentGameRuntime()
        self.turn_runtime = turn_runtime or PersistentTurnRuntime(self.game_runtime.state)

    def ensure_legacy_game(
        self,
        group_chat_id: int,
        *,
        moderator_id: Optional[int] = None,
        scenario_id: Optional[str] = None,
        players: Optional[dict[int, str]] = None,
        player_slots: Optional[dict[int, int]] = None,
        turn_order: Optional[list[int]] = None,
        current_turn_index: int = 0,
    ) -> Any:
        """Materialize the active legacy game in the existing persistence layer."""
        game = self.game_runtime.state.active_game(group_chat_id)
        if not game:
            game = self.game_runtime.state.ensure_lobby(
                group_chat_id,
                moderator_id=moderator_id,
                scenario_id=scenario_id,
            )

        game_id = game.get("id")
        if not game_id:
            raise ValueError("شناسه بازی پایدار پیدا نشد")

        if moderator_id is not None:
            self.game_runtime.state.games.update_game(game_id, moderator_id=int(moderator_id))
        if scenario_id:
            self.game_runtime.state.games.update_game(game_id, scenario_id=scenario_id)

        slots = player_slots or {}
        legacy_players = players or {}
        for seat, player_id in sorted(slots.items()):
            try:
                self.game_runtime.state.games.add_player(
                    game_id=game_id,
                    player_id=int(player_id),
                    seat=int(seat),
                    status="active",
                )
            except Exception:
                continue

        state = {
            "legacy_players": {str(k): v for k, v in legacy_players.items()},
            "player_slots": {str(k): int(v) for k, v in slots.items()},
            "turn_order": [int(x) for x in (turn_order or [])],
            "current_turn_index": int(current_turn_index),
            "migration": "legacy_turn_bridge",
        }
        self.game_runtime.state.persist_lobby(
            game_id,
            state=state,
            current_turn_index=int(current_turn_index),
        )
        return self.game_runtime.state.active_game(group_chat_id) or game

    def persist_legacy_turn_start(
        self,
        group_chat_id: int,
        *,
        seat: int,
        duration_seconds: int = 120,
        is_challenge: bool = False,
        turn_order: Optional[list[int]] = None,
        current_turn_index: int = 0,
        players: Optional[dict[int, str]] = None,
        player_slots: Optional[dict[int, int]] = None,
        moderator_id: Optional[int] = None,
        scenario_id: Optional[str] = None,
    ) -> Any:
        """Persist a legacy turn before its existing Telegram UI/timer runs."""
        game = self.ensure_legacy_game(
            group_chat_id,
            moderator_id=moderator_id,
            scenario_id=scenario_id,
            players=players,
            player_slots=player_slots,
            turn_order=turn_order,
            current_turn_index=current_turn_index,
        )

        turn_number = max(1, int(current_turn_index) + 1)
        player_id = (player_slots or {}).get(seat)
        turn_type = "challenge" if is_challenge else "main"
        state = {
            "migration": "legacy_turn_bridge",
            "seat": int(seat),
            "player_id": int(player_id) if player_id is not None else None,
            "turn_order": [int(x) for x in (turn_order or [])],
            "current_turn_index": int(current_turn_index),
            "legacy_compatibility": True,
        }

        status = str((game or {}).get("status") or "lobby").lower()
        if status == "lobby":
            return self.game_runtime.start_first_turn(
                group_chat_id,
                seat=int(seat),
                turn_number=turn_number,
                duration_seconds=int(duration_seconds),
                current_turn_index=int(current_turn_index),
                player_id=int(player_id) if player_id is not None else None,
                state=state,
            )

        if status not in {"running", "paused", "turn"}:
            raise ValueError(f"شروع نوبت در وضعیت {status} ممکن نیست")

        return self.game_runtime.start_turn(
            group_chat_id,
            turn_number,
            seat=int(seat),
            player_id=int(player_id) if player_id is not None else None,
            turn_type=turn_type,
            duration_seconds=int(duration_seconds),
            current_turn_index=int(current_turn_index),
            state=state,
        )

    def start_first_turn(self, group_chat_id: int, *, seat: int, turn_number: int = 1,
                         duration_seconds: Optional[int] = None,
                         current_turn_index: int = 0,
                         player_id: Optional[int] = None,
                         state: Optional[dict[str, Any]] = None) -> Any:
        return self.game_runtime.start_first_turn(
            group_chat_id,
            seat=seat,
            turn_number=turn_number,
            duration_seconds=duration_seconds,
            current_turn_index=current_turn_index,
            player_id=player_id,
            state=state,
        )

    def current_turn(self, group_chat_id: int) -> Any:
        return self.turn_runtime.current(group_chat_id)

    def recover_turn(self, group_chat_id: int) -> dict[str, Any]:
        return self.turn_runtime.recover(group_chat_id)
