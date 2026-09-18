"""Canonical Face-Off card for the private game-management panel.

The moderator executes the action. The exiting player is removed from the active
roster and their role is transferred internally to a selected active player.
The recipient keeps seeing their original private role message and is blocked
from role recovery until the game finishes.
"""
from __future__ import annotations

import html
import logging
from typing import Any

from aiogram import types
from aiogram.dispatcher.handler import CancelHandler
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


ACTIVE_STATUSES = {"lobby", "running", "paused"}


def _group_id(app: Any) -> int | None:
    for key in ("group_chat_id", "ALLOWED_GROUP_ID", "GROUP_ID", "group_id"):
        value = getattr(app, key, None)
        if value:
            try:
                return int(value)
            except (TypeError, ValueError):
                pass
    return None


def _active_game(app: Any):
    gid = _group_id(app)
    if not gid:
        return None
    try:
        return app.runtime.state.active_game(gid)
    except Exception:
        logging.exception("faceoff: failed to resolve active game")
        return None


def _name(row: dict[str, Any]) -> str:
    return str(
        row.get("nickname")
        or row.get("first_name")
        or row.get("username")
        or row.get("player_id")
        or "بازیکن"
    )


def _rows(app, game):
    rows = app.runtime.state.games.list_players(game["id"])
    return [
        r for r in rows
        if r.get("seat") is not None
        and str(r.get("status") or "active") not in {"removed", "dead", "finished", "kicked"}
    ]


async def _allowed(callback, app, game) -> bool:
    uid = int(callback.from_user.id)
    if uid == int(game.get("moderator_id") or 0):
        return True
    gid = int(game.get("group_chat_id") or _group_id(app) or 0)
    if not gid:
        return False
    try:
        return (
            await app.bot.get_chat_member(gid, uid)
        ).status in {"creator", "administrator"}
    except Exception:
        return False


def hidden_role_users(app) -> set[int]:
    """Return players whose role was transferred by Face-Off in the active game."""
    game = _active_game(app)
    if not game:
        return set()
    state = dict(game.get("state") or {})
    try:
        return {int(x) for x in (state.get("faceoff_hidden_role_players") or [])}
    except (TypeError, ValueError):
        return set()


