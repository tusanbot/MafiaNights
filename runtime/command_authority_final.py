"""Final text-command authority for production."""
from __future__ import annotations

import html
import logging
from typing import Any

from aiogram.dispatcher.handler import CancelHandler
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def _handler(item: Any) -> Any:
    return getattr(item, "callback", None) or getattr(item, "handler", None)


def _move_front(registry, predicate) -> int:
    selected = [item for item in registry if predicate(_handler(item))]
    for item in reversed(selected):
        try:
            registry.remove(item); registry.insert(0, item)
        except ValueError:
            pass
    return len(selected)


def _module_name(fn): return str(getattr(fn, "__module__", ""))
def _name(fn): return str(getattr(fn, "__name__", ""))

def _is_manager(message, game):
    return int(message.from_user.id) == int(game.get("moderator_id") or 0)

async def _cancel_text(message, app):
    """Thin text adapter: delegate cancellation to the canonical end-game owner."""
    if message.chat.type not in {"group", "supergroup"}:
        await message.reply("ℹ️ لغو بازی فقط داخل گروه بازی قابل استفاده است.")
        return
    game = app.runtime.state.active_game(message.chat.id)
    if not game:
        await message.reply("ℹ️ بازی فعالی وجود ندارد.")
        return
    confirmer = getattr(app, "_confirm_cancel_game", None)
    if confirmer is None:
        await message.reply("⚠️ مسیر لغو بازی در دسترس نیست.")
        return
    from types import SimpleNamespace
    callback = SimpleNamespace(
        message=message,
        from_user=message.from_user,
        data=f"mgmt:{int(game['id'])}:cancel",
        answer=message.answer,
    )
    await confirmer(callback)


