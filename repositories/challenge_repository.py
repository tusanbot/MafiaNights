from sqlalchemy import text
from .base import DatabaseRepository


class ChallengeRepository(DatabaseRepository):
    """Persistence for mafia_challenges."""

    def create_challenge(self, game_id, challenger_id, target_id, mode, status="pending"):
        """Create a challenge on both the current and legacy mafia_challenges schemas.

        Production has historically used a wider legacy table with required
        user_id/seat metadata. Build the INSERT from the columns actually
        present so the challenge lifecycle remains compatible during schema
        migration instead of failing on a legacy NOT NULL column.
        """
        with self.SessionLocal() as session:
            columns = {
                str(row[0])
                for row in session.execute(text("""
                    select column_name
                    from information_schema.columns
                    where table_schema='public'
                      and table_name='mafia_challenges'
                """)).all()
            }
            values = {
                "game_id": game_id,
                "challenger_id": int(challenger_id),
                "target_id": int(target_id),
                "mode": mode,
                "status": status,
                "user_id": int(challenger_id),
                "target_user_id": int(target_id),
            }
            # Legacy challenge tables sometimes require a generic user_id.
            # It represents the requester, so challenger_id is the canonical
            # value for that compatibility column.
            insert_columns = [
                key for key in (
                    "game_id", "challenger_id", "target_id", "mode",
                    "status", "user_id", "target_user_id"
                ) if key in columns
            ]
            if not insert_columns:
                raise RuntimeError("mafia_challenges schema is unavailable")
            names = ", ".join(insert_columns)
            binds = ", ".join(f":{key}" for key in insert_columns)
            row = session.execute(
                text(f"insert into public.mafia_challenges ({names}) values ({binds}) returning id"),
                {key: values[key] for key in insert_columns},
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
