"""Normalize private admin-menu authorization.

Private callback messages have chat.type=private, so the group id cannot be
inferred from callback.message. The legacy bot already has a single allowed
group in ALLOWED_GROUP_ID; use it as the authoritative fallback.
"""
from __future__ import annotations

from runtime.admin_menus_v2 import AdminMenusV2


async def _is_group_admin(self, uid: int) -> bool:
    gid = getattr(self.app, "group_chat_id", None) or getattr(self.app, "ALLOWED_GROUP_ID", None)
    if not gid:
        gid = getattr(self.app, "GROUP_ID", None)
    if not gid:
        gid = getattr(self.app, "group_id", None)
    if not gid:
        return False
    try:
        admins = await self.bot.get_chat_administrators(int(gid))
        return any(a.user.id == uid for a in admins)
    except Exception:
        return False


def install(app):
    # Patch the class before/after an instance is created; Python method lookup
    # will use this implementation for all AdminMenusV2 instances.
    AdminMenusV2._is_group_admin = _is_group_admin
    return True