def install(app: Any) -> bool:
    if getattr(app, "_command_authority_final", False): return False
    app._command_authority_final = True
    dp = app.dp

    async def cancel_text_handler(message): await _cancel_text(message, app)

    async def lobby_command(message):
        if message.chat.type not in {"group", "supergroup"}:
            await message.reply("ℹ️ این دستور فقط داخل گروه بازی است."); raise CancelHandler()
        renderer = getattr(app, "_render_lobby_authority", None)
        game = app.runtime.state.active_game(message.chat.id)
        if not game or str(game.get("status") or "") != "lobby":
            await message.reply("ℹ️ لابی فعالی وجود ندارد."); raise CancelHandler()
        if renderer:
            # The canonical renderer expects a callback-like object. The text
            # command sends a fresh lobby message instead, so use its own helper.
            r = app.runtime.state.scenarios.get_by_id(int(game["scenario_id"])) if game.get("scenario_id") else None
            rows = app.runtime.state.games.list_players(game["id"])
            cap = len((r or {}).get("roles") or [])
            active = sorted([x for x in rows if x.get("seat") is not None and str(x.get("status") or "active") not in {"removed", "dead", "finished", "kicked"}], key=lambda x:int(x.get("seat") or 999))
            occupied = {int(x["seat"]):x for x in active}
            def nm(x): return str(x.get("nickname") or x.get("first_name") or x.get("username") or x.get("player_id") or "👤")
            def men(x): return f'<a href="tg://user?id={int(x["player_id"])}"><b>{html.escape(nm(x))}</b></a>'
            lines=["🏠 <b>لابی فعال</b>", f"🎭 سناریو: <b>{html.escape(str((r or {}).get('name') or '---'))}</b>", f"👥 بازیکنان: <b>{len(active)}/{cap}</b>", "", "🪑 <b>لیست صندلی‌ها</b>"]
            lines += [f"{s:02d}. {men(occupied[s]) if s in occupied else '⬜ آزاد'}" for s in range(1,cap+1)]
            await message.reply("\n".join(lines), parse_mode="HTML", reply_markup=InlineKeyboardMarkup(row_width=3).add(*[InlineKeyboardButton(f"{s:02d} {'🔒' if s in occupied else '🪑'}", callback_data=f"lobby:{int(game['id'])}:seat:{s}") for s in range(1,cap+1)]))
        raise CancelHandler()

    async def attendance_command(message):
        if message.chat.type not in {"group", "supergroup"}:
            await message.reply("ℹ️ این دستور فقط داخل گروه بازی است."); raise CancelHandler()
        game = app.runtime.state.active_game(message.chat.id)
        if not game or str(game.get("status") or "") != "lobby":
            await message.reply("ℹ️ لابی فعالی وجود ندارد."); raise CancelHandler()
        renderer = getattr(app, "_render_attendance_authority", None)
        if renderer:
            await renderer(message); raise CancelHandler()
        await message.reply("📢 حاضری فعال نیست."); raise CancelHandler()

    async def substitute_command(message):
        if message.chat.type not in {"group", "supergroup"}:
            await message.reply("ℹ️ این دستور فقط داخل گروه بازی است."); raise CancelHandler()
        game = app.runtime.state.active_game(message.chat.id)
        if not game or str(game.get("status") or "") != "lobby":
            await message.reply("ℹ️ فقط در لابی فعال می‌توان وارد لیست جایگزین شد."); raise CancelHandler()
        target = message.reply_to_message.from_user if message.reply_to_message else message.from_user
        rows = app.runtime.state.games.list_players(game["id"])
        existing = next((r for r in rows if int(r.get("player_id")) == int(target.id)), None)
        if existing:
            if existing.get("seat") is not None:
                await message.reply("ℹ️ این کاربر در لیست اصلی بازی است."); raise CancelHandler()
            if str(existing.get("status") or "") == "waiting":
                await message.reply("ℹ️ این کاربر قبلاً در لیست جایگزین است."); raise CancelHandler()
        try:
            app.runtime.state.lobby.join(game["id"], int(target.id), None, is_substitute=True)
        except ValueError:
            await message.reply("❌ افزودن به لیست جایگزین انجام نشد."); raise CancelHandler()
        await message.reply(f"✅ {html.escape(str(target.full_name))} به لیست جایگزین اضافه شد.", parse_mode="HTML")
        raise CancelHandler()

    dp.register_message_handler(cancel_text_handler, lambda m: (m.text or "").strip().casefold().replace("‌", " ") in {"لغو بازی", "/لغو_بازی", "/cancel_game", "/cancelgame"}, content_types="text", state="*")
    dp.register_message_handler(substitute_command, lambda m: (m.text or "").strip().casefold() == "جایگزین", content_types="text", state="*")
    dp.register_message_handler(attendance_command, lambda m: (m.text or "").strip().casefold() == "حاضری", content_types="text", state="*")
    dp.register_message_handler(lobby_command, lambda m: (m.text or "").strip().casefold() == "لابی", content_types="text", state="*")

    registry = getattr(getattr(dp, "message_handlers", None), "handlers", [])
    # Exact final commands first. Then the completed game-command surfaces.
    _move_front(registry, lambda fn: _module_name(fn) == "commands" and _name(fn) == "handle_text_commands")
    _move_front(registry, lambda fn: _module_name(fn) == "runtime.text_commands" and _name(fn) == "command")
    _move_front(registry, lambda fn: _module_name(fn) == "runtime.player_kick" and _name(fn) == "text_command")
    _move_front(registry, lambda fn: _module_name(fn) == "runtime.command_surface_v2" and _name(fn) == "command")
    _move_front(registry, lambda fn: _module_name(fn) == "runtime.command_surface_v3" and _name(fn) == "command")
    _move_front(registry, lambda fn: _module_name(fn) == "runtime.end_game_control" and _name(fn) == "finish_command")
    _move_front(registry, lambda fn: _module_name(fn) == "runtime.command_authority_final" and _name(fn) == "cancel_text_handler")
    _move_front(registry, lambda fn: _module_name(fn) == "runtime.command_authority_final" and _name(fn) in {"substitute_command", "attendance_command", "lobby_command"})

    logging.info("FINAL TEXT COMMAND AUTHORITY active: lobby=active attendance=active substitute=active cancel=active finish=v3")
    return True
