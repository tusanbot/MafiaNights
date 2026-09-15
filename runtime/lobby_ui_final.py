from __future__ import annotations
import html
import logging
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from repositories.scenario_repository import ScenarioRepository
from runtime.scenario_runtime import ScenarioRuntime


def install(main):
    if getattr(main, "_final_lobby_installed", False): return False
    main._final_lobby_installed = True
    repo = ScenarioRepository(); dp = main.dp

    # The legacy lobby lives in main1.py.  It is not a second lobby anymore:
    # its callback handlers are removed here so this file is the only owner of
    # group-lobby callbacks.  Do this before registering the final handlers.
    legacy_names = {
        "start_game", "choose_scenario", "scenario_selected",
        "choose_moderator", "moderator_selected", "handle_slot",
    }
    registry = getattr(getattr(dp, "callback_query_handlers", None), "handlers", [])
    removed = 0
    kept = []
    for item in registry:
        cb = getattr(item, "callback", None)
        if getattr(cb, "__name__", "") in legacy_names:
            removed += 1
            continue
        kept.append(item)
    if removed:
        registry[:] = kept
        logging.info("FINAL_LOBBY_CUTOVER removed_legacy_handlers=%s", removed)

    def game(gid): return main.runtime.state.active_game(int(gid))
    def row(g):
        try: return repo.get_by_id(int(g.get("scenario_id"))) if g and g.get("scenario_id") else None
        except Exception: return None
    def players(g): return main.runtime.state.games.list_players(g["id"]) if g else []
    def name(p): return str(p.get("nickname") or p.get("first_name") or p.get("username") or p.get("player_id") or "👤")
    def mention(uid, fallback=None):
        try: n=main.display_name(int(uid), fallback or main.players.get(int(uid)))
        except Exception: n=fallback or main.players.get(int(uid)) or str(uid)
        return f'<a href="tg://user?id={int(uid)}"><b>{html.escape(str(n))}</b></a>'
    async def allowed(c,g):
        if int(c.from_user.id)==int((g or {}).get("moderator_id") or 0): return True
        try: return (await main.bot.get_chat_member(int(c.message.chat.id),int(c.from_user.id))).status in {"creator","administrator"}
        except Exception: return False
    def state(g): return dict((g or {}).get("state") or {})
    def save(g,**changes):
        s=state(g); s.update(changes); g["state"]=s; return main.runtime.state.games.update_game(g["id"],state=s)
    def front(fn):
        h=getattr(getattr(dp,"callback_query_handlers",None),"handlers",[])
        for i,x in enumerate(h):
            if getattr(x,"callback",None) is fn: h.insert(0,h.pop(i)); break
    def view(gid):
        g=game(gid); r=row(g); ps=players(g)
        active=[p for p in ps if p.get("seat") is not None and str(p.get("status") or "active") not in {"removed","dead"}]
        waiting=[p for p in ps if p.get("seat") is None and str(p.get("status") or "waiting")=="waiting"]
        cap=len((r or {}).get("roles") or []); active.sort(key=lambda p:int(p.get("seat") or 999))
        lines=["༄","    <b>Mafia Nights</b>","",f"📝 <b>سناریو:</b> {html.escape(str((r or {}).get('name') or '---'))}",f"🎩 <b>گرداننده:</b> {mention(g.get('moderator_id'))}",f"👥 <b>بازیکنان:</b> {len(active)}/{cap}","","◤◢◣◥◤◢◣◥◤◢◣◥","        <b>لیست بازیکنان</b>","◤◢◣◥◤◢◣◥◤◢◣◥",""]
        lines += [f"{int(p['seat']):02d} {mention(int(p['player_id']),name(p))}" for p in active] or ["— هنوز بازیکنی وارد بازی نشده است."]
        if waiting: lines += ["","🎟 <b>لیست رزرو</b>"]+[f"{i}. {mention(int(p['player_id']),name(p))}" for i,p in enumerate(waiting,1)]
        lines += ["","◤◢◣◥◤◢◣◥◤◢◣◥","༄"]
        kb=InlineKeyboardMarkup(row_width=2)
        kb.row(InlineKeyboardButton("🔄 ورود / خروج",callback_data="fl_toggle"),InlineKeyboardButton("🎟 رزرو / لغو رزرو",callback_data="fl_reserve"))
        kb.row(InlineKeyboardButton("📝 تغییر سناریو",callback_data="fl_scenario"),InlineKeyboardButton("⚙️ مدیریت بازی",callback_data="fl_manage"))
        kb.row(InlineKeyboardButton("⭐ امکانات ویژه",callback_data="fl_special"),InlineKeyboardButton("🚫 لغو بازی",callback_data="fl_cancel"))
        kb.add(InlineKeyboardButton("📢 تگ لیست / حاضری",callback_data="fl_attendance"))
        return "\n".join(lines),kb
    async def render(c):
        t,k=view(int(c.message.chat.id)); await c.message.edit_text(t,parse_mode="HTML",reply_markup=k); main.lobby_message_id=c.message.message_id
    async def new(c):
        gid=int(c.message.chat.id)
        if getattr(main,"game_running",False) or getattr(main,"round_active",False): await c.answer("⚠️ بازی در حال اجراست.",show_alert=True); return
        main.group_chat_id=gid; main.lobby_active=True; main.game_running=False; main.round_active=False
        try: main.runtime.lobby.ensure(gid)
        except Exception: logging.exception("lobby ensure failed")
        kb=InlineKeyboardMarkup(row_width=3); rows=repo.list_active(); popular={"پدرخوانده-جک","پدرخوانده-شرلوک","پدرخوانده-نوسترا","کلاسیک 12","کلاسیک 13","قمار باز","زودیاک","کاپو"}
        rows.sort(key=lambda x:(0 if x.get("name") in popular else 1,int(x.get("sort_order") or 0),int(x.get("id") or 0)))
        for r in rows: kb.insert(InlineKeyboardButton(f"{str(r.get('name') or '')[:18]} ({len(r.get('roles') or [])})",callback_data=f"fl_pick:{int(r['id'])}"))
        await c.message.edit_text("📝 <b>انتخاب سناریو</b>\n\nسناریوی بازی را انتخاب کنید:",parse_mode="HTML",reply_markup=kb); await c.answer()
    async def pick(c):
        try: sid=int(str(c.data).split(":")[1]); r=repo.get_by_id(sid)
        except Exception: r=None
        if not r or not r.get("is_active",True): await c.answer("❌ سناریو نامعتبر است.",show_alert=True); return
        gid=int(c.message.chat.id); g=game(gid)
        if not g: await c.answer("❌ بازی فعال پیدا نشد.",show_alert=True); return
        try: ScenarioRuntime(main).apply_to_game(str(g["id"]),sid); main.selected_scenario=str(r["name"]); main.MAX_SEATS=len(r.get("roles") or [])
        except Exception: logging.exception("scenario save failed"); await c.answer("❌ ذخیره سناریو انجام نشد.",show_alert=True); return
        kb=InlineKeyboardMarkup(row_width=2)
        for a in await main.bot.get_chat_administrators(gid): kb.insert(InlineKeyboardButton(a.user.full_name[:24],callback_data=f"fl_mod:{int(a.user.id)}"))
        await c.message.edit_text(f"📝 <b>{html.escape(str(r['name']))}</b>\n\n🎩 <b>انتخاب گرداننده</b>",parse_mode="HTML",reply_markup=kb); await c.answer("✅ سناریو انتخاب شد")
    async def moderator(c):
        gid=int(c.message.chat.id); uid=int(str(c.data).split(":")[1]); admins={int(a.user.id) for a in await main.bot.get_chat_administrators(gid)}
        if uid not in admins: await c.answer("❌ گرداننده باید مدیر گروه باشد.",show_alert=True); return
        main.runtime.lobby.set_moderator(gid,uid); main.moderator_id=uid; main.group_chat_id=gid; main.lobby_active=True; main.game_running=False; main.round_active=False
        await render(c); await c.answer("✅ لابی اصلی ایجاد شد")
    async def toggle(c):
        gid=int(c.message.chat.id); uid=int(c.from_user.id); g=game(gid); r=row(g)
        if not g or not r: await c.answer("❌ لابی معتبر نیست.",show_alert=True); return
        ps=players(g); cur=next((p for p in ps if int(p["player_id"])==uid),None); active=[p for p in ps if p.get("seat") is not None and str(p.get("status") or "active") not in {"removed","dead"}]; cap=len(r.get("roles") or [])
        if cur and cur.get("seat") is not None:
            seat=int(cur["seat"]); main.runtime.state.lobby.leave(g["id"],uid)
            try: main.runtime.lobby.promote_waiting(gid,seat)
            except Exception: pass
            await render(c); await c.answer("🚪 از بازی خارج شدید"); return
        if cur and cur.get("seat") is None and str(cur.get("status") or "")=="waiting": main.runtime.state.lobby.leave(g["id"],uid); await render(c); await c.answer("🎟 رزرو شما لغو شد"); return
        if len(active)>=cap: await c.answer("🎟 ظرفیت اصلی تکمیل است؛ از «رزرو / لغو رزرو» استفاده کنید.",show_alert=True); return
        occupied={int(p["seat"]) for p in active}; seat=next((n for n in range(1,cap+1) if n not in occupied),None)
        main.runtime.state.lobby.join(g["id"],uid,seat); await render(c); await c.answer(f"✅ وارد بازی شدید؛ صندلی {seat}")
    async def reserve(c):
        gid=int(c.message.chat.id); uid=int(c.from_user.id); g=game(gid); r=row(g)
        if not g or not r: await c.answer("❌ لابی معتبر نیست.",show_alert=True); return
        ps=players(g); cur=next((p for p in ps if int(p["player_id"])==uid),None); active=[p for p in ps if p.get("seat") is not None and str(p.get("status") or "active") not in {"removed","dead"}]; cap=len(r.get("roles") or [])
        if cur and cur.get("seat") is None and str(cur.get("status") or "")=="waiting": main.runtime.state.lobby.leave(g["id"],uid); await render(c); await c.answer("❌ رزرو شما لغو شد"); return
        if cur and cur.get("seat") is not None: await c.answer("ℹ️ شما داخل بازی هستید.",show_alert=True); return
        if len(active)<cap: await c.answer("ℹ️ تا قبل از تکمیل ظرفیت، رزرو فعال نیست.",show_alert=True); return
        main.runtime.state.lobby.join(g["id"],uid,None,is_substitute=True); await render(c); await c.answer("🎟 رزرو شما ثبت شد")
    async def manage(c):
        from runtime.game_management import GameManagement
        g=game(int(c.message.chat.id))
        if not g or not await allowed(c,g): await c.answer("⛔ دسترسی ندارید یا بازی فعال نیست.",show_alert=True); return
        await GameManagement(main).open(c)
    async def cancel(c):
        from runtime.game_management import GameManagement
        g=game(int(c.message.chat.id))
        if not g or not await allowed(c,g): await c.answer("⛔ دسترسی ندارید.",show_alert=True); return
        await GameManagement(main).cancel(c)
    async def scenario_menu(c):
        g=game(int(c.message.chat.id))
        if not g or not await allowed(c,g): await c.answer("⛔ دسترسی ندارید.",show_alert=True); return
        kb=InlineKeyboardMarkup(row_width=3)
        for r in repo.list_active(): kb.insert(InlineKeyboardButton(f"{str(r.get('name') or '')[:18]} ({len(r.get('roles') or [])})",callback_data=f"fl_pick:{int(r['id'])}"))
        await c.message.edit_text("📝 <b>تغییر سناریو</b>\n\nسناریوی جدید را انتخاب کنید:",parse_mode="HTML",reply_markup=kb); await c.answer()
    def sk(g):
        s=state(g); ch=dict(s.get("challenge_settings") or {}); nx=dict(s.get("next_settings") or {}); ui=dict(s.get("ui_settings") or {}); en=bool(ch.get("enabled",True)); mode=str(ch.get("mode") or "limited"); mark=bool(ch.get("show_player_status",True)); pn=bool(nx.get("allow_players_next",True)); mn=bool(nx.get("allow_moderator_next",True)); kb=InlineKeyboardMarkup(row_width=2)
        kb.row(InlineKeyboardButton(f"{'🟢' if en else '🔴'} وضعیت چالش: {'فعال' if en else 'غیرفعال'}",callback_data="fl_en"),InlineKeyboardButton(f"⚔ محدودیت: {'آزاد' if mode=='free' else 'محدود'}",callback_data="fl_mode")); kb.row(InlineKeyboardButton(f"🤏 علامت چالش: {'روشن' if mark else 'خاموش'}",callback_data="fl_mark"),InlineKeyboardButton(f"👤 نکست بازیکن: {'فعال' if pn else 'غیرفعال'}",callback_data="fl_pnext")); kb.row(InlineKeyboardButton(f"🎩 نکست گرداننده: {'فعال' if mn else 'غیرفعال'}",callback_data="fl_mnext"),InlineKeyboardButton(f"🎨 رنگ ترن: {ui.get('turn_color','🟢')}",callback_data="fl_tcolor")); kb.row(InlineKeyboardButton(f"⚔️ رنگ چالش: {ui.get('challenge_color','🟣')}",callback_data="fl_ccolor"),InlineKeyboardButton("⬅️ بازگشت به لابی",callback_data="fl_back")); return kb
    async def special(c):
        g=game(int(c.message.chat.id))
        if not g or not await allowed(c,g): await c.answer("⛔ فقط گرداننده یا مدیر گروه.",show_alert=True); return
        s=state(g); ch=dict(s.get("challenge_settings") or {}); nx=dict(s.get("next_settings") or {}); ui=dict(s.get("ui_settings") or {}); t=("⭐ <b>امکانات ویژه لابی</b>\n\n" f"⚔ وضعیت چالش: <b>{'فعال' if ch.get('enabled',True) else 'غیرفعال'}</b>\n" f"⚔ محدودیت چالش: <b>{'آزاد' if ch.get('mode','limited')=='free' else 'محدود'}</b>\n" f"🤏 علامت چالش: <b>{'فعال' if ch.get('show_player_status',True) else 'غیرفعال'}</b>\n" f"👤 نکست بازیکن: <b>{'فعال' if nx.get('allow_players_next',True) else 'غیرفعال'}</b>\n" f"🎩 نکست گرداننده: <b>{'فعال' if nx.get('allow_moderator_next',True) else 'غیرفعال'}</b>\n" f"🎨 رنگ ترن: <b>{ui.get('turn_color','🟢')}</b>\n⚔️ رنگ چالش: <b>{ui.get('challenge_color','🟣')}</b>"); await c.message.edit_text(t,parse_mode="HTML",reply_markup=sk(g)); await c.answer()
    async def mutate(c,key):
        g=game(int(c.message.chat.id))
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
        g=game(int(c.message.chat.id)); ps=players(g) if g else []; active=[p for p in ps if p.get("seat") is not None and str(p.get("status") or "active") not in {"removed"}]
        if not active: await c.answer("👥 بازیکنی در بازی نیست.",show_alert=True); return
        ready=set(state(g).get("ready_players") or []); tags=[f"{'✅' if int(p['player_id']) in ready else '⬜'} {int(p['seat']):02d}. {mention(int(p['player_id']),name(p))}" for p in sorted(active,key=lambda x:int(x.get('seat') or 999))]; kb=InlineKeyboardMarkup(row_width=1).add(InlineKeyboardButton("🙋‍♂️ آماده‌ام",callback_data="fl_ready"),InlineKeyboardButton("⬅️ بازگشت به لابی",callback_data="fl_back")); await c.message.edit_text("📢 <b>تگ لیست / حاضری</b>\n\n"+"\n".join(tags)+"\n\n"+" ".join(mention(int(p['player_id']),name(p)) for p in active),parse_mode="HTML",reply_markup=kb); await c.answer()
    async def ready(c):
        g=game(int(c.message.chat.id)); uid=int(c.from_user.id)
        if not g or not any(int(p['player_id'])==uid and p.get('seat') is not None for p in players(g)): await c.answer("⛔ فقط بازیکنان داخل بازی می‌توانند آماده شوند.",show_alert=True); return
        s=state(g); q=set(s.get('ready_players') or []); q.add(uid); save(g,ready_players=list(q)); await attendance(c); await c.answer("✅ آماده‌ام ثبت شد")
    async def back(c): await render(c); await c.answer()
    callbacks=[(new,lambda c:c.data in {"fl_new","new_game"}),(pick,lambda c:str(c.data).startswith("fl_pick:")),(moderator,lambda c:str(c.data).startswith("fl_mod:")),(toggle,lambda c:c.data=="fl_toggle"),(reserve,lambda c:c.data=="fl_reserve"),(scenario_menu,lambda c:c.data=="fl_scenario"),(manage,lambda c:c.data=="fl_manage"),(cancel,lambda c:c.data=="fl_cancel"),(special,lambda c:c.data=="fl_special"),(attendance,lambda c:c.data=="fl_attendance"),(ready,lambda c:c.data=="fl_ready"),(back,lambda c:c.data=="fl_back"),(lambda c:mutate(c,"en"),lambda c:c.data=="fl_en"),(lambda c:mutate(c,"mode"),lambda c:c.data=="fl_mode"),(lambda c:mutate(c,"mark"),lambda c:c.data=="fl_mark"),(lambda c:mutate(c,"pnext"),lambda c:c.data=="fl_pnext"),(lambda c:mutate(c,"mnext"),lambda c:c.data=="fl_mnext"),(lambda c:mutate(c,"tcolor"),lambda c:c.data=="fl_tcolor"),(lambda c:mutate(c,"ccolor"),lambda c:c.data=="fl_ccolor")]
    for fn,flt in callbacks: dp.register_callback_query_handler(fn,flt,state="*"); front(fn)
    main._render_final_lobby=render
    logging.info("FINAL_LOBBY_UI active: single authoritative lobby runtime")
    return True
