import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


class DatabaseRepository:
    """Shared PostgreSQL connection used by Mafia repositories."""

    def __init__(self, database_url=None):
        database_url = database_url or os.getenv("DATABASE_URL")
        if not database_url:
            raise RuntimeError("DATABASE_URL تنظیم نشده است")

        if database_url.startswith("postgres://"):
            database_url = database_url.replace("postgres://", "postgresql+psycopg2://", 1)
        elif database_url.startswith("postgresql://"):
            database_url = database_url.replace("postgresql://", "postgresql+psycopg2://", 1)

        self.engine = create_engine(database_url, pool_pre_ping=True)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
