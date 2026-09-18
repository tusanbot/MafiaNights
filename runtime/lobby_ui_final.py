from __future__ import annotations
import html
import logging
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from repositories.scenario_repository import ScenarioRepository
from runtime.scenario_runtime import ScenarioRuntime


def install(main):
    if getattr(main, "_final_lobby_installed", False) and getattr(main, "_canonical_new_game_handler", None) is not None:
        return False
    main._final_lobby_installed = True
    dp = main.dp
    repo = ScenarioRepository()

    def handler_of(item):
        return getattr(item, "handler", None) or getattr(item, "callback", None)

    def move_front(registry, fn):
        for i, item in enumerate(registry):
            if handler_of(item) is fn:
                registry.insert(0, registry.pop(i))
                return True
        return False

    old_names = {"start_game", "choose_scenario", "scenario_selected", "choose_moderator", "moderator_selected", "handle_slot"}
    cr = getattr(getattr(dp, "callback_query_handlers", None), "handlers", [])
    cr[:] = [x for x in cr if getattr(handler_of(x), "__name__", "") not in old_names]
    mr = getattr(getattr(dp, "message_handlers", None), "handlers", [])
    mr[:] = [x for x in mr if getattr(handler_of(x), "__name__", "") != "start_cmd"]
    logging.info("FINAL_LOBBY_CUTOVER legacy lobby/start handlers removed")

    def game(gid):
        return main.runtime.state.active_game(int(gid))

    def players(g):
        return main.runtime.state.games.list_players(g["id"]) if g else []

    def scenario(g):
        try:
            return repo.get_by_id(int(g["scenario_id"])) if g and g.get("scenario_id") else None
        except Exception:
            return None

    def state(g):
        return dict((g or {}).get("state") or {})

    def save(g, **changes):
        s = state(g); s.update(changes); g["state"] = s
        return main.runtime.state.games.update_game(g["id"], state=s)

    def pname(p):
        return str(p.get("nickname") or p.get("first_name") or p.get("username") or p.get("player_id") or "👤")

    def mention(uid, fallback=None):
        try: n = main.display_name(int(uid), fallback or main.players.get(int(uid)))
        except Exception: n = fallback or main.players.get(int(uid)) or str(uid)
        return f'<a href="tg://user?id={int(uid)}"><b>{html.escape(str(n))}</b></a>'

    async def allowed(c, g):
        if int(c.from_user.id) == int((g or {}).get("moderator_id") or 0): return True
        try:
            m = await main.bot.get_chat_member(int(c.message.chat.id), int(c.from_user.id))
            return m.status in {"creator", "administrator"}
        except Exception: return False

    def lobby_view(gid):
        g = game(gid); r = scenario(g); ps = players(g)
        active = [p for p in ps if p.get("seat") is not None and str(p.get("status") or "active") not in {"removed", "dead", "finished", "kicked"}]
        waiting = [p for p in ps if p.get("seat") is None and str(p.get("status") or "waiting") in {"waiting", "substitute"}]
        active.sort(key=lambda p: int(p.get("seat") or 999))
        cap = len((r or {}).get("roles") or [])
        occupied = {int(p["seat"]): p for p in active if p.get("seat") is not None}
        full = cap > 0 and len(active) >= cap
        moderator_id = int((g or {}).get("moderator_id") or 0)
        moderator_row = next((p for p in ps if int(p.get("player_id") or 0) == moderator_id), None)
        moderator_label = pname(moderator_row) if moderator_row else (
            str((g or {}).get("state", {}).get("moderator_name") or "❓") if g else "❓"
        )
        lines = [
            "༄", "    <b>Mafia Nights</b>", "",
            f"📝 <b>سناریو:</b> {html.escape(str((r or {}).get('name') or '---'))}",
            f"🎩 <b>گرداننده:</b> {mention(moderator_id, moderator_label) if moderator_id else '❌ انتخاب نشده'}",
            f"👥 <b>بازیکنان:</b> {len(active)}/{cap}", "",
            "━━━━━━━━━━━━━━━━━━", "🪑 <b>لیست صندلی‌ها</b>"
        ]
        for seat_no in range(1, cap + 1):
            row = occupied.get(seat_no)
            lines.append(f"{seat_no:02d}. {mention(int(row['player_id']), pname(row)) if row else '⬜ آزاد'}")
        if waiting:
            lines += ["", "🎟 <b>لیست رزرو</b>"] + [
                f"{i}. {mention(int(p['player_id']), pname(p))}" for i, p in enumerate(waiting, 1)
            ]
        lines += ["", "━━━━━━━━━━━━━━━━━━", "༄"]

        kb = InlineKeyboardMarkup(row_width=3)
        for seat_no in range(1, cap + 1):
            row = occupied.get(seat_no)
            label = f"{seat_no:02d} {pname(row)[:10]}" if row else f"{seat_no:02d} ⬜"
            kb.insert(InlineKeyboardButton(label, callback_data=f"fl_seat:{seat_no}"))
        kb.row(
            InlineKeyboardButton("🚪 ورود / خروج", callback_data="fl_toggle"),
        )
        if full:
            kb.row(InlineKeyboardButton("🎟 رزرو / لغو رزرو", callback_data="fl_reserve"))
            kb.row(InlineKeyboardButton("🎭 پخش نقش", callback_data="distribute_roles"))
        kb.row(
            InlineKeyboardButton("📝 تغییر سناریو", callback_data="fl_scenario"),
            InlineKeyboardButton("⚙️ مدیریت بازی", callback_data="fl_manage"),
        )
        kb.row(
            InlineKeyboardButton("⭐ امکانات ویژه", callback_data="fl_special"),
            InlineKeyboardButton("🚫 لغو بازی", callback_data="fl_cancel"),
        )
        return "\n".join(lines), kb

    async def start_command(message):
        if message.chat.type in {"group", "supergroup"}:
            kb = InlineKeyboardMarkup(row_width=1).add(
                InlineKeyboardButton("🎮 بازی جدید", callback_data="fl_new")
            )
            await message.reply(
                "🏠 <b>منوی اصلی Mafia Nights</b>",
                parse_mode="HTML",
                reply_markup=kb,
            )
        else:
            kb = InlineKeyboardMarkup(row_width=1)
            kb.add(InlineKeyboardButton("⚙️ مدیریت بازی", callback_data="manage_game"))
            kb.add(InlineKeyboardButton("📜 مدیریت سناریو", callback_data="manage_scenarios"))
            kb.add(InlineKeyboardButton("⚙ امکانات اضافه", callback_data="addons_menu"))
            kb.add(InlineKeyboardButton("❓ راهنما", callback_data="help"))
            await message.reply(
                "📋 <b>پنل Mafia Nights</b>",
                parse_mode="HTML",
                reply_markup=kb,
            )

    async def new(c):
        gid = int(c.message.chat.id)
        if getattr(main, "game_running", False) or getattr(main, "round_active", False):
            await c.answer("⚠️ بازی در حال اجراست.", show_alert=True)
            return
        main.group_chat_id = gid
        main.lobby_active = True
        main.game_running = False
        main.round_active = False
        try:
            main.runtime.lobby.ensure(gid)
        except Exception:
            logging.exception("lobby ensure failed")
        kb = InlineKeyboardMarkup(row_width=3)
        rows = repo.list_active()
        popular = {"پدرخوانده-جک", "پدرخوانده-شرلوک", "پدرخوانده-نوسترا", "کلاسیک 12", "کلاسیک 13", "قمار باز", "زودیاک", "کاپو"}
        rows.sort(key=lambda x: (
            0 if x.get("name") in popular else 1,
            int(x.get("sort_order") or 0),
            int(x.get("id") or 0),
        ))
        for r in rows:
            kb.insert(
                InlineKeyboardButton(
                    f"{str(r.get('name') or '')[:18]} ({len(r.get('roles') or [])})",
                    callback_data=f"fl_pick:{int(r['id'])}",
                )
            )
        # For the text-command adapter the incoming Telegram Message cannot
        # be edited, so send the lobby as a reply instead.
        if getattr(c, "_from_text_command", False):
            sent = await c.message.reply(
                text,
                parse_mode="HTML",
                reply_markup=kb,
            )
            main.lobby_message_id = sent.message_id
        else:
            await c.message.edit_text(
                text,
                parse_mode="HTML",
                reply_markup=kb,
            )
        await c.answer()

    async def render(c):
        text, kb = lobby_view(c.message.chat.id)
        # A real callback can edit the existing lobby message. The text-command
        # adapter receives a normal Telegram Message, which cannot be edited.
        # In that case create the canonical lobby message first.
        if getattr(c, "_from_text_command", False):
            sent = await c.message.reply(
                "📝 <b>انتخاب سناریو</b>\n\nسناریوی بازی را انتخاب کنید:",
                parse_mode="HTML",
                reply_markup=kb,
            )
            main.lobby_message_id = sent.message_id
        else:
            await c.message.edit_text(
                "📝 <b>انتخاب سناریو</b>\n\nسناریوی بازی را انتخاب کنید:",
                parse_mode="HTML",
                reply_markup=kb,
            )
        await c.answer()

    # Expose the canonical callback owner to the actual webhook entrypoint.
    # This prevents legacy text handlers from intercepting «بازی جدید».
    main._canonical_new_game_handler = new

    async def pick(c):
        try: sid = int(str(c.data).split(":",1)[1]); r = repo.get_by_id(sid)
        except Exception: r = None
        if not r or not r.get("is_active",True): await c.answer("❌ سناریو نامعتبر است.",show_alert=True); return
        g = game(c.message.chat.id)
        if not g: await c.answer("❌ بازی فعال پیدا نشد.",show_alert=True); return
        try:
            ScenarioRuntime(main).apply_to_game(str(g["id"]), sid)
            main.selected_scenario = str(r["name"]); main.MAX_SEATS = len(r.get("roles") or [])
        except Exception:
            logging.exception("scenario save failed"); await c.answer("❌ ذخیره سناریو انجام نشد.",show_alert=True); return
        kb = InlineKeyboardMarkup(row_width=2)
        for a in await main.bot.get_chat_administrators(int(c.message.chat.id)):
            kb.insert(InlineKeyboardButton(a.user.full_name[:24], callback_data=f"fl_mod:{a.user.id}"))
        await c.message.edit_text(f"📝 <b>{html.escape(str(r['name']))}</b>\n\n🎩 <b>انتخاب گرداننده</b>",parse_mode="HTML",reply_markup=kb)
        await c.answer("✅ سناریو انتخاب شد")

    async def moderator(c):
        gid = int(c.message.chat.id); uid = int(str(c.data).split(":",1)[1])
        admins = {int(a.user.id) for a in await main.bot.get_chat_administrators(gid)}
        if uid not in admins: await c.answer("❌ گرداننده باید مدیر گروه باشد.",show_alert=True); return
        try:
            member = await main.bot.get_chat_member(gid, uid)
            moderator_name = main.display_name(uid, member.user.full_name)
        except Exception:
            moderator_name = main.display_name(uid, None) or str(uid)
        main.runtime.lobby.set_moderator(gid,uid); main.moderator_id=uid; main.group_chat_id=gid; main.lobby_active=True; main.game_running=False; main.round_active=False
        g = game(gid)
        if g:
            save(g, moderator_name=str(moderator_name))
        await render(c); await c.answer("✅ لابی نهایی فعال شد")

    async def toggle(c):
        g = game(c.message.chat.id); r = scenario(g); uid = int(c.from_user.id)
        if not g or not r: await c.answer("❌ لابی معتبر نیست.",show_alert=True); return
        ps = players(g); cur = next((p for p in ps if int(p["player_id"])==uid),None)
        active = [p for p in ps if p.get("seat") is not None and str(p.get("status") or "active") not in {"removed","dead"}]
        cap = len(r.get("roles") or [])
        if cur and cur.get("seat") is not None:
            seat=int(cur["seat"]); main.runtime.state.lobby.leave(g["id"],uid)
            try: main.runtime.lobby.promote_waiting(c.message.chat.id,seat)
            except Exception: pass
            await render(c); await c.answer("🚪 از بازی خارج شدید"); return
        if cur and cur.get("seat") is None and str(cur.get("status") or "")=="waiting":
            main.runtime.state.lobby.leave(g["id"],uid); await render(c); await c.answer("🎟 رزرو شما لغو شد"); return
        if len(active)>=cap: await c.answer("🎟 ظرفیت اصلی تکمیل است؛ از «رزرو / لغو رزرو» استفاده کنید.",show_alert=True); return
        occupied={int(p["seat"]) for p in active}; seat=next((n for n in range(1,cap+1) if n not in occupied),None)
        main.runtime.state.lobby.join(g["id"],uid,seat); await render(c); await c.answer(f"✅ وارد بازی شدید؛ صندلی {seat}")

    async def seat_select(c):
        g = game(c.message.chat.id)
        r = scenario(g)
        uid = int(c.from_user.id)
        try:
            target = int(str(c.data).split(":", 1)[1])
        except Exception:
            await c.answer("❌ صندلی نامعتبر است.", show_alert=True); return
        if not g or not r:
            await c.answer("❌ لابی معتبر نیست.", show_alert=True); return
        cap = len(r.get("roles") or [])
        if target < 1 or target > cap:
            await c.answer("❌ شماره صندلی نامعتبر است.", show_alert=True); return
        ps = players(g)
        current = next((p for p in ps if int(p.get("player_id") or 0) == uid and str(p.get("status") or "") not in {"removed", "finished", "kicked"}), None)
        occupied = {int(p["seat"]): int(p["player_id"]) for p in ps if p.get("seat") is not None and str(p.get("status") or "active") not in {"removed", "dead", "finished", "kicked"}}
        owner = occupied.get(target)
        if owner is not None and owner != uid:
            await c.answer("❌ این صندلی قبلاً گرفته شده است.", show_alert=True); return
        if current and current.get("seat") is not None and int(current["seat"]) == target:
            await c.answer("ℹ️ این صندلی برای شما ثبت شده است."); return
        if current is None:
            if len(occupied) >= cap:
                await c.answer("🎟 ظرفیت اصلی تکمیل است؛ از «رزرو / لغو رزرو» استفاده کنید.", show_alert=True); return
            try:
                await main._ensure_player(c.from_user)
            except Exception:
                pass
            try:
                main.runtime.state.lobby.join(g["id"], uid, target, is_substitute=False)
            except Exception:
                await c.answer("❌ ورود به صندلی انجام نشد؛ احتمالاً همزمان گرفته شده است.", show_alert=True); return
        else:
            try:
                main.runtime.state.lobby.assign_seat(g["id"], uid, target)
            except Exception:
                await c.answer("❌ تغییر صندلی انجام نشد.", show_alert=True); return
        await render(c)
        await c.answer(f"✅ صندلی {target} برای شما ثبت شد.")

    async def reserve(c):
        g=game(c.message.chat.id); r=scenario(g); uid=int(c.from_user.id)
        if not g or not r: await c.answer("❌ لابی معتبر نیست.",show_alert=True); return
        ps=players(g); cur=next((p for p in ps if int(p["player_id"])==uid),None); active=[p for p in ps if p.get("seat") is not None and str(p.get("status") or "active") not in {"removed","dead"}]; cap=len(r.get("roles") or [])
        if cur and cur.get("seat") is None and str(cur.get("status") or "")=="waiting": main.runtime.state.lobby.leave(g["id"],uid); await render(c); await c.answer("❌ رزرو شما لغو شد"); return
        if cur and cur.get("seat") is not None: await c.answer("ℹ️ شما داخل بازی هستید.",show_alert=True); return
        if len(active)<cap: await c.answer("ℹ️ تا قبل از تکمیل ظرفیت، رزرو فعال نیست.",show_alert=True); return
        main.runtime.state.lobby.join(g["id"],uid,None,is_substitute=True); await render(c); await c.answer("🎟 رزرو شما ثبت شد")

    async def manage(c):
        g=game(c.message.chat.id)
        if not g or not await allowed(c,g): await c.answer("⛔ دسترسی ندارید یا بازی فعال نیست.",show_alert=True); return
        await main.game_management.open(c)

    async def cancel(c):
        g=game(c.message.chat.id)
        if not g or not await allowed(c,g): await c.answer("⛔ دسترسی ندارید.",show_alert=True); return
        confirmer = getattr(main, "_confirm_cancel_game", None)
        if confirmer:
            await confirmer(c)
            return
        await main.game_management.cancel(c)

    async def scenario_menu(c):
        g=game(c.message.chat.id)
        if not g or not await allowed(c,g): await c.answer("⛔ دسترسی ندارید.",show_alert=True); return
        kb=InlineKeyboardMarkup(row_width=3)
        for r in repo.list_active(): kb.insert(InlineKeyboardButton(f"{str(r.get('name') or '')[:18]} ({len(r.get('roles') or [])})",callback_data=f"fl_pick:{int(r['id'])}"))
        await c.message.edit_text("📝 <b>تغییر سناریو</b>\n\nسناریوی جدید را انتخاب کنید:",parse_mode="HTML",reply_markup=kb); await c.answer()

    def special_kb(g):
        s=state(g); ch=dict(s.get("challenge_settings") or {}); nx=dict(s.get("next_settings") or {}); ui=dict(s.get("ui_settings") or {}); kb=InlineKeyboardMarkup(row_width=2)
        kb.row(InlineKeyboardButton(f"{'🟢' if ch.get('enabled',True) else '🔴'} وضعیت چالش: {'فعال' if ch.get('enabled',True) else 'غیرفعال'}",callback_data="fl_en"),InlineKeyboardButton(f"⚔ محدودیت: {'آزاد' if ch.get('mode','limited')=='free' else 'محدود'}",callback_data="fl_mode"))
        kb.row(InlineKeyboardButton(f"🤏 علامت چالش: {'روشن' if ch.get('show_player_status',True) else 'خاموش'}",callback_data="fl_mark"),InlineKeyboardButton(f"👤 نکست بازیکن: {'فعال' if nx.get('allow_players_next',True) else 'غیرفعال'}",callback_data="fl_pnext"))
        kb.row(InlineKeyboardButton(f"🎩 نکست گرداننده: {'فعال' if nx.get('allow_moderator_next',True) else 'غیرفعال'}",callback_data="fl_mnext"),InlineKeyboardButton(f"🎨 رنگ ترن: {ui.get('turn_color','🟢')}",callback_data="fl_tcolor"))
        kb.row(InlineKeyboardButton(f"⚔️ رنگ چالش: {ui.get('challenge_color','🟣')}",callback_data="fl_ccolor"),InlineKeyboardButton("⬅️ بازگشت به لابی",callback_data="fl_back"))
        return kb

    async def special(c):
        g=game(c.message.chat.id)
        if not g or not await allowed(c,g): await c.answer("⛔ فقط گرداننده یا مدیر گروه.",show_alert=True); return
        s=state(g); ch=dict(s.get("challenge_settings") or {}); nx=dict(s.get("next_settings") or {}); ui=dict(s.get("ui_settings") or {})
        t=("⭐ <b>امکانات ویژه لابی</b>\n\n" f"⚔ وضعیت چالش: <b>{'فعال' if ch.get('enabled',True) else 'غیرفعال'}</b>\n" f"⚔ محدودیت چالش: <b>{'آزاد' if ch.get('mode','limited')=='free' else 'محدود'}</b>\n" f"🤏 علامت چالش: <b>{'فعال' if ch.get('show_player_status',True) else 'غیرفعال'}</b>\n" f"👤 نکست بازیکن: <b>{'فعال' if nx.get('allow_players_next',True) else 'غیرفعال'}</b>\n" f"🎩 نکست گرداننده: <b>{'فعال' if nx.get('allow_moderator_next',True) else 'غیرفعال'}</b>\n" f"🎨 رنگ ترن: <b>{ui.get('turn_color','🟢')}</b>\n⚔️ رنگ چالش: <b>{ui.get('challenge_color','🟣')}</b>")
        await c.message.edit_text(t,parse_mode="HTML",reply_markup=special_kb(g)); await c.answer()

    async def mutate(c,key):
        g=game(c.message.chat.id)
        if not g or not await allowed(c,g): await c.answer("⛔ دسترسی ندارید.",show_alert=True); return
        s=state(g); ch=dict(s.get("challenge_settings") or {}); nx=dict(s.get("next_settings") or {}); ui=dict(s.get("ui_settings") or {})
        if key=="en": ch["enabled"]=not bool(ch.get("enabled",True)); main.challenge_active=ch["enabled"]
        elif key=="mode": ch["mode"]="free" if ch.get("mode","limited")!="free" else "limited"
        elif key=="mark": ch["show_player_status"]=not bool(ch.get("show_player_status",True))
        elif key=="pnext": nx["allow_players_next"]=not bool(nx.get("allow_players_next",True))
        elif key=="mnext": nx["allow_moderator_next"]=not bool(nx.get("allow_moderator_next",True))
        elif key in {"tcolor","ccolor"}:
            colors=["🟢","🔵","🟡","🔴","🟣","🟠","⚪"]; f="turn_color" if key=="tcolor" else "challenge_color"; cur=ui.get(f,colors[0]); ui[f]=colors[(colors.index(cur)+1)%len(colors)] if cur in colors else colors[0]
        save(g,challenge_settings=ch,next_settings=nx,ui_settings=ui); await special(c)

    async def attendance(c):
        g=game(c.message.chat.id); ps=players(g) if g else []; active=[p for p in ps if p.get("seat") is not None and str(p.get("status") or "active")!="removed"]
        if not active: await c.answer("👥 بازیکنی در بازی نیست.",show_alert=True); return
        ready=set(state(g).get("ready_players") or []); tags=[f"{'✅' if int(p['player_id']) in ready else '⬜'} {int(p['seat']):02d}. {mention(int(p['player_id']),pname(p))}" for p in sorted(active,key=lambda x:int(x.get('seat') or 999))]
        kb=InlineKeyboardMarkup(row_width=1).add(InlineKeyboardButton("🙋‍♂️ آماده‌ام",callback_data="fl_ready"),InlineKeyboardButton("⬅️ بازگشت به لابی",callback_data="fl_back"))
        await c.message.edit_text("📢 <b>تگ لیست / حاضری</b>\n\n"+"\n".join(tags)+"\n\n"+" ".join(mention(int(p['player_id']),pname(p)) for p in active),parse_mode="HTML",reply_markup=kb); await c.answer()

    async def ready(c):
        g=game(c.message.chat.id); uid=int(c.from_user.id)
        if not g or not any(int(p['player_id'])==uid and p.get('seat') is not None for p in players(g)): await c.answer("⛔ فقط بازیکنان داخل بازی می‌توانند آماده شوند.",show_alert=True); return
        s=state(g); q=set(s.get("ready_players") or []); q.add(uid); save(g,ready_players=list(q)); await attendance(c); await c.answer("✅ آماده‌ام ثبت شد")

    async def back(c): await render(c); await c.answer()

    callbacks=[
        (new,lambda c:c.data in {"fl_new","new_game"}),
        (pick,lambda c:str(c.data).startswith("fl_pick:")),
        (moderator,lambda c:str(c.data).startswith("fl_mod:")),
        (toggle,lambda c:c.data=="fl_toggle"),(seat_select,lambda c:str(c.data).startswith("fl_seat:")),(reserve,lambda c:c.data=="fl_reserve"),
        (scenario_menu,lambda c:c.data=="fl_scenario"),(manage,lambda c:c.data=="fl_manage"),
        (cancel,lambda c:c.data=="fl_cancel"),(special,lambda c:c.data=="fl_special"),
        (attendance,lambda c:c.data=="fl_attendance"),(ready,lambda c:c.data=="fl_ready"),(back,lambda c:c.data=="fl_back"),
        (lambda c:mutate(c,"en"),lambda c:c.data=="fl_en"),(lambda c:mutate(c,"mode"),lambda c:c.data=="fl_mode"),
        (lambda c:mutate(c,"mark"),lambda c:c.data=="fl_mark"),(lambda c:mutate(c,"pnext"),lambda c:c.data=="fl_pnext"),
        (lambda c:mutate(c,"mnext"),lambda c:c.data=="fl_mnext"),(lambda c:mutate(c,"tcolor"),lambda c:c.data=="fl_tcolor"),(lambda c:mutate(c,"ccolor"),lambda c:c.data=="fl_ccolor"),
    ]
    for fn,flt in callbacks: dp.register_callback_query_handler(fn,flt,state="*")
    for fn,_ in callbacks: move_front(cr,fn)

    # Canonical text command: «بازی جدید» must enter the same new() handler
    # used by the canonical fl_new/new_game callback, not the legacy main1 route.
    from types import SimpleNamespace
    async def new_game_text(message):
        callback = SimpleNamespace(message=message, from_user=message.from_user, data="fl_new", answer=message.answer, _from_text_command=True)
        await new(callback)
    dp.register_message_handler(new_game_text, lambda m: (m.text or "").strip().replace("‌", " ") == "بازی جدید", state="*")
    move_front(mr,new_game_text)

    dp.register_message_handler(start_command,commands=["start"],state="*")
    move_front(mr,start_command)
    main._render_final_lobby=render
    logging.info("FINAL_LOBBY_UI active: authoritative lobby + capacity-gated reserve + role distribution")
    return True
