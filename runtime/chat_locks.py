"""Chat speaking-lock controls for Mafia Nights.

Telegram enforces the hard locks for regular members through chat permissions.
A lightweight message guard handles administrators (which Telegram permissions
describe separately) and the special turn-lock emoji/symbol exception.
"""
from __future__ import annotations

import logging
import unicodedata
from typing import Any

from aiogram import types
from aiogram.dispatcher.handler import CancelHandler
from aiogram.types import ChatPermissions


LOCK_KEYS = ("chat_lock", "night_lock", "turn_lock")


def _settings(main) -> dict[str, Any]:
    addons = getattr(main, "addons", None)
    if addons is None:
        return {}
    try:
        gid = int(getattr(main, "group_chat_id", None) or getattr(addons, "group_id", None) or getattr(main, "ALLOWED_GROUP_ID", 0))
        return addons.get_group_settings(gid) or {}
    except Exception:
        return getattr(addons, "settings", {}) or {}


def _security(main) -> dict[str, Any]:
    return dict(_settings(main).get("security") or {})


def _group_id(main, message=None) -> int | None:
    if message is not None and getattr(message, "chat", None):
        try:
            return int(message.chat.id)
        except Exception:
            pass
    for key in ("group_chat_id", "ALLOWED_GROUP_ID", "GROUP_ID"):
        value = getattr(main, key, None)
        if value:
            try:
                return int(value)
            except Exception:
                pass
    return None


def _active_player_ids(main, gid: int) -> set[int]:
    ids: set[int] = set()
    try:
        game = main.runtime.state.active_game(gid)
        if not game:
            return ids
        for row in main.runtime.state.games.list_players(game["id"]):
            status = str(row.get("status") or "active")
            if row.get("seat") is not None and status not in {"removed", "dead", "finished", "kicked"}:
                ids.add(int(row["player_id"]))
    except Exception:
        logging.exception("chat locks: active player lookup failed")
    return ids


def _moderator_id(main) -> int:
    try:
        return int(getattr(main, "moderator_id", 0) or 0)
    except Exception:
        return 0


def _current_turn_uid(main) -> int | None:
    try:
        order = list(getattr(main, "turn_order", []) or [])
        index = int(getattr(main, "current_turn_index", 0) or 0)
        if not order:
            return None
        seat = int(order[index])
        return int((getattr(main, "player_slots", {}) or {}).get(seat))
    except Exception:
        return None


def _full_permissions() -> ChatPermissions:
    return ChatPermissions(
        can_send_messages=True,
        can_send_media_messages=True,
        can_send_other_messages=True,
        can_add_web_page_previews=True,
    )


def _locked_permissions() -> ChatPermissions:
    return ChatPermissions(
        can_send_messages=False,
        can_send_media_messages=False,
        can_send_other_messages=False,
        can_add_web_page_previews=False,
    )


def _permissions_dict(value) -> dict[str, bool]:
    if value is None:
        return {}
    keys = (
        "can_send_messages",
        "can_send_media_messages",
        "can_send_other_messages",
        "can_add_web_page_previews",
    )
    return {k: bool(getattr(value, k, False)) for k in keys if getattr(value, k, None) is not None}


async def _set_default_permissions(main, gid: int, permissions: ChatPermissions) -> bool:
    try:
        await main.bot.set_chat_permissions(gid, permissions=permissions)
        return True
    except Exception:
        logging.exception("chat locks: set_chat_permissions failed gid=%s", gid)
        return False


async def _restrict(main, gid: int, uid: int, allowed: bool) -> bool:
    try:
        await main.bot.restrict_chat_member(
            gid,
            uid,
            permissions=_full_permissions() if allowed else _locked_permissions(),
        )
        return True
    except Exception:
        logging.debug("chat locks: restrict_chat_member failed gid=%s uid=%s", gid, uid, exc_info=True)
        return False


async def _snapshot_permissions(main, gid: int) -> bool:
    addons = getattr(main, "addons", None)
    if addons is None:
        return False
    try:
        chat = await main.bot.get_chat(gid)
        current = _permissions_dict(getattr(chat, "permissions", None))
        sec = addons.get_group_settings(gid).setdefault("security", {})
        if "_chat_permissions_backup" not in sec and current:
            sec["_chat_permissions_backup"] = current
            addons.set_group_settings(gid, addons.get_group_settings(gid))
        return True
    except Exception:
        logging.exception("chat locks: permission snapshot failed gid=%s", gid)
        return False


