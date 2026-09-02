from __future__ import annotations

import logging
from functools import wraps


# Setup actions must be admin-only because a moderator does not exist yet.
_ADMIN_ONLY_EXACT = {
    "lv6_new",
    "manage_game",
    "manage_scenarios",
    "add_scenario",
    "remove_scenario",
    "back_main",
}

_ADMIN_ONLY_PREFIXES = (
    "lv6_s:",
    "lv6_m:",
    "delete_scen_",
    "scenario_",
    "moderator_",
)

# Game/lobby management may be performed by either a current moderator or a
# group administrator. This is also the security boundary for stale Telegram
# messages containing legacy callback_data.
_ADMIN_OR_MOD_EXACT = {
    "lv6_manage",
    "lv6_cancel",
    "lv6_change_s",
    "lv6_change_m",
    "lv6_challenge",
    "lv6_remove",
    "lv6_ready",
    "lv6_distribute",
    "distribute_roles",
    "start_round",
    "start_turn",
    "start_night",
    "start_new_day",
    "speaker_auto",
    "speaker_manual",
    "challenge_toggle",
    "lv6_back_s",
}

_ADMIN_OR_MOD_PREFIXES = (
    "remove_player:",
    "remove_",
)


def install(main):
    """Add a final authorization boundary around every registered callback.

    UI visibility is not a security boundary: old Telegram messages can still
    contain legacy callback_data. Therefore authorization is enforced at
    callback execution time, after all legacy/runtime handlers are registered.
    """
    dp = main.dp
    bot = main.bot
    registry = getattr(getattr(dp, "callback_query_handlers", None), "handlers", None)
    if registry is None:
        logging.warning("callback authorization: callback registry unavailable")
        return

    if getattr(main, "_callback_authorization_installed", False):
        return

    def data_of(callback):
        return str(getattr(callback, "data", "") or "")

    def requires_admin(data: str) -> bool:
        return data in _ADMIN_ONLY_EXACT or any(data.startswith(p) for p in _ADMIN_ONLY_PREFIXES)

    def requires_admin_or_moderator(data: str) -> bool:
        return data in _ADMIN_OR_MOD_EXACT or any(data.startswith(p) for p in _ADMIN_OR_MOD_PREFIXES)

    async def is_admin(user_id: int, group_id: int) -> bool:
        try:
            admins = await bot.get_chat_administrators(group_id)
            return any(a.user.id == user_id for a in admins)
        except Exception:
            return False

    async def allowed(callback) -> tuple[bool, str]:
        data = data_of(callback)
        if not requires_admin(data) and not requires_admin_or_moderator(data):
            return True, ""

        chat = getattr(getattr(callback, "message", None), "chat", None)
        group_id = getattr(chat, "id", None) or getattr(main, "group_chat_id", None)
        if not group_id:
            return False, "⛔ گروه مشخص نیست."

        user_id = callback.from_user.id
        admin = await is_admin(user_id, int(group_id))
        moderator = user_id == getattr(main, "moderator_id", None)

        if requires_admin(data):
            if admin:
                return True, ""
            return False, "⛔ فقط مدیران گروه به این گزینه دسترسی دارند."

        if admin or moderator:
            return True, ""
        return False, "⛔ فقط گرداننده یا مدیر گروه به این گزینه دسترسی دارند."

    # Wrap each callback in-place so we preserve its original filters and
    # handler ordering. A separate catch-all handler cannot safely "continue"
    # to the next aiogram handler after authorization.
    wrapped_count = 0
    for item in registry:
        callback_fn = getattr(item, "callback", None)
        if callback_fn is None or getattr(callback_fn, "_callback_auth_guard", False):
            continue

        @wraps(callback_fn)
        async def guarded(callback, _original=callback_fn):
            ok, reason = await allowed(callback)
            if not ok:
                await callback.answer(reason, show_alert=True)
                return
            return await _original(callback)

        guarded._callback_auth_guard = True
        guarded._callback_auth_original = callback_fn
        item.callback = guarded
        wrapped_count += 1

    main._callback_authorization_installed = True
    logging.info("✅ Callback authorization guard installed on %s handlers", wrapped_count)
