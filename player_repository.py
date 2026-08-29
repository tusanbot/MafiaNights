import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


class PlayerRepository:
    """دسترسی متمرکز به جدول mafia_players."""

    def __init__(self, database_url=None):
        self.database_url = database_url or os.getenv("DATABASE_URL")
        if not self.database_url:
            raise RuntimeError("DATABASE_URL تنظیم نشده است")

        url = self.database_url
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+psycopg2://", 1)
        elif url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg2://", 1)

        self.engine = create_engine(url, pool_pre_ping=True)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)

    def upsert(self, user_id, full_name=None, username=None):
        """ثبت بازیکن یا به‌روزرسانی اطلاعات پایه او."""
        user_id = int(user_id)
        full_name = (full_name or "").strip() or None
        username = (username or "").strip() or None

        first_name = None
        last_name = None
        if full_name:
            parts = full_name.split(None, 1)
            first_name = parts[0]
            last_name = parts[1] if len(parts) > 1 else None

        with self.SessionLocal() as session:
            session.execute(
                text("""
                    insert into public.mafia_players
                        (id, username, first_name, last_name, updated_at)
                    values
                        (:id, :username, :first_name, :last_name, now())
                    on conflict (id) do update set
                        username = coalesce(excluded.username, public.mafia_players.username),
                        first_name = coalesce(excluded.first_name, public.mafia_players.first_name),
                        last_name = coalesce(excluded.last_name, public.mafia_players.last_name),
                        updated_at = now()
                """),
                {
                    "id": user_id,
                    "username": username,
                    "first_name": first_name,
                    "last_name": last_name,
                },
            )
            session.commit()

    def get(self, user_id):
        with self.SessionLocal() as session:
            row = session.execute(
                text("""
                    select id, username, first_name, last_name, nickname
                    from public.mafia_players
                    where id = :id
                """),
                {"id": int(user_id)},
            ).mappings().first()
            return dict(row) if row else None

    def get_display_name(self, user_id, fallback="❓"):
        row = self.get(user_id)
        if not row:
            return fallback
        return row.get("nickname") or fallback

    def set_nickname(self, user_id, nickname):
        nickname = (nickname or "").strip()
        if not nickname:
            return False

        with self.SessionLocal() as session:
            result = session.execute(
                text("""
                    update public.mafia_players
                    set nickname = :nickname, updated_at = now()
                    where id = :id
                """),
                {"id": int(user_id), "nickname": nickname},
            )
            session.commit()
            return result.rowcount > 0

    def delete_nickname(self, user_id):
        with self.SessionLocal() as session:
            result = session.execute(
                text("""
                    update public.mafia_players
                    set nickname = null, updated_at = now()
                    where id = :id
                """),
                {"id": int(user_id)},
            )
            session.commit()
            return result.rowcount > 0

    def all_nicknames(self):
        with self.SessionLocal() as session:
            rows = session.execute(
                text("""
                    select id, nickname
                    from public.mafia_players
                    where nickname is not null and trim(nickname) <> ''
                    order by lower(nickname)
                """)
            ).mappings().all()
            return {int(row["id"]): row["nickname"] for row in rows}
