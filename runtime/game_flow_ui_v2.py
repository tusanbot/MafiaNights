from __future__ import annotations

import html
import logging
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


"""Authoritative cleanup layer for the in-game Telegram UI.

This layer deliberately sits after the legacy runtime bridges. It owns only the
message lifecycle around role distribution, round transitions, next-turn, night
and new-day transitions. Game state/turn mechanics remain in main1 and the
persistent bridges.
"""


def install(main):
    dp = main.dp
    bot = main.bot

    def handlers():
        return getattr(getattr(dp, "callback_query_handlers", None), "handlers", [])

    def front(fn):
        registry = handlers()
        for i, item in enumerate(registry):
            if getattr(item, "callback", None) is fn:
                registry.insert(0, registry.pop(i))
                return

    def challenge_status_keyboard():
        kb = InlineKeyboardMarkup(row_width=1)
        kb.add(InlineKeyboardButton("⚔️ وضعیت چالش", callback_data="lv6_challenge_status"))
        return kb

    async def challenge_status(callback):
        status = "روشن" if getattr(main, "challenge_active", True) else "خاموش"
        await callback.answer(f"⚔️ وضعیت چالش: {status}", show_alert=True)

    async def start_round_clean(callback):
        if callback.from_user.id != main.moderator_id:
            await callback.answer("❌ فقط گرداننده می‌تواند دور را شروع کند.", show_alert=True)
            return
        # Transient in-memory seat maps may be empty after a new day. Always
        # hydrate from the durable game-player rows before validating the turn.
        try:
            game0 = main.runtime.state.active_game(int(main.group_chat_id or callback.message.chat.id))
            rows0 = [
                row for row in main.runtime.state.games.list_players(game0["id"])
                if row.get("seat") is not None
                and str(row.get("status") or "active") not in {"removed", "dead", "finished", "kicked"}
            ] if game0 else []
            main.player_slots = {int(row["seat"]): int(row["player_id"]) for row in rows0}
            main.players = {int(row["player_id"]): str(row.get("nickname") or row.get("first_name") or row.get("username") or row["player_id"]) for row in rows0}
            state0 = dict((game0 or {}).get("state") or {})
            persisted_order = []
            for raw in state0.get("turn_order") or []:
                try:
                    seat = int(raw)
                except (TypeError, ValueError):
                    continue
                if seat in main.player_slots:
                    persisted_order.append(seat)
            main.turn_order = persisted_order or sorted(main.player_slots)
        except Exception:
            logging.exception("start_round_clean: failed to hydrate seats")

        if not main.player_slots:
            await callback.answer("⚠️ هیچ صندلی ثبت‌شده‌ای برای بازیکنان فعال وجود ندارد.", show_alert=True)
            return

        # If no chief has been selected yet, show the canonical chief-selection
        # list here. Once a chief exists, starting the round must NOT render a
        # second player list.
        try:
            game = main.runtime.state.active_game(int(main.group_chat_id or callback.message.chat.id))
            head_seat = dict((game or {}).get("state") or {}).get("head_seat")
            game_id = int((game or {}).get("id") or 0)
        except Exception:
            game, head_seat, game_id = None, None, 0

        if head_seat is None and game_id:
            rows = [
                r for r in main.runtime.lobby_snapshot(int(main.group_chat_id or callback.message.chat.id)).get("players", [])
                if r.get("seat") is not None
                and str(r.get("status") or "active") not in {"removed", "dead", "finished"}
            ]
            kb = InlineKeyboardMarkup(row_width=2)
            kb.add(InlineKeyboardButton("🎲 انتخاب تصادفی", callback_data=f"day:{game_id}:head_random"))
            for row in sorted(rows, key=lambda r: int(r.get("seat") or 999)):
                label = str(row.get("nickname") or row.get("first_name") or row.get("username") or row.get("player_id"))
                kb.insert(InlineKeyboardButton(
                    f"{int(row['seat'])}. {label[:20]}",
                    callback_data=f"day:{game_id}:head_pick:{int(row['seat'])}",
                ))
            kb.row(InlineKeyboardButton("⬅️ بازگشت", callback_data=f"mgmt:{game_id}:close"))
            await callback.message.edit_text(
                "🎩 <b>انتخاب سردست</b>\n\nسردست را انتخاب کنید یا انتخاب تصادفی بزنید:",
                parse_mode="HTML",
                reply_markup=kb,
            )
            await callback.answer("ابتدا سردست را انتخاب کنید.")
            return

        if not main.turn_order:
            main.turn_order = sorted(main.player_slots.keys())
        main.current_turn_index = 0
        first_seat = int(main.turn_order[0])
        try:
            state_now = dict((game or {}).get("state") or {})
            state_now["turn_order"] = [int(x) for x in main.turn_order]
            state_now["current_turn_index"] = 0
            main.runtime.state.games.update_game(
                game["id"], state=state_now, current_turn_index=0, current_turn_seat=first_seat
            )
        except Exception:
            logging.exception("start_round_clean: failed to persist durable turn order")

        # The head-selection handler already rendered the canonical formatted
        # player list. Do NOT replace it with a second/simple player list here.
        # Keeping that message intact gives the day exactly one player-list UI.
        await main.start_turn(first_seat)
        await callback.answer("✅ دور شروع شد")

    async def start_turn_clean(callback):
        if callback.from_user.id != main.moderator_id:
            await callback.answer("❌ فقط گرداننده می‌تواند دور را شروع کند.", show_alert=True)
            return
        if not main.turn_order:
            if main.player_slots:
                main.turn_order = sorted(main.player_slots.keys())
            else:
                await callback.answer("⚠️ ترتیب نوبت‌ها مشخص نیست.", show_alert=True)
                return
        main.current_turn_index = 0
        try:
            await callback.message.delete()
        except Exception:
            pass
        await main.start_turn(main.turn_order[0])
        await callback.answer("✅ دور شروع شد")

    async def next_turn_clean(callback):
        # The old turn/challenge message is disposable. Remove it before the
        # legacy/persistent transition creates the next turn message.
        try:
            await callback.message.delete()
        except Exception:
            pass
        original = getattr(next_turn_clean, "_legacy_original", None)
        if original is not None:
            return await original(callback)
        await callback.answer("⚠️ انتقال نوبت در دسترس نیست.", show_alert=True)

    async def start_night_clean(callback):
        if callback.from_user.id != main.moderator_id:
            await callback.answer("❌ فقط گرداننده می‌تواند فاز شب را شروع کند.", show_alert=True)
            return
        kb = InlineKeyboardMarkup(row_width=1)
        kb.add(InlineKeyboardButton("🌞 شروع روز جدید", callback_data="start_new_day"))
        try:
            await callback.message.edit_text(
                "🌙 <b>فاز شب شروع شد.</b>\n\nدر صورت آماده بودن، روز جدید را شروع کنید.",
                reply_markup=kb,
                parse_mode="HTML",
            )
            main.game_message_id = callback.message.message_id
        except Exception:
            msg = await bot.send_message(
                main.group_chat_id,
                "🌙 <b>فاز شب شروع شد.</b>\n\nدر صورت آماده بودن، روز جدید را شروع کنید.",
                reply_markup=kb,
                parse_mode="HTML",
            )
            main.game_message_id = msg.message_id
        await callback.answer()

    async def start_new_day_clean(callback):
        if callback.from_user.id != main.moderator_id:
            await callback.answer("❌ فقط گرداننده می‌تواند روز جدید را شروع کند.", show_alert=True)
            return
        group_id = main.group_chat_id or callback.message.chat.id
        main.group_chat_id = group_id

        # Reset exactly once, then immediately render the new-day controls in
        # the message the moderator just clicked. Head selection is responsible
        # for the single formatted player list rendered for the new day.
        try:
            main.reset_round_data()
        except Exception:
            logging.exception("round reset failed")
        main.round_active = True
        main.challenge_mode = False
        main.game_running = True

        runtime = getattr(main, "persistent_runtime", None)
        if runtime is not None:
            try:
                runtime.start_new_day(int(group_id))
            except Exception:
                logging.exception("persistent start_new_day failed")

        # Do not render a second speaker/player list here. The day control
        # has one source of truth: chief selection. If the moderator presses
        # start round without selecting a chief, start_round_clean renders the
        # canonical chief list itself.
        kb = InlineKeyboardMarkup(row_width=2)
        kb.add(
            InlineKeyboardButton("🎩 انتخاب سردست", callback_data=f"day:{int((main.runtime.state.active_game(int(group_id)) or {}).get('id') or 0)}:head"),
            InlineKeyboardButton("▶️ شروع دور", callback_data="start_round"),
        )
        kb.add(InlineKeyboardButton("⚔️ وضعیت چالش", callback_data=f"mgmt:{int(group_id)}:challenge:round"))
        text = "🌞 <b>روز جدید شروع شد!</b>\n\nابتدا سردست را انتخاب کنید؛ سپس «شروع دور» را بزنید."

        try:
            await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
            main.game_message_id = callback.message.message_id
        except Exception:
            msg = await bot.send_message(group_id, text, reply_markup=kb, parse_mode="HTML")
            main.game_message_id = msg.message_id
        await callback.answer("🌞 روز جدید شروع شد")

    # Disable the legacy role-distribution callback completely. It calls
    # show_roles_list() in main1 and is the source of the duplicate moderator
    # list. v6's distribute handler is the sole owner now.
    registry = handlers()
    registry[:] = [
        item for item in registry
        if getattr(getattr(item, "callback", None), "__name__", "")
        not in {"distribute_roles_callback"}
    ]

    # Register cleanup-owned callbacks. They are intentionally moved to the
    # front so stale legacy handlers cannot produce duplicate messages.
    dp.register_callback_query_handler(start_round_clean, lambda c: c.data == "start_round")
    dp.register_callback_query_handler(start_turn_clean, lambda c: c.data == "start_turn")
    dp.register_callback_query_handler(start_night_clean, lambda c: c.data == "start_night")
    dp.register_callback_query_handler(start_new_day_clean, lambda c: c.data == "start_new_day")
    dp.register_callback_query_handler(challenge_status, lambda c: c.data == "lv6_challenge_status")

    for fn in (start_round_clean, start_turn_clean, start_night_clean, start_new_day_clean, challenge_status):
        front(fn)

    # Replace the existing next-turn callback in-place so persistence logic is
    # preserved while the previous turn message is removed first.
    for item in handlers():
        callback = getattr(item, "callback", None)
        if getattr(callback, "__name__", None) == "next_turn":
            original = callback
            async def wrapped_next_turn(cb, _original=original):
                try:
                    await cb.message.delete()
                except Exception:
                    pass
                return await _original(cb)
            wrapped_next_turn.__name__ = "next_turn"
            wrapped_next_turn._ui_cleanup_v2 = True
            wrapped_next_turn._legacy_original = original
            item.callback = wrapped_next_turn
            front(wrapped_next_turn)
            break

    logging.info("✅ Game flow UI cleanup v2 installed")
