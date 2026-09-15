from __future__ import annotations

import html
import logging
from aiogram.dispatcher.handler import CancelHandler
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from repositories.scenario_repository import ScenarioRepository
from runtime.scenario_runtime import ScenarioRuntime


def _reg(main):
    return getattr(getattr(main.dp, "callback_query_handlers", None), "handlers", [])


def install(main):
    if getattr(main, "_lobby_ui_v10_installed", False):
        return False
    main._lobby_ui_v10_installed = True
    repo = ScenarioRepository()
    dp = main.dp

    def game(gid):
        return main.runtime.state.active_game(int(gid))

    def scenario_row(g):
        sid = (g or {}).get("scenario_id")
        try:
            return repo.get_by_id(int(sid)) if sid else None
        except Exception:
            return None

    def players(g):
        return main.runtime.state.games.list_players(g["id"]) if g else []

    def name(r):
        return str(r.get("nickname") or r.get("first_name") or r.get("username") or r.get("player_id") or "👤")

    def mention(uid, fallback=None):
        try:
            n = main.display_name(int(uid), fallback or main.players.get(int(uid)))
        except Exception:
            n = fallback or main.players.get(int(uid)) or str(uid)
        return f'<a href="tg://user?id={int(uid)}"><b>{html.escape(str(n))}</b></a>'

    async def allowed(c, g):
        uid = int(c.from_user.id)
        if uid == int((g or {}).get("moderator_id") or 0):
            return True
        try:
            return (await main.bot.get_chat_member(int(c.message.chat.id), uid)).status in {"creator", "administrator"}
        except Exception:
            return False

    def state(g):
        return dict((g or {}).get("state") or {})

    def save(g, **changes):
        s = state(g); s.update(changes); g["state"] = s
        return main.runtime.state.games.update_game(g["id"], state=s)

    def lobby_view(gid):
        g = game(gid)
        row = scenario_row(g)
        ps = players(g)
        active = [p for p in ps if p.get("seat") is not None and str(p.get("status") or "active") not in {"removed", "dead"}]
        waiting = [p for p in ps if p.get("seat") is None and str(p.get("status") or "waiting") == "waiting"]
        cap = len((row or {}).get("roles") or [])
        active.sort(key=lambda p: int(p.get("seat") or 999))
        lines = ["༄", "    <b>Mafia Nights</b>", "", f"📝 <b>سناریو:</b> {html.escape(str((row or {}).get('name') or '---'))}", f"🎩 <b>گرداننده:</b> {mention(g.get('moderator_id'))}", f"👥 <b>بازیکنان:</b> {len(active)}/{cap}", "", "◤◢◣◥◤◢◣◥◤◢◣◥", "        <b>لیست بازیکنان</b>", "◤◢◣◥◤◢◣◥◤◢◣◥", ""]
        for p in active:
            lines.append(f"{int(p['seat']):02d} {mention(int(p['player_id']), name(p))}")
        if not active:
            lines.append("— هنوز بازیکنی وارد بازی نشده است.")
        if waiting:
            lines += ["", "🎟 <b>لیست رزرو</b>"]
            for i, p in enumerate(waiting, 1):
                lines.append(f"{i}. {mention(int(p['player_id']), name(p))}")
        lines += ["", "◤◢◣◥◤◢◣◥◤◢◣◥", "༄"]

        settings = state(g).get("lobby_settings") or {}
        kb = InlineKeyboardMarkup(row_width=2)
        in_game = {int(p["player_id"]) for p in active}
        # Telegram inline-button labels are shared by everyone. Therefore the
        # button is a true per-user toggle in its callback, rather than two
        # competing static buttons which can get out of sync.
        kb.row(InlineKeyboardButton("🔄 ورود / خروج", callback_data="lv10_toggle"), InlineKeyboardButton("🎟 رزرو / لغو رزرو", callback_data="lv10_reserve"))
        kb.row(InlineKeyboardButton("📝 تغییر سناریو", callback_data=f"mgmt:{g['id']}:scenario"), InlineKeyboardButton("⚙️ مدیریت بازی", callback_data="lv10_manage"))
        kb.row(InlineKeyboardButton("⭐ امکانات ویژه", callback_data="lv10_special"), InlineKeyboardButton("🚫 لغو بازی", callback_data="lv10_cancel"))
        kb.add(InlineKeyboardButton("📢 تگ لیست / حاضری", callback_data="lv10_attendance"))
        return "\n".join(lines), kb

    async def render(c):
        gid = int(c.message.chat.id)
        text, kb = lobby_view(gid)
        await c.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
        main.lobby_message_id = c.message.message_id

    async def toggle(c):
        gid = int(c.message.chat.id); uid = int(c.from_user.id); g = game(gid); row = scenario_row(g)
        if not g or not row:
            await c.answer("❌ لابی معتبر نیست.", show_alert=True); return
        ps = players(g); current = next((p for p in ps if int(p["player_id"]) == uid), None)
        active = [p for p in ps if p.get("seat") is not None and str(p.get("status") or "active") not in {"removed", "dead"}]
        cap = len(row.get("roles") or [])
        if current and current.get("seat") is not None:
            main.runtime.state.lobby.leave(g["id"], uid)
            try: main.runtime.lobby.promote_waiting(gid, int(current["seat"]))
            except Exception: pass
            await render(c); await c.answer("🚪 از بازی خارج شدید"); return
        if current and current.get("seat") is None and str(current.get("status") or "") == "waiting":
            main.runtime.state.lobby.leave(g["id"], uid)
            await render(c); await c.answer("🎟 رزرو شما لغو شد"); return
        if len(active) >= cap:
            await c.answer("🎟 ظرفیت اصلی تکمیل است؛ از «رزرو / لغو رزرو» استفاده کنید.", show_alert=True); return
        occupied = {int(p["seat"]) for p in active}
        seat = next((n for n in range(1, cap + 1) if n not in occupied), None)
        if seat is None:
            await c.answer("🎟 ظرفیت اصلی تکمیل است؛ از «رزرو / لغو رزرو» استفاده کنید.", show_alert=True); return
        main.runtime.state.lobby.join(g["id"], uid, seat)
        await render(c); await c.answer(f"✅ وارد بازی شدید؛ صندلی {seat}")

    async def reserve(c):
        gid = int(c.message.chat.id); uid = int(c.from_user.id); g = game(gid); row = scenario_row(g)
        if not g or not row:
            await c.answer("❌ لابی معتبر نیست.", show_alert=True); return
        ps = players(g); current = next((p for p in ps if int(p["player_id"]) == uid), None)
        active = [p for p in ps if p.get("seat") is not None and str(p.get("status") or "active") not in {"removed", "dead"}]
        cap = len(row.get("roles") or [])
        if current and current.get("seat") is None and str(current.get("status") or "") == "waiting":
            main.runtime.state.lobby.leave(g["id"], uid); await render(c); await c.answer("❌ رزرو شما لغو شد"); return
        if current and current.get("seat") is not None:
            await c.answer("ℹ️ شما داخل بازی هستید.", show_alert=True); return
        if len(active) < cap:
            await c.answer("ℹ️ تا قبل از تکمیل ظرفیت، رزرو فعال نیست.", show_alert=True); return
        main.runtime.state.lobby.join(g["id"], uid, None, is_substitute=True)
        await render(c); await c.answer("🎟 رزرو شما ثبت شد")

    async def manage(c):
        from runtime.game_management import GameManagement
        g = game(int(c.message.chat.id))
        if not g or not await allowed(c, g):
            await c.answer("⛔ دسترسی ندارید یا بازی فعال نیست.", show_alert=True); return
        await GameManagement(main).open(c)

    async def cancel(c):
        from runtime.game_management import GameManagement
        g = game(int(c.message.chat.id))
        if not g or not await allowed(c, g):
            await c.answer("⛔ دسترسی ندارید.", show_alert=True); return
        await GameManagement(main).cancel(c)

    def special_kb(g):
        s = state(g); ch = dict(s.get("challenge_settings") or {}); nx = dict(s.get("next_settings") or {}); ui = dict(s.get("ui_settings") or {})
        enabled = bool(ch.get("enabled", True)); mode = str(ch.get("mode") or "limited"); mark = bool(ch.get("show_player_status", True))
        pnext = bool(nx.get("allow_players_next", True)); mnext = bool(nx.get("allow_moderator_next", True))
        tc = str(ui.get("turn_color") or "🟢"); cc = str(ui.get("challenge_color") or "🟣")
        kb = InlineKeyboardMarkup(row_width=2)
        kb.row(InlineKeyboardButton(f"{'🟢' if enabled else '🔴'} وضعیت چالش: {'فعال' if enabled else 'غیرفعال'}", callback_data="lv10_ch_enabled"), InlineKeyboardButton(f"⚔ محدودیت: {'آزاد' if mode == 'free' else 'محدود'}", callback_data="lv10_ch_mode"))
        kb.row(InlineKeyboardButton(f"🤏 علامت چالش: {'روشن' if mark else 'خاموش'}", callback_data="lv10_ch_mark"), InlineKeyboardButton(f"👤 نکست بازیکن: {'فعال' if pnext else 'غیرفعال'}", callback_data="lv10_pnext"))
        kb.row(InlineKeyboardButton(f"🎩 نکست گرداننده: {'فعال' if mnext else 'غیرفعال'}", callback_data="lv10_mnext"), InlineKeyboardButton(f"🎨 رنگ ترن: {tc}", callback_data="lv10_turn_color"))
        kb.row(InlineKeyboardButton(f"⚔️ رنگ چالش: {cc}", callback_data="lv10_ch_color"), InlineKeyboardButton("⬅️ بازگشت به لابی", callback_data="lv10_back"))
        return kb

    async def special(c):
        g = game(int(c.message.chat.id))
        if not g or not await allowed(c, g): await c.answer("⛔ فقط گرداننده یا مدیر گروه.", show_alert=True); return
        s=state(g); ch=dict(s.get("challenge_settings") or {}); nx=dict(s.get("next_settings") or {}); ui=dict(s.get("ui_settings") or {})
        text=("⭐ <b>امکانات ویژه لابی</b>\n\n"
              f"⚔ وضعیت چالش: <b>{'فعال' if ch.get('enabled', True) else 'غیرفعال'}</b>\n"
              f"⚔ محدودیت چالش: <b>{'آزاد' if ch.get('mode','limited') == 'free' else 'محدود'}</b>\n"
              f"🤏 علامت چالش: <b>{'فعال' if ch.get('show_player_status', True) else 'غیرفعال'}</b>\n"
              f"👤 نکست بازیکن: <b>{'فعال' if nx.get('allow_players_next', True) else 'غیرفعال'}</b>\n"
              f"🎩 نکست گرداننده: <b>{'فعال' if nx.get('allow_moderator_next', True) else 'غیرفعال'}</b>\n"
              f"🎨 رنگ ترن: <b>{ui.get('turn_color','🟢')}</b>\n⚔️ رنگ چالش: <b>{ui.get('challenge_color','🟣')}</b>")
        await c.message.edit_text(text, parse_mode="HTML", reply_markup=special_kb(g)); await c.answer()

    async def mutate(c, key):
        g=game(int(c.message.chat.id))
        if not g or not await allowed(c,g): await c.answer("⛔ دسترسی ندارید.",show_alert=True); return
        s=state(g); ch=dict(s.get("challenge_settings") or {}); nx=dict(s.get("next_settings") or {}); ui=dict(s.get("ui_settings") or {})
        if key == "enabled": ch["enabled"] = not bool(ch.get("enabled", True)); main.challenge_active = ch["enabled"]
        elif key == "mode": ch["mode"] = "free" if ch.get("mode","limited") != "free" else "limited"
        elif key == "mark": ch["show_player_status"] = not bool(ch.get("show_player_status", True))
        elif key == "pnext": nx["allow_players_next"] = not bool(nx.get("allow_players_next", True))
        elif key == "mnext": nx["allow_moderator_next"] = not bool(nx.get("allow_moderator_next", True))
        elif key in {"turn_color","ch_color"}:
            colors=["🟢","🔵","🟡","🔴","🟣","🟠","⚪"]
            field="turn_color" if key == "turn_color" else "challenge_color"
            ui[field]=colors[(colors.index(ui.get(field,"🟢")) + 1) % len(colors)]
        save(g, challenge_settings=ch, next_settings=nx, ui_settings=ui)
        await special(c)

    async def attendance(c):
        g=game(int(c.message.chat.id)); ps=players(g) if g else []
        active=[p for p in ps if p.get("seat") is not None and str(p.get("status") or "active") not in {"removed"}]
        if not active: await c.answer("👥 بازیکنی در بازی نیست.",show_alert=True); return
        ready=set((state(g).get("ready_players") or [])); tags=[]
        for p in sorted(active,key=lambda x:int(x.get("seat") or 999)):
            uid=int(p["player_id"]); tags.append(f"{'✅' if uid in ready else '⬜'} {int(p['seat']):02d}. {mention(uid,name(p))}")
        kb=InlineKeyboardMarkup(row_width=1).add(InlineKeyboardButton("🙋‍♂️ آماده‌ام",callback_data="lv10_ready"), InlineKeyboardButton("⬅️ بازگشت به لابی",callback_data="lv10_back"))
        await c.message.edit_text("📢 <b>تگ لیست / حاضری</b>\n\n" + "\n".join(tags) + "\n\n" + " ".join(mention(int(p["player_id"]),name(p)) for p in active), parse_mode="HTML", reply_markup=kb); await c.answer()

    async def ready(c):
        g=game(int(c.message.chat.id)); uid=int(c.from_user.id)
        if not g or not any(int(p["player_id"])==uid and p.get("seat") is not None for p in players(g)):
            await c.answer("⛔ فقط بازیکنان داخل بازی می‌توانند آماده شوند.",show_alert=True); return
        s=state(g); ready=set(s.get("ready_players") or []); ready.add(uid); save(g,ready_players=list(ready)); await attendance(c); await c.answer("✅ آماده‌ام ثبت شد")

    async def change_scenario(c):
        from runtime.game_management import GameManagement
        g=game(int(c.message.chat.id))
        if not g or not await allowed(c,g): await c.answer("⛔ دسترسی ندارید.",show_alert=True); return
        await GameManagement(main).scenario(c)

    async def back(c): await render(c); await c.answer()

    callbacks = [
        (toggle, lambda c: c.data == "lv10_toggle"),
        (reserve, lambda c: c.data == "lv10_reserve"),
        (manage, lambda c: c.data == "lv10_manage"),
        (cancel, lambda c: c.data == "lv10_cancel"),
        (special, lambda c: c.data == "lv10_special"),
        (attendance, lambda c: c.data == "lv10_attendance"),
        (ready, lambda c: c.data == "lv10_ready"),
        (back, lambda c: c.data == "lv10_back"),
        (change_scenario, lambda c: c.data == "lv10_change_scenario"),
        (lambda c: mutate(c,"enabled"), lambda c: c.data == "lv10_ch_enabled"),
        (lambda c: mutate(c,"mode"), lambda c: c.data == "lv10_ch_mode"),
        (lambda c: mutate(c,"mark"), lambda c: c.data == "lv10_ch_mark"),
        (lambda c: mutate(c,"pnext"), lambda c: c.data == "lv10_pnext"),
        (lambda c: mutate(c,"mnext"), lambda c: c.data == "lv10_mnext"),
        (lambda c: mutate(c,"turn_color"), lambda c: c.data == "lv10_turn_color"),
        (lambda c: mutate(c,"ch_color"), lambda c: c.data == "lv10_ch_color"),
    ]
    for fn, flt in callbacks:
        dp.register_callback_query_handler(fn, flt, state="*")
        r=_reg(main)
        for i,item in enumerate(r):
            if getattr(item,"callback",None) is fn:
                r.insert(0,r.pop(i)); break
    logging.info("LOBBY_UI_V10 active: toggle join/leave + reservation + management + special settings + attendance")
    return True
