"""Backward-compatible profile DB access for mixed-schema deployments."""
from __future__ import annotations

import logging
from sqlalchemy import text


def install(profile_enhancements) -> bool:
    if profile_enhancements is None or getattr(profile_enhancements, "_profile_db_compat", False):
        return False

    original_profile = profile_enhancements._profile

    def safe_profile(uid: int):
        try:
            return original_profile(uid)
        except Exception as exc:
            # Some production DB connections can temporarily point at a schema
            # predating `gender`. The profile itself must remain usable.
            if "column \"gender\" does not exist" not in str(exc):
                raise
            logging.warning("profile DB compatibility fallback: gender column unavailable")
            with profile_enhancements._session() as s:
                row = s.execute(
                    text("select id,username,first_name,last_name,nickname from public.mafia_players where id=:id"),
                    {"id": int(uid)},
                ).mappings().first()
                if not row:
                    return None
                data = dict(row)
                data["gender"] = None
                return data

    profile_enhancements._profile = safe_profile
    profile_enhancements._profile_db_compat = True
    logging.info("PROFILE DB COMPATIBILITY ACTIVE")
    return True
