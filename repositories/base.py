import os
import socket
from urllib.parse import urlparse

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


class DatabaseRepository:
    """Shared PostgreSQL connection used by Mafia repositories.

    Some Vercel workers resolve Supabase's direct database hostname to IPv6 while
    the runtime has no usable IPv6 route. psycopg2 then fails with
    ``Cannot assign requested address`` instead of falling back to IPv4. Resolve
    the hostname once and pass ``hostaddr`` so the connection is deterministic.
    """

    def __init__(self, database_url=None):
        database_url = database_url or os.getenv("DATABASE_URL")
        if not database_url:
            raise RuntimeError("DATABASE_URL تنظیم نشده است")

        if database_url.startswith("postgres://"):
            database_url = database_url.replace("postgres://", "postgresql+psycopg2://", 1)
        elif database_url.startswith("postgresql://"):
            database_url = database_url.replace("postgresql://", "postgresql+psycopg2://", 1)

        connect_args = {}
        try:
            host = urlparse(database_url).hostname
            if host:
                connect_args["hostaddr"] = socket.gethostbyname(host)
        except (OSError, ValueError):
            # Keep normal hostname resolution as a fallback for non-DNS/local DBs.
            pass

        self.engine = create_engine(
            database_url,
            pool_pre_ping=True,
            connect_args=connect_args,
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
