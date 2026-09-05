import os
import socket
from urllib.parse import urlparse

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool


class DatabaseRepository:
    """Shared PostgreSQL connection policy for long-lived and Vercel workers.

    Vercel workers are short-lived and can fan out horizontally. A normal
    SQLAlchemy QueuePool in every worker can therefore multiply idle DB
    connections. Serverless mode uses NullPool so each request returns the
    connection immediately; local/long-lived workers can opt into a small pool.
    """

    def __init__(self, database_url=None):
        database_url = database_url or os.getenv("DATABASE_URL")
        if not database_url:
            raise RuntimeError("DATABASE_URL تنظیم نشده است")

        if database_url.startswith("postgres://"):
            database_url = database_url.replace("postgres://", "postgresql+psycopg2://", 1)
        elif database_url.startswith("postgresql://"):
            database_url = database_url.replace("postgresql://", "postgresql+psycopg2://", 1)

        connect_args = {
            "connect_timeout": int(os.getenv("DB_CONNECT_TIMEOUT", "5")),
        }
        try:
            host = urlparse(database_url).hostname
            if host:
                connect_args["hostaddr"] = socket.gethostbyname(host)
        except (OSError, ValueError):
            pass

        serverless = (
            os.getenv("VERCEL") == "1"
            or os.getenv("VERCEL_ENV")
            or os.getenv("DB_POOL_MODE", "").lower() in {"null", "serverless"}
        )
        engine_kwargs = {
            "pool_pre_ping": True,
            "connect_args": connect_args,
        }
        if serverless:
            engine_kwargs["poolclass"] = NullPool
        else:
            engine_kwargs.update({
                "pool_size": int(os.getenv("DB_POOL_SIZE", "2")),
                "max_overflow": int(os.getenv("DB_MAX_OVERFLOW", "1")),
                "pool_recycle": int(os.getenv("DB_POOL_RECYCLE", "300")),
            })

        self.engine = create_engine(database_url, **engine_kwargs)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
