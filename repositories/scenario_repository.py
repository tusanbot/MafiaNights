from uuid import UUID

from sqlalchemy import text
from .base import DatabaseRepository


class ScenarioId(str):
    """Canonical UUID scenario id with legacy integer callback compatibility."""

    def __new__(cls, value):
        return super().__new__(cls, str(value))

    def __int__(self):
        raw = str(self).strip()
        try:
            return UUID(raw).int
        except (TypeError, ValueError, AttributeError):
            return int(raw)


class ScenarioRepository(DatabaseRepository):
    """Persistence for mafia_scenarios with UUID/numeric compatibility."""

    @staticmethod
    def _scenario_id(value):
        if value is None:
            return None
        if isinstance(value, int):
            try:
                return str(UUID(int=value))
            except (ValueError, OverflowError):
                return str(value)
        raw = str(value).strip()
        if not raw:
            return None
        try:
            return str(UUID(raw))
        except (TypeError, ValueError, AttributeError):
            try:
                numeric = int(raw)
                # UUID integer representation used by legacy callback handlers.
                if numeric > 2**63:
                    return str(UUID(int=numeric))
                return str(numeric)
            except (TypeError, ValueError, OverflowError):
                return raw

    @staticmethod
    def _wrap(row):
        value = dict(row) if row else None
        if value and value.get("id") is not None:
            value["id"] = ScenarioId(value["id"])
        return value

    def list_active(self):
        with self.SessionLocal() as session:
            rows = session.execute(text(
                "select id, name, description, min_players, max_players, roles, config "
                "from public.mafia_scenarios where is_active = true "
                "order by sort_order nulls last, id"
            )).mappings().all()
            return [self._wrap(row) for row in rows]

    def get_by_name(self, name):
        with self.SessionLocal() as session:
            row = session.execute(text(
                "select * from public.mafia_scenarios where name = :name limit 1"
            ), {"name": name}).mappings().first()
            return self._wrap(row)

    def get_by_id(self, scenario_id):
        scenario_id = self._scenario_id(scenario_id)
        if not scenario_id:
            return None
        with self.SessionLocal() as session:
            row = session.execute(text(
                "select * from public.mafia_scenarios where id = :scenario_id limit 1"
            ), {"scenario_id": scenario_id}).mappings().first()
            return self._wrap(row)

    def upsert(self, name, description=None, min_players=None, max_players=None, roles=None, config=None, is_active=True):
        import json
        with self.SessionLocal() as session:
            row = session.execute(text(
                "insert into public.mafia_scenarios "
                "(name, description, min_players, max_players, roles, config, is_active, sort_order, updated_at) "
                "values (:name, :description, :min_players, :max_players, cast(:roles as jsonb), "
                "cast(:config as jsonb), :is_active, "
                "coalesce((select max(sort_order) + 1 from public.mafia_scenarios), 0), now()) "
                "on conflict (name) do update set description = excluded.description, "
                "min_players = excluded.min_players, max_players = excluded.max_players, "
                "roles = excluded.roles, config = excluded.config, is_active = excluded.is_active, "
                "updated_at = now() returning id"
            ), {
                "name": name, "description": description, "min_players": min_players,
                "max_players": max_players, "roles": json.dumps(roles or [], ensure_ascii=False),
                "config": json.dumps(config or {}, ensure_ascii=False), "is_active": is_active,
            }).scalar_one()
            session.commit()
            return str(row)

    def update_by_id(self, scenario_id, name, description=None, min_players=None, max_players=None, roles=None, config=None, is_active=True):
        import json
        scenario_id = self._scenario_id(scenario_id)
        if not scenario_id:
            raise ValueError("scenario id is required")
        with self.SessionLocal() as session:
            row = session.execute(text(
                "update public.mafia_scenarios set name=:name, description=:description, "
                "min_players=:min_players, max_players=:max_players, roles=cast(:roles as jsonb), "
                "config=cast(:config as jsonb), is_active=:is_active, updated_at=now() "
                "where id=:id returning id"
            ), {
                "id": scenario_id, "name": name, "description": description,
                "min_players": min_players, "max_players": max_players,
                "roles": json.dumps(roles or [], ensure_ascii=False),
                "config": json.dumps(config or {}, ensure_ascii=False),
                "is_active": is_active,
            }).scalar_one_or_none()
            if row is None:
                raise ValueError("scenario not found")
            session.commit()
            return str(row)

    def set_active(self, scenario_id, is_active=False):
        scenario_id = self._scenario_id(scenario_id)
        if not scenario_id:
            raise ValueError("scenario id is required")
        with self.SessionLocal() as session:
            row = session.execute(text(
                "update public.mafia_scenarios set is_active=:active, updated_at=now() "
                "where id=:id returning id"
            ), {"id": scenario_id, "active": bool(is_active)}).scalar_one_or_none()
            if row is None:
                raise ValueError("scenario not found")
            session.commit()
            return str(row)
