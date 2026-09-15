from __future__ import annotations

import html
import logging
from aiogram.dispatcher.handler import CancelHandler
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from repositories.scenario_repository import ScenarioRepository
from runtime.scenario_runtime import ScenarioRuntime


def _registry(main):
    return getattr(getattr(main.dp, "callback_query_handlers", None), "handlers", [])


def _remove_legacy_lobby_handlers(main):
    reg = _registry(main)
    legacy_names = {"new", "scenario", "moderator", "change_s"}
    before = len(reg)
    reg[:] = [item for item in reg if getattr(getattr(item, "callback", None), "__name__", "") not in legacy_names]
    return before - len(reg)


def install(main):
    if getattr(main, "_lobby_ui_v9_installed", False):
        return False
    main._lobby_ui_v9_installed = True
    removed = _remove_legacy_lobby_handlers(main)
    repo = ScenarioRepository(); dp = main.dp; reg = _registry(main)

    def rows(key):
        data=[(r,str(r.get("name") or "")) for r in repo.list_active()]
        if key=="father": data=[(r,n) for r,n in data if n.startswith("پدرخوانده-")]
        elif key=="classic": data=[(r,n) for r,n in data if n.startswith("کلاسیک ")]
        elif key=="don": data=[(r,n) for r,n in data if n=="کاپو" or "دن مافیا" in [str(x) for x in (r.get("roles") or [])]]
        elif key=="gambler": data=[(r,n) for r,n in data if n in {"قمار باز","قمارباز"}]
        elif key=="zodiac": data=[(r,n) for r,n in data if n=="زودیاک"]
        elif key=="other":
            popular={"پدرخوانده-جک","پدرخوانده-شرلوک","پدرخوانده-نوسترا","کلاسیک 12","کلاسیک 13","قمار باز","قمارباز","زودیاک","کاپو"}
            data=[(r,n) for r,n in data if n not in popular]
        return data

    def catalog():
        kb=InlineKeyboardMarkup(row_width=3)
        for label,key in (("👑 پدرخوانده","father"),("🎭 کلاسیک","classic"),("🎩 دن","don"),("🎲 قمارباز","gambler"),("☢️ زودیاک","zodiac")):
            kb.insert(InlineKeyboardButton(label,callback_data=f"lv9_cat:{key}"))
        kb.add(InlineKeyboardButton("📚 سایر سناریوها",callback_data="lv9_cat:other")); return kb

    def scenario_kb(key):
        kb=InlineKeyboardMarkup(row_width=3)
        for row,n in rows(key):
            sid=int(row["id"]); label=n.replace("پدرخوانده-","") if key=="father" else (n.replace("کلاسیک ","")+" نفره" if key=="classic" else ("کاپو" if key=="don" and n=="کاپو" else n))
            kb.insert(InlineKeyboardButton(f"{label} ({len(row.get('roles') or [])})",callback_data=f"lv9_s:{key}:{sid}"))
        kb.row(InlineKeyboardButton("⬅️ سناریوهای محبوب",callback_data="lv9_catalog")); return kb

    async def show_catalog(c):
        await c.message.edit_text("📝 <b>انتخاب سناریو</b>\n\n⭐ دسته‌بندی سناریوها:",parse_mode="HTML",reply_markup=catalog()); await c.answer(); raise CancelHandler()

    async def new(c):
        if getattr(main,"game_running",False) or getattr(main,"round_active",False): await c.answer("⚠️ بازی در حال اجراست.",show_alert=True); raise CancelHandler()
        try:
            if getattr(main,"runtime",None): main.runtime.lobby.ensure(int(c.message.chat.id))
        except Exception: pass
        main.group_chat_id=int(c.message.chat.id); main.lobby_active=True; main.game_running=False; main.round_active=False; main._lv6_setup=True; main._lv6_change_scenario=False
        await show_catalog(c)

    async def category(c):
        key=str(c.data).split(":",1)[1]; title={"father":"👑 <b>پدرخوانده</b>","classic":"🎭 <b>کلاسیک</b>","don":"🎩 <b>دن</b>","gambler":"🎲 <b>قمارباز</b>","zodiac":"☢️ <b>زودیاک</b>","other":"📚 <b>سایر سناریوها</b>"}.get(key,"📝 <b>سناریوها</b>")
        await c.message.edit_text(f"{title}\n\nنسخه موردنظر را انتخاب کنید:",parse_mode="HTML",reply_markup=scenario_kb(key)); await c.answer(); raise CancelHandler()

    def resolve_selection(data):
        parts=str(data).split(":")
        if len(parts)==3 and parts[0]=="lv9_s": return int(parts[2])
        if len(parts)==2 and parts[0]=="lv6_s":
            index=int(parts[1]); names=list((getattr(main,"scenarios",{}) or {}).keys())
            if index<0 or index>=len(names): raise ValueError("scenario index out of range")
            row=repo.get_by_name(names[index])
            if not row: raise ValueError("scenario not found")
            return int(row["id"])
        raise ValueError("invalid scenario callback")

    def mention(uid, fallback=None):
        if not uid: return "---"
        try: name=main.display_name(int(uid),fallback or main.players.get(int(uid)))
        except Exception: name=fallback or main.players.get(int(uid)) or str(uid)
        return f'<a href="tg://user?id={int(uid)}"><b>{html.escape(str(name))}</b></a>'

    def lobby_view(group_id):
        snap=main.runtime.lobby_snapshot(group_id); game=snap.get("game") or {}; sid=game.get("scenario_id")
        row=repo.get_by_id(int(sid)) if sid else None
        name=str((row or {}).get("name") or getattr(main,"selected_scenario",None) or "---")
        capacity=len((row or {}).get("roles") or [])
        players=[r for r in snap.get("players",[]) if r.get("seat") is not None and str(r.get("status") or "active") not in {"removed","dead"}]
        waiting=[r for r in snap.get("players",[]) if r.get("seat") is None and str(r.get("status") or "waiting")=="waiting"]
        lines=["༄","    <b>Mafia Nights</b>","",f"📝 <b>سناریو:</b> {html.escape(name)}",f"🎩 <b>گرداننده:</b> {mention(game.get('moderator_id'))}",f"👥 <b>بازیکنان:</b> {len(players)}/{capacity}","","◤◢◣◥◤◢◣◥◤◢◣◥","        <b>لیست بازیکنان</b>","◤◢◣◥◤◢◣◥◤◢◣◥",""]
        if players:
            for p in sorted(players,key=lambda x:int(x.get("seat") or 999)):
                lines.append(f"{int(p['seat']):02d} {mention(int(p['player_id']),p.get('nickname') or p.get('first_name') or p.get('username'))}")
        else: lines.append("— هنوز بازیکنی وارد نشده است.")
        if waiting:
            lines += ["","🎟 <b>لیست رزرو</b>"]
            for i,p in enumerate(waiting,1): lines.append(f"{i}. {mention(int(p['player_id']),p.get('nickname') or p.get('first_name'))}")
        lines += ["","◤◢◣◥◤◢◣◥◤◢◣◥","༄"]
        kb=InlineKeyboardMarkup(row_width=3); occupied={int(p["seat"]):p for p in players}
        for seat in range(1,capacity+1):
            p=occupied.get(seat); label=f"{seat:02d} {str(p.get('nickname') or p.get('first_name') or p.get('username') or '👤')[:12]}" if p else f"{seat:02d} ⬜"
            kb.insert(InlineKeyboardButton(label,callback_data=f"lv6_seat:{seat}"))
        kb.row(InlineKeyboardButton("✅ ورود",callback_data="lv6_toggle"),InlineKeyboardButton("❌ خروج",callback_data="lv6_toggle"))
        if len(players)>=capacity>0:
            kb.add(InlineKeyboardButton("🎟 رزرو / لغو رزرو",callback_data="lv6_reserve")); kb.add(InlineKeyboardButton("🎭 پخش نقش",callback_data="distribute_roles"))
        kb.add(InlineKeyboardButton("⚙️ مدیریت بازی",callback_data="lv6_manage"))
        return "\n".join(lines),kb

    async def choose(c):
        try: sid=resolve_selection(c.data); row=repo.get_by_id(sid)
        except Exception: await c.answer("❌ سناریو نامعتبر است.",show_alert=True); raise CancelHandler()
        if not row or not row.get("is_active",True): await c.answer("❌ سناریو معتبر نیست.",show_alert=True); raise CancelHandler()
        selected=str(row["name"]); gid=int(c.message.chat.id)
        try:
            game=main.runtime.state.active_game(gid)
            if not game: raise ValueError("بازی فعال پیدا نشد")
            ScenarioRuntime(main).apply_to_game(str(game["id"]),sid)
            if getattr(main,"_lv6_change_scenario",False):
                for p in list(main.runtime.lobby_snapshot(gid).get("players",[])): main.runtime.lobby.leave(gid,int(p["player_id"]))
        except Exception:
            logging.exception("scenario selection persistence failed sid=%s group=%s",sid,gid); await c.answer("❌ ذخیره سناریو انجام نشد.",show_alert=True); raise CancelHandler()
        main.selected_scenario=selected; main.MAX_SEATS=len(row.get("roles") or [])
        if getattr(main,"_lv6_change_scenario",False) and getattr(main,"moderator_id",None):
            main._lv6_change_scenario=False; await c.message.edit_text(f"✅ سناریو «{html.escape(selected)}» تغییر کرد."); await c.answer(); raise CancelHandler()
        admins=await main.bot.get_chat_administrators(gid); kb=InlineKeyboardMarkup(row_width=3)
        for a in admins: kb.insert(InlineKeyboardButton(a.user.full_name[:24],callback_data=f"lv9_m:{int(a.user.id)}"))
        await c.message.edit_text(f"📝 <b>{html.escape(selected)}</b>\n\n🎩 <b>انتخاب گرداننده</b>",parse_mode="HTML",reply_markup=kb); await c.answer("✅ سناریو انتخاب شد"); raise CancelHandler()

    async def moderator(c):
        gid=int(c.message.chat.id); uid=int(str(c.data).split(":")[1]); admins={int(a.user.id) for a in await main.bot.get_chat_administrators(gid)}
        if uid not in admins: await c.answer("❌ گرداننده باید مدیر گروه باشد.",show_alert=True); raise CancelHandler()
        try:
            main.runtime.lobby.set_moderator(gid,uid); main.moderator_id=uid; main.group_chat_id=gid
            main.lobby_active=True; main.game_running=False; main.round_active=False; main._lv6_setup=False; main._lv6_change_scenario=False
            text,kb=lobby_view(gid)
            await c.message.edit_text(text,parse_mode="HTML",reply_markup=kb)
            main.lobby_message_id=c.message.message_id
        except Exception:
            logging.exception("failed to render lobby after moderator selection group=%s moderator=%s",gid,uid)
            await c.message.edit_text("❌ لابی ساخته شد اما نمایش لابی با خطا مواجه شد. لطفاً دوباره بازی جدید را بزنید.")
            raise CancelHandler()
        await c.answer("✅ لابی اصلی ایجاد شد"); raise CancelHandler()

    async def change(c):
        admins={int(a.user.id) for a in await main.bot.get_chat_administrators(int(c.message.chat.id))}
        if int(c.from_user.id) not in admins: await c.answer("⛔ فقط مدیران.",show_alert=True); raise CancelHandler()
        main._lv6_change_scenario=True; await show_catalog(c)

    for fn,flt in ((new,lambda c:c.data=="lv6_new"),(show_catalog,lambda c:c.data=="lv9_catalog"),(category,lambda c:str(c.data).startswith("lv9_cat:")),(choose,lambda c:str(c.data).startswith("lv9_s:") or str(c.data).startswith("lv6_s:")),(moderator,lambda c:str(c.data).startswith("lv9_m:")),(change,lambda c:c.data=="lv6_change_s")):
        dp.register_callback_query_handler(fn,flt,state="*"); reg=_registry(main)
        for i,item in enumerate(reg):
            if getattr(item,"callback",None) is fn: reg.insert(0,reg.pop(i)); break
    logging.info("LOBBY_UI_CANONICAL active: v6 lobby base + numeric scenario authority; removed_legacy=%s",removed)
    return True
