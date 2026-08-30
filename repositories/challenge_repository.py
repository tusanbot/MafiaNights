from sqlalchemy import text
from .base import DatabaseRepository


class ChallengeRepository(DatabaseRepository):
    """Persistence for mafia_challenges."""

    def create_challenge(self, game_id, challenger_id, target_id, mode, status="pending"):
        with self.SessionLocal() as session:
            row = session.execute(
                text("""
                    insert into public.mafia_challenges
                        (game_id, challenger_id, target_id, mode, status)
                    values
                        (:game_id, :challenger_id, :target_id, :mode, :status)
                    returning id
                """),
                {
                    "game_id": game_id,
                    "challenger_id": int(challenger_id),
                    "target_id": int(target_id),
                    "mode": mode,
                    "status": status,
                },
            ).scalar_one()
            session.commit()
            return row

    def update_mode(self, challenge_id, mode):
        with self.SessionLocal() as session:
            result = session.execute(
                text("""
                    update public.mafia_challenges
                    set mode = :mode
                    where id = :challenge_id
                """),
                {"challenge_id": challenge_id, "mode": mode},
            )
            session.commit()
            return result.rowcount > 0

    def resolve_challenge(self, challenge_id, status):
        with self.SessionLocal() as session:
            result = session.execute(
                text("""
                    update public.mafia_challenges
                    set status = :status, resolved_at = now()
                    where id = :challenge_id
                """),
                {"challenge_id": challenge_id, "status": status},
            )
            session.commit()
            return result.rowcount > 0

    def list_challenges(self, game_id):
        with self.SessionLocal() as session:
            rows = session.execute(
                text("""
                    select * from public.mafia_challenges
                    where game_id = :game_id
                    order by created_at
                """), {"game_id": game_id}).mappings().all()
            return [dict(row) for row in rows]
