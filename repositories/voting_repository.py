"""Atomic persistence for Mafia voting records.

Votes are intentionally stored outside mafia_games.state.  The unique
constraint makes a vote idempotent even when two Telegram callbacks arrive
concurrently.
"""
from __future__ import annotations

import uuid

from sqlalchemy import text

from .base import DatabaseRepository


class VotingRepository(DatabaseRepository):
    def clear_round(self, game_id, round_no: int) -> None:
        with self.SessionLocal() as session:
            session.execute(
                text(
                    "delete from public.mafia_votes "
                    "where game_id=:game_id and round_no=:round_no"
                ),
                {"game_id": str(game_id), "round_no": int(round_no)},
            )
            session.commit()

    def cast(self, game_id, round_no: int, target_player_id: int, voter_player_id: int, voted_at) -> bool:
        with self.SessionLocal() as session:
            row = session.execute(
                text(
                    """
                    insert into public.mafia_votes
                        (game_id, round_no, target_player_id, voter_player_id, voted_at)
                    values
                        (:game_id, :round_no, :target_player_id, :voter_player_id, :voted_at)
                    on conflict (game_id, round_no, target_player_id, voter_player_id)
                    do nothing
                    returning id
                    """
                ),
                {
                    "game_id": str(game_id),
                    "round_no": int(round_no),
                    "target_player_id": int(target_player_id),
                    "voter_player_id": int(voter_player_id),
                    "voted_at": voted_at,
                },
            ).scalar_one_or_none()
            session.commit()
            return row is not None

    def list_target(self, game_id, round_no: int, target_player_id: int) -> list[dict]:
        with self.SessionLocal() as session:
            rows = session.execute(
                text(
                    """
                    select voter_player_id, voted_at
                    from public.mafia_votes
                    where game_id=:game_id
                      and round_no=:round_no
                      and target_player_id=:target_player_id
                    order by voted_at asc
                    """
                ),
                {
                    "game_id": str(game_id),
                    "round_no": int(round_no),
                    "target_player_id": int(target_player_id),
                },
            ).mappings().all()
            return [dict(row) for row in rows]

    def counts(self, game_id, round_no: int) -> dict[int, int]:
        with self.SessionLocal() as session:
            rows = session.execute(
                text(
                    """
                    select target_player_id, count(*) as vote_count
                    from public.mafia_votes
                    where game_id=:game_id and round_no=:round_no
                    group by target_player_id
                    """
                ),
                {"game_id": str(game_id), "round_no": int(round_no)},
            ).mappings().all()
            return {int(row["target_player_id"]): int(row["vote_count"]) for row in rows}

    def round_votes(self, game_id, round_no: int) -> list[dict]:
        with self.SessionLocal() as session:
            rows = session.execute(
                text(
                    """
                    select target_player_id, voter_player_id, voted_at
                    from public.mafia_votes
                    where game_id=:game_id and round_no=:round_no
                    order by voted_at asc
                    """
                ),
                {"game_id": str(game_id), "round_no": int(round_no)},
            ).mappings().all()
            return [dict(row) for row in rows]

    def cleanup_game(self, game_id) -> None:
        with self.SessionLocal() as session:
            session.execute(
                text("delete from public.mafia_votes where game_id=:game_id"),
                {"game_id": str(game_id)},
            )
            session.commit()
