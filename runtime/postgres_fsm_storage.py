"""PostgreSQL-backed aiogram FSM storage for webhook/serverless runtimes.

Vercel may execute consecutive Telegram webhook updates in different Python
workers. aiogram's MemoryStorage is therefore unsafe for multi-step flows.
This storage keeps state/data/bucket in PostgreSQL so every webhook invocation
sees the same FSM session.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from sqlalchemy import create_engine, text


class PostgresFSMStorage:
    """Small aiogram-2-compatible storage implemented on the existing DB."""

    def __init__(self, database_url: str | None = None):
        url = database_url or os.getenv("DATABASE_URL")
        if not url:
            raise RuntimeError("DATABASE_URL تنظیم نشده است")
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+psycopg2://", 1)
        elif url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
        self.engine = create_engine(url, pool_pre_ping=True)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with self.engine.begin() as conn:
            conn.execute(text("""
                create table if not exists public.mafia_fsm_state (
                    chat_id text not null,
                    user_id text not null,
                    state text,
                    data jsonb not null default '{}'::jsonb,
                    bucket jsonb not null default '{}'::jsonb,
                    updated_at timestamptz not null default now(),
                    primary key (chat_id, user_id)
                )
            """))

    @staticmethod
    def _ids(chat: Any, user: Any) -> tuple[str, str]:
        return str(chat), str(user)

    def _ensure_row(self, chat: Any, user: Any) -> None:
        chat_id, user_id = self._ids(chat, user)
        with self.engine.begin() as conn:
            conn.execute(text("""
                insert into public.mafia_fsm_state(chat_id, user_id)
                values (:chat_id, :user_id)
                on conflict (chat_id, user_id) do nothing
            """), {"chat_id": chat_id, "user_id": user_id})

    async def get_state(self, *, chat: Any, user: Any, default: Any = None):
        self._ensure_row(chat, user)
        chat_id, user_id = self._ids(chat, user)
        with self.engine.begin() as conn:
            value = conn.execute(text("select state from public.mafia_fsm_state where chat_id=:chat_id and user_id=:user_id"),
                                 {"chat_id": chat_id, "user_id": user_id}).scalar()
        return default if value is None else value

    async def set_state(self, *, chat: Any, user: Any, state: Any = None):
        chat_id, user_id = self._ids(chat, user)
        self._ensure_row(chat, user)
        with self.engine.begin() as conn:
            conn.execute(text("update public.mafia_fsm_state set state=:state, updated_at=now() where chat_id=:chat_id and user_id=:user_id"),
                         {"chat_id": chat_id, "user_id": user_id, "state": state})

    async def get_data(self, *, chat: Any, user: Any, default: Any = None):
        self._ensure_row(chat, user)
        chat_id, user_id = self._ids(chat, user)
        with self.engine.begin() as conn:
            value = conn.execute(text("select data from public.mafia_fsm_state where chat_id=:chat_id and user_id=:user_id"),
                                 {"chat_id": chat_id, "user_id": user_id}).scalar()
        return dict(value or (default or {}))

    async def set_data(self, *, chat: Any, user: Any, data: dict | None = None):
        chat_id, user_id = self._ids(chat, user)
        self._ensure_row(chat, user)
        with self.engine.begin() as conn:
            conn.execute(text("update public.mafia_fsm_state set data=:data::jsonb, updated_at=now() where chat_id=:chat_id and user_id=:user_id"),
                         {"chat_id": chat_id, "user_id": user_id, "data": json.dumps(data or {}, ensure_ascii=False)})

    async def update_data(self, *, chat: Any, user: Any, **kwargs):
        data = await self.get_data(chat=chat, user=user)
        data.update(kwargs)
        await self.set_data(chat=chat, user=user, data=data)
        return data

    async def reset_state(self, *, chat: Any, user: Any, with_data: bool = False):
        chat_id, user_id = self._ids(chat, user)
        self._ensure_row(chat, user)
        with self.engine.begin() as conn:
            if with_data:
                conn.execute(text("update public.mafia_fsm_state set state=null, data='{}'::jsonb, updated_at=now() where chat_id=:chat_id and user_id=:user_id"),
                             {"chat_id": chat_id, "user_id": user_id})
            else:
                conn.execute(text("update public.mafia_fsm_state set state=null, updated_at=now() where chat_id=:chat_id and user_id=:user_id"),
                             {"chat_id": chat_id, "user_id": user_id})

    async def finish(self, *, chat: Any, user: Any):
        await self.reset_state(chat=chat, user=user, with_data=True)

    async def get_bucket(self, *, chat: Any, user: Any, default: Any = None):
        self._ensure_row(chat, user)
        chat_id, user_id = self._ids(chat, user)
        with self.engine.begin() as conn:
            value = conn.execute(text("select bucket from public.mafia_fsm_state where chat_id=:chat_id and user_id=:user_id"),
                                 {"chat_id": chat_id, "user_id": user_id}).scalar()
        return dict(value or (default or {}))

    async def set_bucket(self, *, chat: Any, user: Any, bucket: dict | None = None):
        chat_id, user_id = self._ids(chat, user)
        self._ensure_row(chat, user)
        with self.engine.begin() as conn:
            conn.execute(text("update public.mafia_fsm_state set bucket=:bucket::jsonb, updated_at=now() where chat_id=:chat_id and user_id=:user_id"),
                         {"chat_id": chat_id, "user_id": user_id, "bucket": json.dumps(bucket or {}, ensure_ascii=False)})

    async def update_bucket(self, *, chat: Any, user: Any, **kwargs):
        bucket = await self.get_bucket(chat=chat, user=user)
        bucket.update(kwargs)
        await self.set_bucket(chat=chat, user=user, bucket=bucket)
        return bucket

    async def reset_bucket(self, *, chat: Any, user: Any):
        await self.set_bucket(chat=chat, user=user, bucket={})

    async def close(self):
        self.engine.dispose()

    async def wait_closed(self):
        return None


def install(app) -> bool:
    if getattr(app, "_postgres_fsm_storage_installed", False):
        return False
    try:
        storage = PostgresFSMStorage()
    except Exception:
        logging.exception("PostgreSQL FSM storage could not be initialized; keeping existing storage")
        return False
    app.dp.storage = storage
    app._postgres_fsm_storage = storage
    app._postgres_fsm_storage_installed = True
    logging.info("PostgreSQL FSM storage installed")
    return True
