"""Compatibility persistence for Mafia voting records.

Production workers can temporarily point at an older database schema. The
repository therefore discovers the installed mafia_votes schema once per
worker and supports both the current round_no schema and the legacy round
schema, as well as UUID/integer game identifiers.
"""
from __future__ import annotations

import logging
import uuid

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from .base import DatabaseRepository


class VotingRepository(DatabaseRepository):
    _schema_cache = None

    def _schema(self):
        if self.__class__._schema_cache is not None:
            return self.__class__._schema_cache
        with self.SessionLocal() as session:
            rows = session.execute(
                text(
                    """
                    select column_name, data_type
                    from information_schema.columns
                    where table_schema='public' and table_name='mafia_votes'
                    """
                )
            ).mappings().all()
        cols = {str(r["column_name"]): str(r["data_type"]) for r in rows}
        if not cols:
            raise RuntimeError("public.mafia_votes وجود ندارد")
        round_col = "round_no" if "round_no" in cols else ("round" if "round" in cols else None)
        target_col = next((name for name in ("target_player_id", "target_id", "target_user_id", "target") if name in cols), None)
        voter_col = next((name for name in ("voter_player_id", "voter_id", "voter_user_id", "voter") if name in cols), None)
        voted_at_col = next((name for name in ("voted_at", "created_at", "timestamp") if name in cols), None)
        if round_col is None:
            raise RuntimeError("ستون دور در public.mafia_votes پیدا نشد")
        if target_col is None or voter_col is None:
            raise RuntimeError(f"ستون هدف/رأی‌دهنده در public.mafia_votes پیدا نشد: {sorted(cols)}")
        game_type = cols.get("game_id", "")
        schema = {"round_col": round_col, "target_col": target_col, "voter_col": voter_col, "voted_at_col": voted_at_col, "game_type": game_type}
        self.__class__._schema_cache = schema
        logging.info("VOTING DB SCHEMA columns=%s round_col=%s target_col=%s voter_col=%s voted_at_col=%s game_id_type=%s", sorted(cols), round_col, target_col, voter_col, voted_at_col, game_type)
        return schema

    def _game_value(self, game_id):
        game_type = self._schema()["game_type"]
        if "uuid" in game_type:
            return str(game_id)
        try:
            return int(game_id)
        except (TypeError, ValueError):
            return str(game_id)

    def clear_round(self, game_id, round_no: int) -> None:
        s = self._schema()
        with self.SessionLocal() as session:
            session.execute(
                text(
                    f"delete from public.mafia_votes "
                    f"where game_id=:game_id and {s['round_col']}=:round_no"
                ),
                {"game_id": self._game_value(game_id), "round_no": int(round_no)},
            )
            session.commit()

    def cast(self, game_id, round_no: int, target_player_id: int, voter_player_id: int, voted_at) -> bool:
        s = self._schema()
        params = {
            "game_id": self._game_value(game_id),
            "round_no": int(round_no),
            "target_player_id": int(target_player_id),
            "voter_player_id": int(voter_player_id),
            "voted_at": voted_at,
        }
        with self.SessionLocal() as session:
            try:
                existing = session.execute(
                    text(
                        f"""
                        select 1 from public.mafia_votes
                        where game_id=:game_id
                          and {s['round_col']}=:round_no
                          and {s['target_col']}=:target_player_id
                          and {s['voter_col']}=:voter_player_id
                        limit 1
                        """
                    ),
                    params,
                ).scalar()
                if existing:
                    session.rollback()
                    return False
                session.execute(
                    text(
                        f"""
                        insert into public.mafia_votes
                            (game_id, {s['round_col']}, {s['target_col']}, {s['voter_col']}{", " + s["voted_at_col"] if s.get("voted_at_col") else ""})
                        values
                            (:game_id, :round_no, :target_player_id, :voter_player_id{", :voted_at" if s.get("voted_at_col") else ""})
                        """
                    ),
                    params,
                )
                session.commit()
                return True
            except IntegrityError:
                session.rollback()
                return False

    def list_target(self, game_id, round_no: int, target_player_id: int) -> list[dict]:
        s = self._schema()
        with self.SessionLocal() as session:
            rows = session.execute(
                text(
                    f"""
                    select {s['voter_col']} as voter_player_id{", " + s["voted_at_col"] + " as voted_at" if s.get("voted_at_col") else ""}
                    from public.mafia_votes
                    where game_id=:game_id
                      and {s['round_col']}=:round_no
                      and {s['target_col']}=:target_player_id
                    {("order by " + s["voted_at_col"] + " asc") if s.get("voted_at_col") else ""}
                    """
                ),
                {
                    "game_id": self._game_value(game_id),
                    "round_no": int(round_no),
                    "target_player_id": int(target_player_id),
                },
            ).mappings().all()
            return [dict(row) for row in rows]

    def counts(self, game_id, round_no: int) -> dict[int, int]:
        s = self._schema()
        with self.SessionLocal() as session:
            rows = session.execute(
                text(
                    f"""
                    select {s['target_col']} as target_player_id, count(*) as vote_count
                    from public.mafia_votes
                    where game_id=:game_id and {s['round_col']}=:round_no
                    group by {s['target_col']}
                    """
                ),
                {"game_id": self._game_value(game_id), "round_no": int(round_no)},
            ).mappings().all()
            return {int(row["target_player_id"]): int(row["vote_count"]) for row in rows}

    def round_votes(self, game_id, round_no: int) -> list[dict]:
        s = self._schema()
        with self.SessionLocal() as session:
            rows = session.execute(
                text(
                    f"""
                    select {s['target_col']} as target_player_id, {s['voter_col']} as voter_player_id{", " + s["voted_at_col"] + " as voted_at" if s.get("voted_at_col") else ""}
                    from public.mafia_votes
                    where game_id=:game_id and {s['round_col']}=:round_no
                    order by voted_at asc
                    """
                ),
                {"game_id": self._game_value(game_id), "round_no": int(round_no)},
            ).mappings().all()
            return [dict(row) for row in rows]

    def cleanup_game(self, game_id) -> None:
        s = self._schema()
        with self.SessionLocal() as session:
            session.execute(
                text(
                    f"delete from public.mafia_votes where game_id=:game_id"
                ),
                {"game_id": self._game_value(game_id)},
            )
            session.commit()
