from __future__ import annotations

import html
import logging
from aiogram.dispatcher.handler import CancelHandler
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from repositories.scenario_repository import ScenarioRepository


def _reg(main):
    return getattr(getattr(main.dp, "callback_query_handlers", None), "handlers", [])


def install(main):
    if getattr(main, "_lobby_ui_v11_installed", False):
        return False
    main._lobby_ui_v11_installed = True
    repo = ScenarioRepository()
    dp = main.dp

    def game(gid):
        return main.runtime.state.active_game(int(gid))

    def players(g):
        return main.runtime.state.games.list_players(g["id"]) if g else []

    def mention(uid, fallback=None):
        try:
            name = main.display_name(int(uid), fallback or main.players.get(int(uid)))
        except Exception:
            name = fallback or main.players.get(int(uid)) or str(uid)
        return f'<a href="tg://user?id={int(uid)}"><b>{html.escape(str(name))}</b></a>'

    def render_data(gid):
        g = game(gid)
        row = None
        try:
            sid = (g or {}).get("scenario_id")
            row = repo.get_by_id(int(sid)) if sid else None
        except Exception:
            row = None
        ps = players(g)
        active = [p for p in ps if p.get("seat") is not None and str(p.get("status") or "active") not in {"removed", "dead"}]
        waiting = [p for p in ps if p.get("seat") is None and str(p.get("status") or "waiting") == "waiting"]
        active.sort(key=lambda p: int(p.get("seat") or 999))
        cap = len((row or {}).get("roles") or [])
        lines = [
            "༄", "    <b>Mafia Nights</b>", "",
            f"📝 <b>سناریو:</b> {html.escape(str((row or {}).get('name') or '---'))}",
            f"🎩 <b>گرداننده:</b> {mention(g.get('moderator_id')) if g and g.get('moderator_id') else '---'}",
            f"👥 <b>بازیکنان:</b> {len(active)}/{cap}", "",
            "◤◢◣◥◤◢◣◥◤◢◣◥", "        <b>لیست بازیکنان</b>",
            "◤◢◣◥◤◢◣◥◤◢◣◥", "",
        ]
        for p in active:
            lines.append(f"{int(p['seat']):02d} {mention(int(p['player_id']), p.get('nickname') or p.get('first_name') or p.get('username'))}")
        if not active:
            lines.append("— هنوز بازیکنی وارد بازی نشده است.")
        if waiting:
            lines += ["", "🎟 <b>لیست رزرو</b>"]
            for i, p in enumerate(waiting, 1):
                lines.append(f"{i}. {mention(int(p['player_id']), p.get('nickname') or p.get('first_name') or p.get('username'))}")
        lines += ["", "◤◢◣◥◤◢◣◥◤◢◣◥", "༄"]

        kb = InlineKeyboardMarkup(row_width=2)
        kb.row(
            InlineKeyboardButton("🔄 ورود / خروج", callback_data="lv10_toggle"),
            InlineKeyboardButton("🎟 رزرو / لغو رزرو", callback_data="lv10_reserve"),
        )
        kb.row(
            InlineKeyboardButton("📝 تغییر سناریو", callback_data=f"mgmt:{g['id']}:scenario"),
            InlineKeyboardButton("⚙️ مدیریت بازی", callback_data="lv10_manage"),
        )
        kb.row(
            InlineKeyboardButton("⭐ امکانات ویژه", callback_data="lv10_special"),
            InlineKeyboardButton("🚫 لغو بازی", callback_data="lv10_cancel"),
        )
        kb.add(InlineKeyboardButton("📢 تگ لیست / حاضری", callback_data="lv10_attendance"))
        return "\n".join(lines), kb

    async def render_message(message, gid):
        text, kb = render_data(gid)
        await message.edit_text(text, parse_mode="HTML", reply_markup=kb)
        main.lobby_message_id = message.message_id
        try:
            game_row = game(gid)
            if game_row:
                state = dict(game_row.get("state") or {})
                state["lobby_message_id"] = int(message.message_id)
                main.runtime.state.games.update_game(game_row["id"], state=state)
        except Exception:
            logging.exception("failed to persist lobby message id")

    async def moderator(c):
        gid = int(c.message.chat.id)
        try:
            uid = int(str(c.data).split(":", 1)[1])
        except Exception:
            await c.answer("❌ گرداننده نامعتبر است.", show_alert=True)
            raise CancelHandler()
        admins = {int(a.user.id) for a in await main.bot.get_chat_administrators(gid)}
        if uid not in admins:
            await c.answer("❌ گرداننده باید مدیر گروه باشد.", show_alert=True)
            raise CancelHandler()
        g = game(gid)
        if not g:
            await c.answer("❌ بازی فعال پیدا نشد.", show_alert=True)
            raise CancelHandler()
        main.runtime.lobby.set_moderator(gid, uid)
        main.moderator_id = uid
        main.group_chat_id = gid
        main.lobby_active = True
        main.game_running = False
        main.round_active = False
        main._lv6_setup = False
        main._lv6_change_scenario = False
        await render_message(c.message, gid)
        await c.answer("✅ لابی اصلی آماده شد")
        raise CancelHandler()

    async def refresh_renderer(gid, game_row=None):
        message_id = None
        try:
            message_id = int((game_row or game(gid) or {}).get("state", {}).get("lobby_message_id"))
        except Exception:
            pass
        message_id = message_id or getattr(main, "lobby_message_id", None)
        if not message_id:
            return False
        try:
            text, kb = render_data(gid)
            await main.bot.edit_message_text(text, int(gid), int(message_id), parse_mode="HTML", reply_markup=kb)
            main.lobby_message_id = int(message_id)
            return True
        except Exception:
            logging.exception("v11 production lobby refresh failed group=%s", gid)
            return False

    main._render_production_lobby = refresh_renderer

    dp.register_callback_query_handler(moderator, lambda c: str(c.data or "").startswith("lv9_m:"), state="*")
    reg = _reg(main)
    for i, item in enumerate(reg):
        if getattr(item, "callback", None) is moderator:
            reg.insert(0, reg.pop(i))
            break

    logging.info("LOBBY_UI_V11_CUTOVER active: moderator selection now renders canonical v10 lobby")
    return True
