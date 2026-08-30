import os
from dataclasses import dataclass


@dataclass(frozen=True)
class DatabaseConfig:
    url: str
    pool_size: int = 5
    max_overflow: int = 10
    pool_timeout: int = 10


def get_database_config() -> DatabaseConfig | None:
    url = os.getenv("DATABASE_URL") or os.getenv("SUPABASE_DB_URL")
    if not url:
        return None
    return DatabaseConfig(url=url)
