from __future__ import annotations

import logging
from functools import wraps

from aiogram.dispatcher.handler import CancelHandler


ADMIN_ONLY_EXACT = {
    "lv6_new", "new_game", "manage_game", "manage_scenarios",
    "add_scenario", "remove_scenario", "back_main", "choose_scenario",
    "choose_moderator",
}
ADMIN_ONLY_PREFIXES = ("lv6_s:", "lv6_m:", "delete_scen_", "scenario_", "moderator_")
ADMIN_OR_MOD_EXACT = {
    "lv6_manage", "lv6_cancel", "lv6_change_s", "lv6_change_m",
    "lv6_challenge", "lv6_remove", "lv6_ready", "lv6_distribute",
    "distribute_roles", "start_round", "start_turn", "start_night",
    "start_new_day", "speaker_auto", "speaker_manual", "choose_head",
    "challenge_toggle", "lv6_back_s",
}
ADMIN_OR_MOD_PREFIXES = ("remove_player:", "remove_")

# These are the old handlers that must never win over the authoritative UI.
LEGACY_GAME_HANDLERS = {
    "start_round_handler", "handle_start_turn", "start_night", "start_new_day",
    "distribute_roles_callback",
}
AUTHORITATIVE_FRONT = {
    "start_round_clean", "start_turn_clean", "start_night_clean",
    "start_new_day_clean", "challenge_status", "challenge_request",
    "handle_challenge_response",
}


def _handler(item):
    # aiogram 2.25.1 stores callbacks on HandlerObj.handler, not .callback.
    return getattr(item, "handler", None)


def _set_handler(item, fn):
    if hasattr(item, "handler"):
        item.handler = fn
        return True
    # Compatibility with any custom registry object used by tests/older code.
    if hasattr(item, "callback"):
        item.callback = fn
        return True
    if isinstance(item, dict):
        item["handler"] = fn
        return True
    return False


def install(main):
    dp = main.dp
    registry = getattr(getattr(dp, "callback_query_handlers", None), "handlers", None)
    if registry is None:
        logging.error("FINAL runtime guard: callback registry unavailable")
        return

    # First remove legacy game-flow entries using the real HandlerObj.handler.
    before = len(registry)
    registry[:] = [
        item for item in registry
        if getattr(_handler(item), "__name__", "") not in LEGACY_GAME_HANDLERS
    ]
    removed_legacy = before - len(registry)

    # If several next_turn handlers exist, keep the cleanup wrapper when present
    # and otherwise wrap the first real handler below.
    next_items = [item for item in registry if getattr(_handler(item), "__name__", "") == "next_turn"]
    if len(next_items) > 1:
        keep = next((i for i in next_items if getattr(_handler(i), "_ui_cleanup_v2", False)), next_items[0])
        registry[:] = [item for item in registry if getattr(_handler(item), "__name__", "") != "next_turn" or item is keep]

    # The v2 cleanup layer itself was written against the wrong aiogram field.
    # Repair its registrations here without depending on that implementation.
    for item in list(registry):
        fn = _handler(item)
        if fn is None or getattr(fn, "_final_runtime_guard", False):
            continue

        original = fn

        @wraps(original)
        async def guarded(callback, _original=original):
            data = str(getattr(callback, "data", "") or "")
            protected_admin = data in ADMIN_ONLY_EXACT or any(data.startswith(p) for p in ADMIN_ONLY_PREFIXES)
            protected_game = data in ADMIN_OR_MOD_EXACT or any(data.startswith(p) for p in ADMIN_OR_MOD_PREFIXES)

            if protected_admin or protected_game:
                chat = getattr(getattr(callback, "message", None), "chat", None)
                group_id = getattr(chat, "id", None) or getattr(main, "group_chat_id", None)
                user_id = getattr(getattr(callback, "from_user", None), "id", None)

                is_admin = False
                if group_id and user_id:
                    try:
                        admins = await main.bot.get_chat_administrators(int(group_id))
                        is_admin = any(a.user.id == user_id for a in admins)
                    except Exception:
                        logging.exception("FINAL runtime guard: admin lookup failed")

                is_mod = user_id == getattr(main, "moderator_id", None)
                allowed = is_admin if protected_admin else (is_admin or is_mod)
                if not allowed:
                    reason = (
                        "⛔ فقط مدیران گروه به این گزینه دسترسی دارند."
                        if protected_admin else
                        "⛔ فقط گرداننده یا مدیر گروه به این گزینه دسترسی دارند."
                    )
                    await callback.answer(reason, show_alert=True)
                    # Stop aiogram from continuing to the next handler.
                    raise CancelHandler()

            return await _original(callback)

        guarded._final_runtime_guard = True
        guarded._final_runtime_original = original
        _set_handler(item, guarded)

    # Delete the previous turn message before the real next_turn handler runs.
    for item in registry:
        fn = _handler(item)
        if getattr(fn, "__name__", "") == "next_turn" and not getattr(fn, "_turn_cleanup_final", False):
            original = fn

            @wraps(original)
            async def cleaned_next_turn(callback, _original=original):
                try:
                    await callback.message.delete()
                except Exception:
                    pass
                return await _original(callback)

            cleaned_next_turn._turn_cleanup_final = True
            # Re-wrap authorization because this wrapper replaces the guarded fn.
            async def authorized_cleaned(callback, _original=cleaned_next_turn):
                data = str(getattr(callback, "data", "") or "")
                if data in ADMIN_OR_MOD_EXACT or any(data.startswith(p) for p in ADMIN_OR_MOD_PREFIXES):
                    chat = getattr(getattr(callback, "message", None), "chat", None)
                    group_id = getattr(chat, "id", None) or getattr(main, "group_chat_id", None)
                    uid = getattr(getattr(callback, "from_user", None), "id", None)
                    is_admin = False
                    if group_id and uid:
                        try:
                            admins = await main.bot.get_chat_administrators(int(group_id))
                            is_admin = any(a.user.id == uid for a in admins)
                        except Exception:
                            pass
                    if not (is_admin or uid == getattr(main, "moderator_id", None)):
                        await callback.answer("⛔ فقط گرداننده یا مدیر گروه به این گزینه دسترسی دارند.", show_alert=True)
                        raise CancelHandler()
                return await _original(callback)
            authorized_cleaned._final_runtime_guard = True
            _set_handler(item, authorized_cleaned)
            break

    # Put authoritative handlers before every legacy catch-all with the same data.
    for wanted in reversed(("handle_challenge_response", "challenge_request", "challenge_status", "start_new_day_clean", "start_night_clean", "start_turn_clean", "start_round_clean")):
        for i, item in enumerate(registry):
            if getattr(_handler(item), "__name__", "") == wanted:
                registry.insert(0, registry.pop(i))
                break

    main._final_runtime_guard_installed = True
    logging.info(
        "FINAL runtime guard installed: handlers=%d legacy_removed=%d protected_exact=%d",
        len(registry), removed_legacy, len(ADMIN_ONLY_EXACT | ADMIN_OR_MOD_EXACT),
    )
    logging.info(
        "FINAL callback registry head: %s",
        [getattr(_handler(item), "__name__", "?") for item in list(registry)[:15]],
    )
