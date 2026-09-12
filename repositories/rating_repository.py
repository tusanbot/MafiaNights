from sqlalchemy import text

from .base import DatabaseRepository


class RatingRepository(DatabaseRepository):
    """Persistence and aggregate queries for MafiaNights player ratings."""

    def record(self, user_id, game_id, score, result, role):
        with self.SessionLocal() as session:
            row = session.execute(
                text(
                    "insert into public.mafia_ratings(user_id, game_id, score, result, role) "
                    "values(:user_id,:game_id,:score,:result,:role) returning id"
                ),
                {
                    "user_id": int(user_id),
                    "game_id": int(game_id),
                    "score": int(score),
                    "result": result,
                    "role": role,
                },
            ).scalar_one()
            session.commit()
            return int(row)

    def player_summary(self, user_id):
        with self.SessionLocal() as session:
            row = session.execute(
                text(
                    "select count(*)::int as games, "
                    "coalesce(sum(score),0)::int as score, "
                    "count(*) filter (where result='win')::int as wins, "
                    "count(*) filter (where result='loss')::int as losses, "
                    "count(*) filter (where result='draw')::int as draws, "
                    "coalesce(max(score),0)::int as best_score "
                    "from public.mafia_ratings where user_id=:user_id"
                ),
                {"user_id": int(user_id)},
            ).mappings().one()
            return dict(row)

    def top(self, limit=10):
        with self.SessionLocal() as session:
            rows = session.execute(
                text(
                    "select r.user_id, "
                    "coalesce(p.nickname,p.display_name,p.first_name,p.username,r.user_id::text) as name, "
                    "count(*)::int as games, coalesce(sum(r.score),0)::int as score, "
                    "count(*) filter (where r.result='win')::int as wins "
                    "from public.mafia_ratings r "
                    "left join public.mafia_players p on p.user_id=r.user_id "
                    "group by r.user_id,p.nickname,p.display_name,p.first_name,p.username "
                    "order by score desc, wins desc, games desc, r.user_id "
                    "limit :limit"
                ),
                {"limit": max(1, min(int(limit), 100))},
            ).mappings().all()
            return [dict(row) for row in rows]
