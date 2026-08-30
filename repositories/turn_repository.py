import json
from sqlalchemy import text
from .base import DatabaseRepository


class TurnRepository(DatabaseRepository):
    """Authoritative persistence for mafia_game_turns and game turn pointer."""

    def start_turn(self, game_id, turn_number, seat=None, player_id=None,
                   turn_type="main", duration_seconds=None, state=None,
                   current_turn_index=None):
        """Create a turn and advance the game's pointer atomically."""
        payload = json.dumps(state or {}, ensure_ascii=False)
        with self.SessionLocal() as session:
            with session.begin():
                game = session.execute(
                    text("select id, status from public.mafia_games where id=:game_id for update"),
                    {"game_id": game_id},
                ).mappings().first()
                if not game:
                    raise ValueError("بازی پیدا نشد")
                if game["status"] not in ("running", "paused"):
                    raise ValueError("بازی در وضعیت اجرای نوبت نیست")

                row = session.execute(
                    text("""
                        insert into public.mafia_game_turns
                            (game_id, turn_number, seat, player_id, turn_type,
                             duration_seconds, state, started_at)
                        values
                            (:game_id, :turn_number, :seat, :player_id, :turn_type,
                             :duration_seconds, :state::jsonb, now())
                        returning id, game_id, turn_number, seat, player_id,
                                  turn_type, duration_seconds, started_at, ended_at, state
                    """),
                    {"game_id": game_id, "turn_number": int(turn_number), "seat": seat,
                     "player_id": player_id, "turn_type": turn_type,
                     "duration_seconds": duration_seconds, "state": payload},
                ).mappings().one()

                fields = {"current_turn_seat": seat}
                if current_turn_index is not None:
                    fields["current_turn_index"] = int(current_turn_index)
                assignments = ["current_turn_seat=:seat", "updated_at=now()"]
                params = {"game_id": game_id, "seat": seat}
                if "current_turn_index" in fields:
                    assignments.append("current_turn_index=:idx")
                    params["idx"] = fields["current_turn_index"]
                session.execute(
                    text(f"update public.mafia_games set {', '.join(assignments)} where id=:game_id"),
                    params,
                )
                return dict(row)

    def finish_turn(self, turn_id, state=None):
        payload = json.dumps(state or {}, ensure_ascii=False)
        with self.SessionLocal() as session:
            with session.begin():
                row = session.execute(
                    text("select id, game_id from public.mafia_game_turns where id=:turn_id for update"),
                    {"turn_id": turn_id},
                ).mappings().first()
                if not row:
                    return False
                result = session.execute(
                    text("""
                        update public.mafia_game_turns
                        set ended_at=now(), state=:state::jsonb
                        where id=:turn_id and ended_at is null
                    """),
                    {"turn_id": turn_id, "state": payload},
                )
                return result.rowcount > 0

    def current_turn(self, game_id):
        with self.SessionLocal() as session:
            row = session.execute(
                text("""
                    select * from public.mafia_game_turns
                    where game_id=:game_id and ended_at is null
                    order by started_at desc
                    limit 1
                """), {"game_id": game_id}).mappings().first()
            return dict(row) if row else None

    def list_turns(self, game_id):
        with self.SessionLocal() as session:
            rows = session.execute(
                text("""
                    select * from public.mafia_game_turns
                    where game_id=:game_id
                    order by turn_number, started_at
                """), {"game_id": game_id}).mappings().all()
            return [dict(row) for row in rows]
