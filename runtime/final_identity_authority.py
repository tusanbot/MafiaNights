from __future__ import annotations

import logging


def _handler(item):
    return getattr(item, "handler", None) or getattr(item, "callback", None)


def install(app):
    if getattr(app, "_final_identity_authority", False):
        return False
    registry = getattr(getattr(app.dp, "callback_query_handlers", None), "handlers", [])
    app._final_identity_authority = True

    for item in list(registry):
        fn = _handler(item)
        if getattr(fn, "__name__", "") != "distribute_roles" or getattr(fn, "_identity_wrapped", False):
            continue
        original = fn

        async def wrapped(callback, _original=original):
            result = await _original(callback)
            try:
                gid = int(callback.message.chat.id)
                game = app.runtime.state.active_game(gid)
                if not game:
                    return result
                moderator_id = int(game.get("moderator_id") or 0)
                if not moderator_id:
                    return result
                member = await app.bot.get_chat_member(gid, moderator_id)
                user = getattr(member, "user", None)
                name = getattr(user, "full_name", None) or getattr(user, "first_name", None) or getattr(user, "username", None)
                if name:
                    state = dict(game.get("state") or {})
                    state["moderator_name"] = str(name)
                    app.runtime.state.games.update_game(game["id"], state=state)
            except Exception:
                logging.exception("failed to persist moderator identity for final result")
            return result

        wrapped.__name__ = "distribute_roles"
        wrapped._identity_wrapped = True
        try:
            item.handler = wrapped
        except Exception:
            item.callback = wrapped
        break

    logging.info("FINAL_IDENTITY_AUTHORITY active")
    return True
