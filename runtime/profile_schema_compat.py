"""Runtime schema compatibility for profile/stat features.

The production runtime database is currently older than the migration set used by
profile enhancements. This module upgrades only the additive columns required by
those features, without touching existing data.
"""
from __future__ import annotations

import logging

from sqlalchemy import text

from player_repository import PlayerRepository


_installed = False


def install(app=None):
    global _installed
    if _installed:
        return True
    repo = PlayerRepository()
    try:
        with repo.SessionLocal() as session:
            session.execute(text("alter table public.mafia_players add column if not exists gender text"))
            session.execute(text("alter table public.mafia_ratings add column if not exists win_bonus integer not null default 0"))
            session.execute(text("alter table public.mafia_ratings add column if not exists challenge_bonus integer not null default 0"))
            session.execute(text("alter table public.mafia_ratings add column if not exists warning_penalty integer not null default 0"))
            session.execute(text("alter table public.mafia_ratings add column if not exists kick_penalty integer not null default 0"))
            session.commit()
        _installed = True
        logging.info("PROFILE SCHEMA COMPATIBILITY ACTIVE: gender + rating bonus columns ensured")
        return True
    except Exception:
        logging.exception("PROFILE SCHEMA COMPATIBILITY FAILED")
        try:
            repo.SessionLocal().rollback()
        except Exception:
            pass
        return False
