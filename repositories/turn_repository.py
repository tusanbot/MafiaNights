from sqlalchemy import text
from .base import DatabaseRepository


class TurnRepository(DatabaseRepository):
    """Persistence for mafia_game_turns."""

    def create_turn(self, game_id, turn_number, seat=None, player_id=None, turn_type="main", duration_seconds=None, state=None):
        with self.SessionLocal() as session:
            row = session.execute(
                text("""
                    insert into public.mafia_game_turns
                        (game_id, turn_number, seat, player_id, turn_type, duration_seconds, state, started_at)
                    values
                        (:game_id, :turn_number, :seat, :player_id, :turn_type, :duration_seconds, :state::jsonb, now())
                    returning id
                """),
                {
                    "game_id": game_id,
                    "turn_number": turn_number,
                    "seat": seat,
                    "player_id": player_id,
                    "turn_type": turn_type,
                    "duration_seconds": duration_seconds,
                    "state": __import__("json").dumps(state or {}, ensure_ascii=False),
                },
            ).scalar_one()
            session.commit()
            return row

    def finish_turn(self, turn_id, state=None):
        with self.SessionLocal() as session:
            result = session.execute(
                text("""
                    update public.mafia_game_turns
                    set ended_at = now(), state = :state::jsonb
                    where id = :turn_id
                """),
                {
                    "turn_id": turn_id,
                    "state": __import__("json").dumps(state or {}, ensure_ascii=False),
                },
            )
            session.commit()
            return result.rowcount > 0

    def list_turns(self, game_id):
        with self.SessionLocal() as session:
            rows = session.execute(
                text("""
                    select * from public.mafia_game_turns
                    where game_id = :game_id
                    order by turn_number, started_at
                """),
                {"game_id": game_id},
            ).mappings().all()
            return [dict(row) for row in rows]