async def sync_group_permissions(main, gid: int | None = None) -> bool:
    """Apply the effective hard lock to regular members and unlock exceptions."""
    gid = gid or _group_id(main)
    if not gid:
        return False
    sec = _security(main)
    chat_lock = bool(sec.get("chat_lock"))
    night_lock = bool(sec.get("night_lock"))
    if not (chat_lock or night_lock):
        addons = getattr(main, "addons", None)
        backup = None
        if addons is not None:
            try:
                backup = (_security(main).get("_chat_permissions_backup") or {})
            except Exception:
                backup = None
        if backup:
            await _set_default_permissions(
                main,
                gid,
                ChatPermissions(**backup),
            )
        return True

    await _snapshot_permissions(main, gid)
    if not await _set_default_permissions(main, gid, _locked_permissions()):
        return False

    # Night lock: only moderator gets an explicit member exception if the
    # moderator is not an administrator. Chat administrators are handled by
    # the message guard below.
    if night_lock:
        await _restrict(main, gid, _moderator_id(main), True)
        return True

    # Chat lock: current seated players are allowed to speak.
    for uid in _active_player_ids(main, gid):
        await _restrict(main, gid, uid, True)
    return True


async def unlock_player_if_needed(main, gid: int, uid: int) -> None:
    sec = _security(main)
    if sec.get("night_lock"):
        return
    if sec.get("chat_lock"):
        await _restrict(main, gid, uid, True)


def _is_admin(status: str) -> bool:
    return status in {"creator", "administrator"}


async def _member_status(main, gid: int, uid: int) -> str:
    try:
        member = await main.bot.get_chat_member(gid, uid)
        return str(getattr(member, "status", "") or "")
    except Exception:
        return ""


def _emoji_or_symbol_only(value: str | None) -> bool:
    text = (value or "").strip()
    if not text:
        return False
    saw = False
    for ch in text:
        if ch.isspace() or unicodedata.category(ch) in {"Mn", "Mc", "Me", "Cf"}:
            continue
        category = unicodedata.category(ch)
        if category.startswith(("S", "P")):
            saw = True
            continue
        return False
    return saw


async def _message_guard(message: types.Message, main):
    if message.chat.type not in {"group", "supergroup"}:
        return
    gid = int(message.chat.id)
    sec = _security(main)
    chat_lock = bool(sec.get("chat_lock"))
    night_lock = bool(sec.get("night_lock"))
    turn_lock = bool(sec.get("turn_lock"))
    if not (chat_lock or night_lock or turn_lock):
        return

    uid = int(message.from_user.id)
    status = await _member_status(main, gid, uid)
    moderator = uid == _moderator_id(main)

    if night_lock:
        if moderator:
            return
        # Telegram default permissions already block regular members.
        # Administrators are outside ChatPermissions, so remove their
        # messages when possible to enforce the moderator-only rule.
        if _is_admin(status):
            try:
                await message.delete()
            except Exception:
                logging.debug("chat locks: could not delete admin message in night lock", exc_info=True)
            raise CancelHandler()
        raise CancelHandler()

    if chat_lock:
        allowed_players = _active_player_ids(main, gid)
        if uid in allowed_players or moderator:
            return
        # Regular non-players should already be blocked by Telegram.
        # This also cleans up a message that arrived before restrictions synced.
        try:
            await message.delete()
        except Exception:
            pass
        raise CancelHandler()

    if turn_lock:
        current_uid = _current_turn_uid(main)
        if moderator or uid == current_uid:
            return
        # Turn lock intentionally permits only a reaction-like text made from
        # emoji/symbols for everyone else. Text/media is removed.
        if getattr(message, "text", None) and _emoji_or_symbol_only(message.text):
            raise CancelHandler()
        try:
            await message.delete()
        except Exception:
            pass
        raise CancelHandler()


def install(main) -> bool:
    if getattr(main, "_chat_locks_installed", False):
        return False

    dp = main.dp
    dp.register_message_handler(
        lambda message: _message_guard(message, main),
        content_types=types.ContentTypes.ANY,
        state="*",
    )

    # Put the lock guard before legacy catch-all message handlers. It does not
    # cancel allowed messages, so normal bot commands/game messages keep working.
    handlers = getattr(getattr(dp, "message_handlers", None), "handlers", [])
    if handlers:
        item = handlers[-1]
        handlers.insert(0, handlers.pop())
        item.handler.__name__ = "chat_lock_message_guard"

    # A seated player must be released immediately after the canonical lobby
    # seat handler succeeds while chat-lock is active.
    registry = getattr(getattr(dp, "callback_query_handlers", None), "handlers", [])
    for item in list(registry):
        fn = getattr(item, "handler", None) or getattr(item, "callback", None)
        if getattr(fn, "__name__", "") != "seat_select":
            continue
        if getattr(fn, "_chat_lock_wrapped", False):
            break
        original = fn

        async def seat_select_with_lock(callback, __original=original):
            result = await __original(callback)
            try:
                await unlock_player_if_needed(main, int(callback.message.chat.id), int(callback.from_user.id))
            except Exception:
                logging.exception("chat locks: failed to unlock newly seated player")
            return result

        seat_select_with_lock.__name__ = "seat_select"
        seat_select_with_lock._chat_lock_wrapped = True
        item.handler = seat_select_with_lock
        break

    main._chat_locks_installed = True
    logging.info("CHAT LOCKS installed")
    return True
