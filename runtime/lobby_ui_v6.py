from __future__ import annotations
import html
import logging
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def install(main):
    dp, bot = main.dp, main.bot
    original_menu = main.main_menu_keyboard

    def front(fn):
        handlers = getattr(dp.callback_query_handlers, "handlers", [])
        for i, h in enumerate(handlers):
            if getattr(h, "callback", None) is fn:
                handlers.insert(0, handlers.pop(i)); break

    def rows():
        return [{"player_id": int(uid), "is_substitute": uid in main.waiting_list,
                 "seat": next((s for s,p in main.player_slots.items() if p == uid), None),
                 "first_name": main.players.get(uid)} for uid in main.players]

    def menu():
        try: src = original_menu()
        except Exception: src = InlineKeyboardMarkup()
        out = InlineKeyboardMarkup(row_width=2); found = False
        for row in getattr(src, "inline_keyboard", []):
            nr=[]
            for b in row:
                t=str(getattr(b,"text",""))
                if "لیست جدید" in t: continue
                if "بازی جدید" in t:
                    nr.append(InlineKeyboardButton("🎮 بازی جدید", callback_data="lv6_new")); found=True
                else: nr.append(b)
            if nr: out.row(*nr)
        if not found: out.add(InlineKeyboardButton("🎮 بازی جدید", callback_data="lv6_new"))
        return out

    def mention(uid):
        try: n=main.display_name(uid, main.players.get(uid)) or main.players.get(uid) or str(uid)
        except Exception: n=main.players.get(uid) or str(uid)
        return f'<a href="tg://user?id={uid}"><b>{html.escape(str(n))}</b></a>'

    async def edit(m,text,kb=None):
        try: await m.edit_text(text,reply_markup=kb,parse_mode="HTML")
        except Exception as e: logging.warning("lobby edit failed: %s",e)

    def scenario_kb():
        kb=InlineKeyboardMarkup(row_width=1)
        for i,(s,cfg) in enumerate(main.scenarios.items()):
            cfg=cfg or {}; kb.add(InlineKeyboardButton(f"📝 {s} ({cfg.get('min_players',1)}-{len(cfg.get('roles') or [])})",callback_data=f"lv6_s:{i}"))
        kb.add(InlineKeyboardButton("⬅️ بازگشت",callback_data="lv6_home")); return kb

    async def moderator_kb():
        kb=InlineKeyboardMarkup(row_width=1)
        for a in await bot.get_chat_administrators(main.group_chat_id):
            kb.add(InlineKeyboardButton(a.user.full_name,callback_data=f"lv6_m:{a.user.id}"))
        kb.add(InlineKeyboardButton("⬅️ بازگشت به سناریو",callback_data="lv6_back_s")); return kb

    def lobby_text():
        cfg=main.scenarios.get(main.selected_scenario) or {}; max_seats=len(cfg.get("roles") or [])
        active=[u for u in main.players if u not in main.waiting_list]
        waiting=[u for u in main.waiting_list if u in main.players]
        text=["🎮 <b>لابی Mafia Nights</b>","",f"📝 سناریو: <b>{html.escape(str(main.selected_scenario or '---'))}</b>",f"🎩 گرداننده: {mention(main.moderator_id) if main.moderator_id else '---'}",f"👥 بازیکنان: <b>{len(active)}/{max_seats}</b>","","📋 <b>بازیکنان داخل بازی</b>"]
        if active:
            for u in sorted(active,key=lambda x:(next((s for s,p in main.player_slots.items() if p==x),999))):
                seat=next((s for s,p in main.player_slots.items() if p==u),None); text.append(f"{seat:02d}. {mention(u)}" if seat else f"▫️ {mention(u)} — بدون صندلی")
        else: text.append("— هنوز بازیکنی وارد نشده است.")
        if waiting:
            text += ["","🎟 <b>لیست رزرو</b>"]+[f"{i}. {mention(u)}" for i,u in enumerate(waiting,1)]
        return "\n".join(text)

    def lobby_kb():
        cfg=main.scenarios.get(main.selected_scenario) or {}; cap=len(cfg.get("roles") or [])
        active=[u for u in main.players if u not in main.waiting_list]
        full=cap>0 and len(active)>=cap and all(any(p==u and s is not None for s,p in main.player_slots.items()) for u in active)
        kb=InlineKeyboardMarkup(row_width=2)
        kb.add(InlineKeyboardButton("🎮 ورود / خروج از بازی",callback_data="lv6_toggle"))
        kb.add(InlineKeyboardButton("💺 انتخاب صندلی",callback_data="lv6_seat_menu"))
        if full: kb.add(InlineKeyboardButton("🎟 رزرو / لغو رزرو",callback_data="lv6_reserve")); kb.add(InlineKeyboardButton("🎭 پخش نقش",callback_data="distribute_roles"))
        kb.add(InlineKeyboardButton("⚙️ مدیریت بازی",callback_data="lv6_manage")); return kb

    async def render(m): await edit(m,lobby_text(),lobby_kb()); main.lobby_message_id=m.message_id

    async def new(c):
        main.group_chat_id=c.message.chat.id
        if main.game_running or main.round_active: await c.answer("⚠️ بازی در حال اجراست.",show_alert=True); return
        main.lobby_active=True; main.selected_scenario=None; main.moderator_id=None; main.MAX_SEATS=0; main.players.clear(); main.player_slots.clear(); main.waiting_list.clear(); main._lv6_setup=True
        await edit(c.message,"📝 <b>انتخاب سناریو</b>\n\nابتدا سناریوی بازی را انتخاب کنید.",scenario_kb()); await c.answer()

    async def scenario(c):
        try: i=int(c.data.split(":")[1]); main.selected_scenario=list(main.scenarios)[i]; main.MAX_SEATS=len((main.scenarios[main.selected_scenario] or {}).get("roles") or [])
        except Exception: await c.answer("سناریو نامعتبر است.",show_alert=True); return
        await edit(c.message,f"📝 سناریو: <b>{html.escape(main.selected_scenario)}</b>\n\n🎩 <b>انتخاب گرداننده</b>",await moderator_kb()); await c.answer("✅ سناریو انتخاب شد")

    async def moderator(c):
        uid=int(c.data.split(":")[1]); admins={a.user.id for a in await bot.get_chat_administrators(main.group_chat_id)}
        if uid not in admins: await c.answer("گرداننده باید مدیر گروه باشد.",show_alert=True); return
        main.moderator_id=uid; main._lv6_setup=False; main.lobby_active=True; main.game_running=False; main.round_active=False
        await render(c.message); await c.answer("✅ لابی ایجاد شد")

    async def home(c): main._lv6_setup=False; main.lobby_active=False; await edit(c.message,"🎮 <b>Mafia Nights</b>\n\nیک گزینه را انتخاب کنید.",menu()); await c.answer()
    async def back_s(c): main._lv6_setup=True; await edit(c.message,"📝 <b>انتخاب سناریو</b>",scenario_kb()); await c.answer()
    async def toggle(c):
        u=c.from_user.id; active=[x for x in main.players if x not in main.waiting_list]
        if u in main.players and u not in main.waiting_list:
            seat=next((s for s,p in main.player_slots.items() if p==u),None); main.players.pop(u,None); main.player_slots.pop(seat,None) if seat is not None else None
            if main.waiting_list: promote=main.waiting_list.pop(0); main.players[promote]=main.players.get(promote,str(promote)); main.player_slots[seat]=promote if seat is not None else promote
            await render(c.message); await c.answer("🚪 از بازی خارج شدید"); return
        if u in main.waiting_list: await c.answer("🎟 شما در رزرو هستید؛ برای لغو رزرو از دکمه رزرو استفاده کنید.",show_alert=True); return
        if len(active)>=int(main.MAX_SEATS or 0): await c.answer("🎟 ظرفیت اصلی پر است؛ رزرو را انتخاب کنید.",show_alert=True); return
        main.players[u]=c.from_user.full_name; await render(c.message); await c.answer("✅ وارد بازی شدید")

    async def seat_menu(c):
        u=c.from_user.id
        if u not in main.players or u in main.waiting_list: await c.answer("ابتدا وارد بازی شوید.",show_alert=True); return
        kb=InlineKeyboardMarkup(row_width=3); occupied={s:p for s,p in main.player_slots.items()}
        for s in range(1,int(main.MAX_SEATS or 0)+1): kb.insert(InlineKeyboardButton(f"{s:02d} "+("🔒" if s in occupied and occupied[s]!=u else ("✅" if occupied.get(s)==u else "⬜")),callback_data=f"lv6_seat:{s}"))
        kb.add(InlineKeyboardButton("⬅️ بازگشت",callback_data="lv6_back_lobby")); await edit(c.message,"💺 <b>انتخاب صندلی</b>",kb); await c.answer()

    async def seat(c):
        u=c.from_user.id; s=int(c.data.split(":")[1]); occupied=main.player_slots.get(s)
        if u not in main.players or u in main.waiting_list: await c.answer("ابتدا وارد بازی شوید.",show_alert=True); return
        if occupied is not None and occupied!=u: await c.answer("این صندلی قبلاً گرفته شده است.",show_alert=True); return
        old=next((x for x,p in main.player_slots.items() if p==u),None)
        if old is not None: main.player_slots.pop(old,None)
        main.player_slots[s]=u; await render(c.message); await c.answer(f"✅ صندلی {s} انتخاب شد")

    async def reserve(c):
        u=c.from_user.id; active=[x for x in main.players if x not in main.waiting_list]; cap=int(main.MAX_SEATS or 0)
        full=cap>0 and len(active)>=cap and all(any(p==x and s is not None for s,p in main.player_slots.items()) for x in active)
        if not full: await c.answer("رزرو پس از تکمیل بازیکنان و صندلی‌ها فعال است.",show_alert=True); return
        if u in main.waiting_list: main.waiting_list.remove(u); await render(c.message); await c.answer("❌ رزرو لغو شد"); return
        if u in main.players: await c.answer("شما در لیست اصلی هستید.",show_alert=True); return
        main.waiting_list.append(u); main.players[u]=c.from_user.full_name; await render(c.message); await c.answer("🎟 به لیست رزرو اضافه شدید")

    async def manage(c):
        admins={a.user.id for a in await bot.get_chat_administrators(main.group_chat_id)}
        if c.from_user.id not in admins: await c.answer("⛔ فقط مدیران.",show_alert=True); return
        kb=InlineKeyboardMarkup(row_width=1)
        for t,d in [("🚫 لغو بازی","lv6_cancel"),("📝 تغییر سناریو","lv6_change_s"),("🎩 تغییر گرداننده","lv6_change_m"),("⚔️ چالش","lv6_challenge"),("🗑 حذف بازیکن","lv6_remove"),("📢 حاضری","lv6_ready"),("⬅️ بازگشت به لابی","lv6_back_lobby")]: kb.add(InlineKeyboardButton(t,callback_data=d))
        await edit(c.message,"⚙️ <b>مدیریت بازی</b>",kb); await c.answer()

    async def cancel(c):
        admins={a.user.id for a in await bot.get_chat_administrators(main.group_chat_id)}
        if c.from_user.id!=main.moderator_id and c.from_user.id not in admins: await c.answer("⛔ دسترسی ندارید.",show_alert=True); return
        main.players.clear(); main.player_slots.clear(); main.waiting_list.clear(); main.lobby_active=False; main.game_running=False; main.round_active=False; main.selected_scenario=None; main.moderator_id=None; main.MAX_SEATS=0
        await edit(c.message,"🚫 <b>بازی لغو شد.</b>",menu()); await c.answer()

    async def back_lobby(c): await render(c.message); await c.answer()
    async def change_s(c): main._lv6_setup=True; await edit(c.message,"📝 <b>تغییر سناریو</b>",scenario_kb()); await c.answer()
    async def change_m(c): main._lv6_setup=False; await edit(c.message,"🎩 <b>تغییر گرداننده</b>",await moderator_kb()); await c.answer()
    async def challenge(c): main.challenge_active=not getattr(main,'challenge_active',True); await manage(c)

    for fn,flt in [(new,lambda c:c.data=='lv6_new'),(scenario,lambda c:str(c.data).startswith('lv6_s:')),(moderator,lambda c:str(c.data).startswith('lv6_m:')),(home,lambda c:c.data=='lv6_home'),(back_s,lambda c:c.data=='lv6_back_s'),(toggle,lambda c:c.data=='lv6_toggle'),(seat_menu,lambda c:c.data=='lv6_seat_menu'),(seat,lambda c:str(c.data).startswith('lv6_seat:')),(reserve,lambda c:c.data=='lv6_reserve'),(manage,lambda c:c.data=='lv6_manage'),(cancel,lambda c:c.data=='lv6_cancel'),(back_lobby,lambda c:c.data=='lv6_back_lobby'),(change_s,lambda c:c.data=='lv6_change_s'),(change_m,lambda c:c.data=='lv6_change_m'),(challenge,lambda c:c.data=='lv6_challenge')]:
        dp.register_callback_query_handler(fn,flt); front(fn)
    main.main_menu_keyboard=menu
