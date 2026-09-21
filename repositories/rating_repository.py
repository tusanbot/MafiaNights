from uuid import UUID

from sqlalchemy import text

from .base import DatabaseRepository

BASE_SCORE = 50

class RatingRepository(DatabaseRepository):
    @staticmethod
    def _game_uuid(session, game_id):
        raw=str(game_id).strip()
        try:return str(UUID(raw))
        except (TypeError,ValueError,AttributeError):
            row=session.execute(text("select id from public.mafia_games where event_number=:event_number limit 1"),{"event_number":int(raw)}).scalar_one_or_none()
            if row is None:raise ValueError("بازی پیدا نشد")
            return str(row)

    def record(self,user_id,game_id,score,result,role,*,win_bonus=0,challenge_bonus=0,warning_penalty=0,kick_penalty=0):
        with self.SessionLocal() as session:
            resolved_game_id=self._game_uuid(session,game_id)
            row=session.execute(text("""
                insert into public.mafia_ratings(user_id,game_id,score,changes,result,role,base_score,win_bonus,challenge_bonus,warning_penalty,kick_penalty)
                values(:user_id,:game_id,:score,:score,:result,:role,:base_score,:win_bonus,:challenge_bonus,:warning_penalty,:kick_penalty)
                on conflict (user_id,game_id) where user_id is not null and game_id is not null
                do update set score=excluded.score,changes=excluded.changes,result=excluded.result,role=excluded.role,base_score=excluded.base_score,win_bonus=excluded.win_bonus,challenge_bonus=excluded.challenge_bonus,warning_penalty=excluded.warning_penalty,kick_penalty=excluded.kick_penalty,updated_at=now()
                returning id
            """),{"user_id":int(user_id),"game_id":resolved_game_id,"score":int(score),"result":result,"role":role,"base_score":BASE_SCORE,"win_bonus":int(win_bonus),"challenge_bonus":int(challenge_bonus),"warning_penalty":int(warning_penalty),"kick_penalty":int(kick_penalty)}).scalar_one();session.commit();return row

    def game_score_details(self,user_id,game_id):
        """Return the score delta and result recorded for one game."""
        with self.SessionLocal() as session:
            resolved_game_id = self._game_uuid(session, game_id)
            row = session.execute(text("""
                select
                    coalesce(score,0)::int as score_delta,
                    coalesce(base_score,50)::int as base_score,
                    coalesce(win_bonus,0)::int as win_bonus,
                    coalesce(challenge_bonus,0)::int as challenge_bonus,
                    coalesce(warning_penalty,0)::int as warning_penalty,
                    coalesce(kick_penalty,0)::int as kick_penalty,
                    coalesce(result,'') as result,
                    coalesce(role,'') as role
                from public.mafia_ratings
                where user_id=:user_id and game_id=:game_id
                limit 1
            """), {"user_id": int(user_id), "game_id": resolved_game_id}).mappings().first()
            return dict(row) if row else {
                "score_delta": 0, "base_score": 50, "win_bonus": 0,
                "challenge_bonus": 0, "warning_penalty": 0,
                "kick_penalty": 0, "result": "", "role": ""
            }

    def player_summary(self,user_id):
        with self.SessionLocal() as session:
            row=session.execute(text("""
                with games as (select r.*,(coalesce(r.base_score,50)+coalesce(r.score,0))::numeric as game_score from public.mafia_ratings r where r.user_id=:user_id),
                achievements as (select coalesce(sum(reward_points),0)::int achievement_points from public.mafia_achievement_rewards where player_id=:user_id)
                select count(*)::int games,(50+coalesce(sum(games.score),0)+(select achievement_points from achievements))::int score,(select achievement_points from achievements)::int achievement_points,
                       count(*) filter(where result='win')::int wins,count(*) filter(where result='loss')::int losses,count(*) filter(where result='draw')::int draws,
                       coalesce(sum(win_bonus),0)::int win_bonus,coalesce(sum(challenge_bonus),0)::int challenge_bonus,coalesce(sum(warning_penalty),0)::int warning_penalty,coalesce(sum(kick_penalty),0)::int kick_penalty,
                       count(*) filter(where kick_penalty>0)::int kicks,coalesce(sum(challenge_bonus/3),0)::int challenges,coalesce(sum(warning_penalty),0)::int warnings,coalesce(max(score),0)::int best_game_delta,coalesce(avg(game_score),0)::numeric avg_game_score
                from games
            """),{"user_id":int(user_id)}).mappings().one();return dict(row)

    def player_profile(self,user_id):
        with self.SessionLocal() as session:
            row=session.execute(text("""
                with r as (select user_id,count(*) games,sum(score) score,count(*) filter(where result='win') wins,count(*) filter(where result='loss') losses,count(*) filter(where result='draw') draws from public.mafia_ratings group by user_id)
                select p.id,p.username,p.first_name,p.last_name,p.nickname,coalesce(r.games,0)::int games,
                       (50+coalesce(r.score,0)+(select coalesce(sum(ar.reward_points),0) from public.mafia_achievement_rewards ar where ar.player_id=p.id))::int score,
                       (select coalesce(sum(ar.reward_points),0) from public.mafia_achievement_rewards ar where ar.player_id=p.id)::int achievement_points,
                       coalesce(r.wins,0)::int wins,coalesce(r.losses,0)::int losses,coalesce(r.draws,0)::int draws
                from public.mafia_players p left join r on r.user_id=p.id where p.id=:user_id limit 1
            """),{"user_id":int(user_id)}).mappings().first();return dict(row) if row else None

    def rating_details(self,user_id):
        with self.SessionLocal() as session:
            row=session.execute(text("""
                with r as (select *, (coalesce(base_score,50)+coalesce(score,0))::numeric game_score from public.mafia_ratings where user_id=:user_id)
                select (50+coalesce(sum(score),0)+(select coalesce(sum(reward_points),0) from public.mafia_achievement_rewards where player_id=:user_id))::int score,
                       (select coalesce(sum(reward_points),0) from public.mafia_achievement_rewards where player_id=:user_id)::int achievement_points,
                       coalesce(sum(win_bonus),0)::int win_bonus,coalesce(sum(challenge_bonus),0)::int challenge_bonus,coalesce(sum(warning_penalty),0)::int warning_penalty,coalesce(sum(kick_penalty),0)::int kick_penalty,
                       count(*) filter(where challenge_bonus>0)::int challenge_games,coalesce(sum(challenge_bonus/3),0)::int challenges,count(*) filter(where warning_penalty>0)::int warning_games,coalesce(sum(warning_penalty),0)::int warnings,count(*) filter(where kick_penalty>0)::int kicks,coalesce(avg(game_score),0)::numeric avg_game_score
                from r
            """),{"user_id":int(user_id)}).mappings().one();return dict(row)

    def top(self, limit=10, metric="score", group_chat_id=None):
        """Return leaderboard rows ordered by one documented metric.

        score: accumulated rating + achievement rewards.
        average: arithmetic mean of per-game effective score (base + delta).
        win_rate: wins / completed rating rows.
        best_game: highest single-game score delta.
        """
        metric = str(metric or "score").strip().lower()
        if metric not in {"score", "average", "win_rate", "best_game"}:
            metric = "score"
        limit = max(1, min(int(limit), 10000))
        where = "where g.group_chat_id=:group_chat_id" if group_chat_id is not None else ""
        join = "join public.mafia_games g on g.id=r.game_id" if group_chat_id is not None else ""
        params = {"limit": limit}
        if group_chat_id is not None:
            params["group_chat_id"] = int(group_chat_id)
        order = {
            "score": "score desc, wins desc, games desc, p.id",
            "average": "avg_score desc, games desc, score desc, p.id",
            "win_rate": "win_rate desc, games desc, score desc, p.id",
            "best_game": "best_game desc, score desc, wins desc, p.id",
        }[metric]
        with self.SessionLocal() as session:
            rows=session.execute(text(f"""
                select p.id,coalesce(p.nickname,p.first_name,p.username,p.id::text) name,
                       count(r.id)::int games,
                       (50+coalesce(sum(r.score),0)+(select coalesce(sum(ar.reward_points),0) from public.mafia_achievement_rewards ar where ar.player_id=p.id))::int score,
                       (select coalesce(sum(ar.reward_points),0) from public.mafia_achievement_rewards ar where ar.player_id=p.id)::int achievement_points,
                       count(r.id) filter(where r.result='win')::int wins,
                       count(r.id) filter(where r.result='loss')::int losses,
                       count(r.id) filter(where r.result='draw')::int draws,
                       coalesce(avg(coalesce(r.base_score,50)+coalesce(r.score,0)),0)::numeric avg_score,
                       coalesce(100.0 * count(r.id) filter(where r.result='win') / nullif(count(r.id),0),0)::numeric win_rate,
                       coalesce(max(r.score),0)::int best_game
                from public.mafia_players p
                join public.mafia_ratings r on r.user_id=p.id
                {join}
                {where}
                group by p.id,p.nickname,p.first_name,p.username
                order by {order}
                limit :limit
            """),params).mappings().all()
            return [dict(row) for row in rows]

    def rank(self, user_id, metric="score"):
        metric = str(metric or "score").strip().lower()
        if metric not in {"score", "average", "win_rate", "best_game"}:
            metric = "score"
        rows = self.top(10000, metric)
        uid = int(user_id)
        for index, row in enumerate(rows, 1):
            if int(row["id"]) == uid:
                return {**row, "rank": index, "total_players": len(rows)}
        return {"rank": None, "score": BASE_SCORE, "games": 0, "wins": 0, "total_players": len(rows)}

    def group_summary(self,user_id,group_chat_id):
        with self.SessionLocal() as session:
            row=session.execute(text("""
                select count(*)::int games,(50+coalesce(sum(r.score),0)+(select coalesce(sum(ar.reward_points),0) from public.mafia_achievement_rewards ar where ar.player_id=:user_id))::int score,(select coalesce(sum(ar.reward_points),0) from public.mafia_achievement_rewards ar where ar.player_id=:user_id)::int achievement_points,
                       count(*) filter(where r.result='win')::int wins,count(*) filter(where r.result='loss')::int losses,count(*) filter(where r.result='draw')::int draws,
                       coalesce(sum(r.win_bonus),0)::int win_bonus,coalesce(sum(r.challenge_bonus),0)::int challenge_bonus,coalesce(sum(r.warning_penalty),0)::int warning_penalty,coalesce(sum(r.kick_penalty),0)::int kick_penalty,coalesce(avg(coalesce(r.base_score,50)+coalesce(r.score,0)),0)::numeric avg_game_score
                from public.mafia_ratings r join public.mafia_games g on g.id=r.game_id where r.user_id=:user_id and g.group_chat_id=:group_chat_id
            """),{"user_id":int(user_id),"group_chat_id":int(group_chat_id)}).mappings().one();return dict(row)

    def group_top(self, group_chat_id, limit=10, metric="score"):
        return self.top(limit=limit, metric=metric, group_chat_id=group_chat_id)