async def install(app: Any) -> bool:
    if getattr(app, "_faceoff_installed", False):
        return False

    from runtime import final_private_ui as pui

    original_management_keyboard = pui.management_keyboard

    def management_keyboard():
        kb = original_management_keyboard()
        rows = getattr(kb, "inline_keyboard", [])
        if not any(
            getattr(button, "callback_data", "") == "finalgm:faceoff"
            for row in rows for button in row
        ):
            button = InlineKeyboardButton("🎭 فیس آف", callback_data="finalgm:faceoff")
            # Keep the management back button last.
            rows.insert(max(0, len(rows) - 1), [button])
        return kb

    pui.management_keyboard = management_keyboard

    async def faceoff_menu(callback: types.CallbackQuery):
        game = _active_game(app)
        if not game or str(game.get("status") or "") not in {"running", "paused"}:
            await callback.answer("⚠️ فیس آف فقط هنگام اجرای بازی در دسترس است.", show_alert=True)
            raise CancelHandler()
        if not await _allowed(callback, app, game):
            await callback.answer("⛔ فقط گرداننده یا مدیر گروه می‌تواند فیس آف انجام دهد.", show_alert=True)
            raise CancelHandler()

        rows = _rows(app, game)
        kb = InlineKeyboardMarkup(row_width=2)
        for row in sorted(rows, key=lambda x: int(x.get("seat") or 999)):
            kb.insert(
                InlineKeyboardButton(
                    f"🎭 {int(row['seat']):02d}. {_name(row)}",
                    callback_data=f"finalgm:faceoff:source:{int(row['player_id'])}",
                )
            )
        kb.add(InlineKeyboardButton("⬅️ مدیریت بازی", callback_data="finalgm:back"))
        await callback.message.edit_text(
            "🎭 <b>فیس آف</b>\n\n"
            "بازیکنی را که باید از بازی خارج شود انتخاب کنید:",
            parse_mode="HTML",
            reply_markup=kb,
        )
        await callback.answer()
        raise CancelHandler()

    async def faceoff_source(callback: types.CallbackQuery):
        game = _active_game(app)
        if not game or str(game.get("status") or "") not in {"running", "paused"}:
            await callback.answer("⚠️ بازی فعال نیست.", show_alert=True)
            raise CancelHandler()
        if not await _allowed(callback, app, game):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
            raise CancelHandler()

        try:
            source_id = int(str(callback.data).rsplit(":", 1)[1])
        except (TypeError, ValueError):
            await callback.answer("❌ بازیکن نامعتبر است.", show_alert=True)
            raise CancelHandler()

        rows = _rows(app, game)
        source = next((r for r in rows if int(r["player_id"]) == source_id), None)
        if not source:
            await callback.answer("❌ بازیکن پیدا نشد یا دیگر در بازی نیست.", show_alert=True)
            raise CancelHandler()

        hidden = hidden_role_users(app)
        kb = InlineKeyboardMarkup(row_width=2)
        for row in sorted(rows, key=lambda x: int(x.get("seat") or 999)):
            target_id = int(row["player_id"])
            if target_id == source_id or target_id in hidden:
                continue
            kb.insert(
                InlineKeyboardButton(
                    f"🎭 {int(row['seat']):02d}. {_name(row)}",
                    callback_data=f"finalgm:faceoff:target:{source_id}:{target_id}",
                )
            )
        kb.add(InlineKeyboardButton("⬅️ انتخاب بازیکن اول", callback_data="finalgm:faceoff"))
        await callback.message.edit_text(
            f"🎭 <b>فیس آف</b>\n\n"
            f"بازیکن خارج‌شونده: <b>{html.escape(_name(source))}</b>\n\n"
            "حالا بازیکنی را انتخاب کنید که نقش او با نقش بازیکن اول جابه‌جا شود:",
            parse_mode="HTML",
            reply_markup=kb,
        )
        await callback.answer()
        raise CancelHandler()

    async def faceoff_target(callback: types.CallbackQuery):
        game = _active_game(app)
        if not game or str(game.get("status") or "") not in {"running", "paused"}:
            await callback.answer("⚠️ بازی فعال نیست.", show_alert=True)
            raise CancelHandler()
        if not await _allowed(callback, app, game):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
            raise CancelHandler()

        parts = str(callback.data or "").split(":")
        if len(parts) != 5:
            await callback.answer("❌ اطلاعات فیس آف نامعتبر است.", show_alert=True)
            raise CancelHandler()
        try:
            source_id, target_id = int(parts[3]), int(parts[4])
        except ValueError:
            await callback.answer("❌ بازیکن نامعتبر است.", show_alert=True)
            raise CancelHandler()

        rows = _rows(app, game)
        source = next((r for r in rows if int(r["player_id"]) == source_id), None)
        target = next((r for r in rows if int(r["player_id"]) == target_id), None)
        if not source or not target or source_id == target_id:
            await callback.answer("❌ بازیکنان انتخاب‌شده معتبر نیستند.", show_alert=True)
            raise CancelHandler()

        hidden = hidden_role_users(app)
        if target_id in hidden:
            await callback.answer("❌ این بازیکن قبلاً فیس آف شده است.", show_alert=True)
            raise CancelHandler()

        source_role = str(source.get("role") or "").strip()
        target_role = str(target.get("role") or "").strip()
        if not source_role or not target_role:
            await callback.answer("❌ نقش یکی از بازیکنان مشخص نیست؛ عملیات انجام نشد.", show_alert=True)
            raise CancelHandler()

        game_id = int(game["id"])
        try:
            # Transfer the exiting player's role to the destination player.
            if not app.runtime.state.games.set_player_role(game_id, target_id, source_role):
                raise RuntimeError("target role update failed")

            # Remove the first player from the active game.
            app.runtime.state.games.set_player_seat(game_id, source_id, None)
            app.runtime.state.games.set_player_status(game_id, source_id, "removed")

            state = dict(game.get("state") or {})
            role_map = dict(state.get("last_role_map") or {})
            role_map.pop(str(source_id), None)
            role_map[str(target_id)] = source_role
            state["last_role_map"] = role_map

            players_in_game = dict(state.get("players_in_game") or {})
            source_seat = str(int(source.get("seat")))
            target_seat = str(int(target.get("seat")))
            players_in_game.pop(source_seat, None)
            target_payload = dict(players_in_game.get(target_seat) or {})
            target_payload.update({
                "id": target_id,
                "name": _name(target),
                "role": source_role,
            })
            players_in_game[target_seat] = target_payload
            state["players_in_game"] = players_in_game

            turn_order = [int(x) for x in (state.get("turn_order") or [])]
            source_seat_int = int(source.get("seat"))
            state["turn_order"] = [x for x in turn_order if x != source_seat_int]

            hidden = {int(x) for x in (state.get("faceoff_hidden_role_players") or [])}
            hidden.add(target_id)
            state["faceoff_hidden_role_players"] = sorted(hidden)

            history = list(state.get("faceoff_history") or [])
            history.append({
                "source_player_id": source_id,
                "target_player_id": target_id,
                "source_role": source_role,
                "target_previous_role": target_role,
            })
            state["faceoff_history"] = history[-50:]

            if not app.runtime.state.games.update_game(game_id, state=state):
                raise RuntimeError("game state update failed")
        except Exception:
            logging.exception(
                "faceoff failed game=%s source=%s target=%s",
                game_id, source_id, target_id,
            )
            # Best-effort rollback of the role transfer if the state write failed.
            try:
                app.runtime.state.games.set_player_role(game_id, target_id, target_role)
                app.runtime.state.games.set_player_seat(game_id, source_id, int(source["seat"]))
                app.runtime.state.games.set_player_status(game_id, source_id, str(source.get("status") or "active"))
            except Exception:
                logging.exception("faceoff rollback failed game=%s", game_id)
            await callback.answer("❌ اجرای فیس آف انجام نشد؛ هیچ تغییری را قطعی در نظر نگیرید.", show_alert=True)
            raise CancelHandler()

        group_id = int(game.get("group_chat_id") or _group_id(app) or 0)
        try:
            await app.bot.send_message(
                group_id,
                f"🎭 <b>فیس آف</b>\n\n"
                f"❌ {html.escape(_name(source))} از بازی خارج شد.",
                parse_mode="HTML",
            )
        except Exception:
            logging.exception("faceoff group notification failed game=%s", game_id)

        try:
            await app.bot.send_message(
                source_id,
                "🎭 <b>فیس آف</b>\n\n"
                "❌ شما توسط گرداننده از بازی خارج شدید.",
                parse_mode="HTML",
            )
        except Exception:
            logging.info("faceoff source notification failed user=%s", source_id)

        await callback.message.edit_text(
            f"✅ <b>فیس آف انجام شد.</b>\n\n"
            f"❌ خارج شد: <b>{html.escape(_name(source))}</b>\n"
            f"🎭 نقش او به <b>{html.escape(_name(target))}</b> منتقل شد.\n\n"
            "🔒 نقش جدید به بازیکن مقصد ارسال نمی‌شود و تا پایان بازی «نقش من» برای او مسدود است.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(row_width=1).add(
                InlineKeyboardButton("🎭 فیس آف دیگر", callback_data="finalgm:faceoff"),
                InlineKeyboardButton("⬅️ مدیریت بازی", callback_data="finalgm:back"),
            ),
        )
        await callback.answer("✅ فیس آف انجام شد.")
        raise CancelHandler()

    async def blocked_role_text(message: types.Message):
        if message.chat.type != "private" or (message.text or "").strip() != "نقش من":
            return
        if int(message.from_user.id) not in hidden_role_users(app):
            return
        await message.answer(
            "🔒 نقش شما در این بازی به‌صورت فیس آف تغییر کرده است و تا پایان بازی امکان مشاهده مجدد نقش وجود ندارد."
        )
        raise CancelHandler()

    async def blocked_role_deeplink(message: types.Message):
        if message.chat.type != "private":
            return
        args = message.get_args() or ""
        if not args.startswith("role_"):
            return
        if int(message.from_user.id) not in hidden_role_users(app):
            return
        await message.answer(
            "🔒 به‌دلیل فیس آف، دریافت مجدد نقش تا پایان بازی امکان‌پذیر نیست."
        )
        raise CancelHandler()

    dp = app.dp
    dp.register_callback_query_handler(
        faceoff_menu, lambda c: str(c.data or "") == "finalgm:faceoff", state="*"
    )
    dp.register_callback_query_handler(
        faceoff_source, lambda c: str(c.data or "").startswith("finalgm:faceoff:source:"), state="*"
    )
    dp.register_callback_query_handler(
        faceoff_target, lambda c: str(c.data or "").startswith("finalgm:faceoff:target:"), state="*"
    )
    dp.register_message_handler(
        blocked_role_text,
        lambda m: bool(m.chat and m.chat.type == "private" and (m.text or "").strip() == "نقش من"),
        content_types=types.ContentTypes.TEXT,
        state="*",
    )
    dp.register_message_handler(
        blocked_role_deeplink,
        commands={"start"},
        state="*",
    )

    cq = getattr(dp.callback_query_handlers, "handlers", [])
    for item in list(cq):
        fn = getattr(item, "handler", None) or getattr(item, "callback", None)
        if fn in {faceoff_menu, faceoff_source, faceoff_target}:
            try:
                cq.remove(item)
                cq.insert(0, item)
            except ValueError:
                pass

    mh = getattr(dp.message_handlers, "handlers", [])
    for item in list(mh):
        fn = getattr(item, "handler", None) or getattr(item, "callback", None)
        if fn in {blocked_role_text, blocked_role_deeplink}:
            try:
                mh.remove(item)
                mh.insert(0, item)
            except ValueError:
                pass

    app._faceoff_installed = True
    logging.info("FACE-OFF PRIVATE MANAGEMENT ACTIVE")
    return True


# Synchronous helper for role-recovery guards used by other runtime modules.
def is_hidden_role_player(app: Any, user_id: int) -> bool:
    return int(user_id) in hidden_role_users(app)
