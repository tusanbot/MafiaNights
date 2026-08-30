from sqlalchemy import text
from .base import DatabaseRepository


class GameRepository(DatabaseRepository):
    """Persistence for mafia_games and mafia_game_players."""

    def create_game(self, group_chat_id, moderator_id=None, scenario_id=None, event_number=None, state=None):
        with self.SessionLocal() as session:
            row = session.execute(
                text("""
                    insert into public.mafia_games
                        (event_number, group_chat_id, moderator_id, scenario_id, status, state)
                    values
                        (:event_number, :group_chat_id, :moderator_id, :scenario_id, 'lobby', :state::jsonb)
                    returning id
                """),
                {"event_number": event_number, "group_chat_id": int(group_chat_id), "moderator_id": moderator_id,
                 "scenario_id": scenario_id, "state": __import__("json").dumps(state or {}, ensure_ascii=False)},
            ).scalar_one()
            session.commit()
            return row

    def get_active_game(self, group_chat_id):
        with self.SessionLocal() as session:
            row = session.execute(
                text("""
                    select * from public.mafia_games
                    where group_chat_id = :group_chat_id
                      and status in ('lobby', 'running', 'paused')
                    order by created_at desc
                    limit 1
                """), {"group_chat_id": int(group_chat_id)}).mappings().first()
            return dict(row) if row else None

    def update_game(self, game_id, **fields):
        allowed = {"moderator_id", "scenario_id", "status", "current_turn_seat", "current_turn_index",
                    "state", "started_at", "finished_at"}
        fields = {k: v for k, v in fields.items() if k in allowed}
        if not fields:
            return False
        params = {"game_id": game_id}
        assignments = []
        for key, value in fields.items():
            if key == "state":
                assignments.append("state = :state::jsonb")
                params[key] = __import__("json").dumps(value or {}, ensure_ascii=False)
            else:
                assignments.append(f"{key} = :{key}")
                params[key] = value
        assignments.append("updated_at = now()")
        with self.SessionLocal() as session:
            result = session.execute(text(f"update public.mafia_games set {', '.join(assignments)} where id = :game_id"), params)
            session.commit()
            return result.rowcount > 0

    def add_player(self, game_id, player_id, seat=None, role=None, status="active", is_substitute=False):
        with self.SessionLocal() as session:
            existing = session.execute(
                text("select id, seat, status, is_substitute from public.mafia_game_players where game_id=:game_id and player_id=:player_id limit 1"),
                {"game_id": game_id, "player_id": int(player_id)}).mappings().first()
            if existing:
                return existing["id"]
            if seat is not None:
                occupied = session.execute(
                    text("select 1 from public.mafia_game_players where game_id=:game_id and seat=:seat limit 1"),
                    {"game_id": game_id, "seat": int(seat)}).first()
                if occupied:
                    raise ValueError("این صندلی قبلاً رزرو شده است")
            row = session.execute(
                text("""insert into public.mafia_game_players
                    (game_id, player_id, seat, role, status, is_substitute)
                    values (:game_id,:player_id,:seat,:role,:status,:is_substitute) returning id"""),
                {"game_id": game_id, "player_id": int(player_id), "seat": seat, "role": role,
                 "status": status, "is_substitute": is_substitute}).scalar_one()
            session.commit()
            return row

    def list_players(self, game_id):
        with self.SessionLocal() as session:
            rows = session.execute(
                text("""select gp.*, p.username, p.first_name, p.last_name, p.nickname
                      from public.mafia_game_players gp
                      join public.mafia_players p on p.id = gp.player_id
                      where gp.game_id=:game_id
                      order by gp.seat nulls last, gp.joined_at"""), {"game_id": game_id}).mappings().all()
            return [dict(row) for row in rows]

    def remove_player(self, game_id, player_id):
        with self.SessionLocal() as session:
            result = session.execute(
                text("delete from public.mafia_game_players where game_id=:game_id and player_id=:player_id"),
                {"game_id": game_id, "player_id": int(player_id)})
            session.commit()
            return result.rowcount > 0

    def set_player_seat(self, game_id, player_id, seat):
        with self.SessionLocal() as session:
            if seat is not None:
                occupied = session.execute(
                    text("select player_id from public.mafia_game_players where game_id=:game_id and seat=:seat and player_id<>:player_id limit 1"),
                    {"game_id": game_id, "seat": int(seat), "player_id": int(player_id)}).first()
                if occupied:
                    raise ValueError("این صندلی قبلاً رزرو شده است")
            result = session.execute(
                text("update public.mafia_game_players set seat=:seat, status=:status where game_id=:game_id and player_id=:player_id"),
                {"game_id": game_id, "player_id": int(player_id), "seat": seat,
                 "status": "waiting" if seat is None else "active"})
            session.commit()
            return result.rowcount > 0

    def set_player_status(self, game_id, player_id, status):
        with self.SessionLocal() as session:
            result = session.execute(
                text("update public.mafia_game_players set status=:status where game_id=:game_id and player_id=:player_id"),
                {"game_id": game_id, "player_id": int(player_id), "status": status})
            session.commit()
            return result.rowcount > 0

    def promote_waiting_player(self, game_id, seat):
        with self.SessionLocal() as session:
            row = session.execute(
                text("""select id, player_id from public.mafia_game_players
                      where game_id=:game_id and seat is null and status='waiting'
                      order by joined_at limit 1"""), {"game_id": game_id}).mappings().first()
            if not row:
                return None
            occupied = session.execute(
                text("select 1 from public.mafia_game_players where game_id=:game_id and seat=:seat limit 1"),
                {"game_id": game_id, "seat": int(seat)}).first()
            if occupied:
                raise ValueError("این صندلی قبلاً رزرو شده است")
            session.execute(
                text("update public.mafia_game_players set seat=:seat, status='active' where id=:id"),
                {"id": row["id"], "seat": int(seat)})
            session.commit()
            return {"id": row["id"], "player_id": row["player_id"], "seat": int(seat)}
