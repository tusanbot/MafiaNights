"""Canonical player identity authority for the Production runtime.

This module is the single boundary for player registration/profile identity data.
During migration, legacy modules may remain in the repository, but Production
code should resolve identity through this authority instead of maintaining a
second nickname/profile source.
"""
from __future__ import annotations

import logging
from typing import Any

from player_repository import PlayerRepository


class PlayerIdentityAuthority:
    def __init__(self, repository: PlayerRepository | None = None):
        self.repo = repository or PlayerRepository()

    def get(self, user_id: int) -> dict[str, Any] | None:
        try:
            return self.repo.get(int(user_id))
        except Exception:
            logging.exception("player identity: get failed user_id=%s", user_id)
            return None

    def is_registered(self, user_id: int) -> bool:
        row = self.get(user_id)
        return bool(row and str(row.get("nickname") or "").strip())

    def display_name(self, user_id: int, fallback: str = "❓") -> str:
        try:
            return self.repo.get_display_name(int(user_id), fallback)
        except Exception:
            logging.exception("player identity: display_name failed user_id=%s", user_id)
            return fallback

    def ensure(self, user: Any) -> dict[str, Any] | None:
        if user is None or getattr(user, "id", None) is None:
            return None
        uid = int(user.id)
        self.repo.upsert(
            uid,
            getattr(user, "full_name", None),
            getattr(user, "username", None),
        )
        return self.get(uid)

    def register(
        self,
        user_id: int,
        nickname: str,
        *,
        username: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
    ) -> bool:
        return bool(
            self.repo.register(
                int(user_id),
                nickname,
                username=username,
                first_name=first_name,
                last_name=last_name,
            )
        )

    def set_nickname(self, user_id: int, nickname: str, *, ensure: bool = True) -> bool:
        if ensure:
            row = self.get(user_id)
            if row is None:
                self.repo.upsert(int(user_id))
        return bool(self.repo.set_nickname(int(user_id), nickname))

    def delete_nickname(self, user_id: int) -> bool:
        return bool(self.repo.delete_nickname(int(user_id)))

    def all_nicknames(self) -> dict[int, str]:
        return dict(self.repo.all_nicknames())


def install(app: Any) -> PlayerIdentityAuthority:
    existing = getattr(app, "player_identity", None)
    if existing is not None:
        return existing

    authority = PlayerIdentityAuthority()
    app.player_identity = authority
    app.display_name = authority.display_name
    app.is_registered = authority.is_registered
    logging.info("PLAYER IDENTITY AUTHORITY active: source=mafia_players")
    return authority
