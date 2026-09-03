"""Final authoritative round controls: mute, one-shot extra turns, challenge rules."""
from __future__ import annotations
import html
import logging
import time
from functools import wraps
from aiogram.dispatcher.handler import CancelHandler
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

def _handler(item): return getattr(item, 'handler', None)
def _group_id(main):
    for a in ('group_chat_id','ALLOWED_GROUP_ID','GROUP_ID','group_id'):
        v=getattr(main,a,None)
        if v:
            try:return int(v)
            except:pass
    return None

def _players(main):
    slots=getattr(main,'player_slots',{}) or {}; legacy=getattr(main,'players',{}) or {}; pg=getattr(main,'players_in_game',{}) or {}; out=[]
    for raw_seat,raw_uid in slots.items():
        try: seat=int(raw_seat); uid=int(raw_uid)
        except: continue
        info=pg.get(seat) or pg.get(str(seat)) or {}; name=info.get('name') if isinstance(info,dict) else None
        if not name:
            try:name=main.display_name(uid, legacy.get(uid))
            except:name=None
        if not name or str(name).strip() in {'?','❓','None','بازیکن'}:
            val=legacy.get(uid)
            if isinstance(val,str): name=val
            elif isinstance(val,dict): name=val.get('nickname') or val.get('full_name') or val.get('first_name')
            else: name=getattr(val,'full_name',None) or getattr(val,'first_name',None)
        if not name or str(name).strip() in {'?','❓','None'}: name=f'بازیکن {seat}'
        out.append((seat,uid,str(name)))
    return sorted(out)

def _ensure(main):
    if not isinstance(getattr(main,'_gm_muted_next_round',None),set): main._gm_muted_next_round=set()
    if not isinstance(getattr(main,'_gm_extra_next_round',None),set): main._gm_extra_next_round=set()
    if not isinstance(getattr(main,'_gm_extra_seats',None),set): main._gm_extra_seats=set()
    if not isinstance(getattr(main,'_gm_normal_order',None),list): main._gm_normal_order=[]
    if not hasattr(main,'_gm_extra_phase'): main._gm_extra_phase=False
    if not hasattr(main,'_gm_extra_turn_active'): main._gm_extra_turn_active=False

def _active(main):
    try:return main.turn_order[main.current_turn_index]
    except:return None
async def _admin(main,uid):
    if uid==getattr(main,'moderator_id',None): return True
    gid=_group_id(main)
    if not gid:return False
    try:return any(getattr(getattr(x,'user',None),'id',None)==uid for x in await main.bot.get_chat_administrators(gid))
    except:return False
def _move_front(reg,item):
    try: reg.insert(0,reg.pop(reg.index(item)))
    except ValueError: pass

async def install(main):
    _ensure(main); dp=main.dp; reg=getattr(getattr(dp,'callback_query_handlers',None),'handlers',None)
    if reg is None:return False
    async def hydrate():
        gid=_group_id(main)
        if not gid:return
        for seat,uid,_ in _players(main):
            try:
                m=await main.bot.get_chat_member(gid,uid); u=getattr(m,'user',None); n=getattr(u,'full_name',None) or getattr(u,'first_name',None)
                if n and isinstance(getattr(main,'players',None),dict) and (not main.players.get(uid) or str(main.players.get(uid)).strip() in {'?','❓'}): main.players[uid]=n
            except: pass
    async def open_sel(c,mode):
        if not await _admin(main,c.from_user.id): await c.answer('⛔ دسترسی ندارید.',show_alert=True); raise CancelHandler()
        if not getattr(main,'game_running',False): await c.answer('⚠️ بازی در حال اجرا نیست.',show_alert=True); raise CancelHandler()
        await hydrate(); icon='🔇' if mode=='mute' else '➕'; active=main._gm_muted_next_round if mode=='mute' else main._gm_extra_next_round; rows=[]
        for s,_,n in _players(main):
            mark=' ✅' if s in active else ''; rows.append([InlineKeyboardButton(f'{icon} صندلی {s} — {html.escape(n)}{mark}',callback_data=f'gm3:{mode}:{s}')])
        rows.append([InlineKeyboardButton('⬅️ مدیریت بازی',callback_data='manage_game')])
        text=f'{icon} <b>{"سکوت بازیکن" if mode=="mute" else "ترن اضافه"}</b>\n\nبازیکن موردنظر را انتخاب کنید.'
        text+=('\\n🔇 در دور بعد ترن عادی این بازیکن حذف می‌شود و در همان ترن امکان درخواست چالش هم ندارد.' if mode=='mute' else '\\n➕ دقیقاً یک ترن اضافه بعد از پایان دور جاری؛ بدون گزینه و امکان چالش.')
        await c.message.edit_text(text,reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),parse_mode='HTML'); await c.answer(); raise CancelHandler()
    async def toggle(c,mode):
        if not await _admin(main,c.from_user.id): await c.answer('⛔ دسترسی ندارید.',show_alert=True); raise CancelHandler()
        try:s=int(str(c.data).rsplit(':',1)[1])
        except: await c.answer('⚠️ بازیکن نامعتبر است.',show_alert=True); raise CancelHandler()
        if s not in {x[0] for x in _players(main)}: await c.answer('⚠️ بازیکن دیگر در بازی نیست.',show_alert=True); raise CancelHandler()
        a=main._gm_muted_next_round if mode=='mute' else main._gm_extra_next_round; other=main._extra_next_round if False else (main._gm_extra_next_round if mode=='mute' else main._gm_muted_next_round)
        if s in a:a.remove(s); msg='لغو شد'
        else:a.add(s); other.discard(s); msg='فعال شد'
        await c.answer(f'{"سکوت" if mode=="mute" else "ترن اضافه"} صندلی {s} {msg}.'); await open_sel(c,mode)
    dp.register_callback_query_handler(lambda c:open_sel(c,'mute'),lambda c:c.data=='gm:mute',state='*')
    dp.register_callback_query_handler(lambda c:open_sel(c,'extra'),lambda c:c.data=='gm:extra',state='*')
    dp.register_callback_query_handler(lambda c:toggle(c,'mute'),lambda c:str(c.data or '').startswith('gm3:mute:'),state='*')
    dp.register_callback_query_handler(lambda c:toggle(c,'extra'),lambda c:str(c.data or '').startswith('gm3:extra:'),state='*')
    for item in list(reg)[-4:]: _move_front(reg,item)

    tk=getattr(main,'turn_keyboard',None)
    if tk is not None and not getattr(tk,'_gm3',False):
        @wraps(tk)
        def turn_keyboard_v3(seat,is_challenge=False):
            _ensure(main)
            if not is_challenge and seat in main._gm_extra_seats and main._gm_extra_phase: return InlineKeyboardMarkup(row_width=1).add(InlineKeyboardButton('⏭ نکست',callback_data=f'next_{seat}'))
            if not is_challenge and seat in main._gm_muted_next_round: return InlineKeyboardMarkup(row_width=1).add(InlineKeyboardButton('⏭ نکست',callback_data=f'next_{seat}'))
            return tk(seat,is_challenge)
        turn_keyboard_v3._gm3=True; main.turn_keyboard=turn_keyboard_v3

    old_next=getattr(main,'next_turn',None)
    if old_next is not None:
        reg[:]=[x for x in reg if getattr(_handler(x),'__name__','')!='next_turn']
        async def next_v3(c):
            if getattr(getattr(c,'message',None),'chat',None) and c.message.chat.type=='private': await c.answer('این عملیات فقط داخل گروه انجام می‌شود.',show_alert=True); raise CancelHandler()
            uid=c.from_user.id; active=_active(main); owner=(getattr(main,'player_slots',{}) or {}).get(active)
            if uid!=getattr(main,'moderator_id',None) and uid!=owner: await c.answer('⛔ فقط صاحب نوبت یا گرداننده می‌تواند نکست بزند.',show_alert=True); raise CancelHandler()
            try:clicked=int(str(c.data).split('_',1)[1])
            except: await c.answer('⚠️ نوبت نامعتبر است.',show_alert=True); raise CancelHandler()
            if active is None or clicked!=active: await c.answer('⚠️ این نوبت دیگر فعال نیست.',show_alert=True); raise CancelHandler()
            now=time.time()
            if now-getattr(main,'_gm3_last_next',0)<1: await c.answer('⏳ لطفاً کمی صبر کنید.',show_alert=True); raise CancelHandler()
            main._gm3_last_next=now
            task=getattr(main,'turn_timer_task',None)
            if task and not task.done(): task.cancel()
            _ensure(main)
            if getattr(main,'challenge_mode',False):
                main.challenge_mode=False
                if getattr(main,'paused_main_player',None) is not None:
                    if getattr(main,'post_challenge_advance',False): main.current_turn_index+=1
                    main.post_challenge_advance=False; main.paused_main_player=None; main.paused_main_duration=None
            else:
                pending=getattr(main,'pending_challenges',{})
                if active not in main._gm_extra_seats and active not in main._gm_muted_next_round and active in pending:
                    challenger=pending.pop(active); cs=next((s for s,u in (getattr(main,'player_slots',{}) or {}).items() if u==challenger),None)
                    if cs is not None:
                        main.paused_main_player=active; main.paused_main_duration=120; main.post_challenge_advance=True; main.challenge_mode=True; main._gm_extra_turn_active=False; await main.start_turn(cs,duration=60,is_challenge=True); return
                main.current_turn_index+=1
            order=list(getattr(main,'turn_order',[]) or []); idx=int(getattr(main,'current_turn_index',0))
            if idx>=len(order):
                if not main._gm_extra_phase:
                    base=list(main._gm_normal_order or order)
                    if not base: base=sorted((getattr(main,'player_slots',{}) or {}).keys())
                    muted=set(main._gm_muted_next_round); extras=[s for s in base if s in main._gm_extra_next_round and s not in muted]
                    main._gm_extra_next_round.clear()
                    if extras:
                        main.turn_order=base+extras; main._gm_extra_seats=set(extras); main._gm_extra_phase=True; main.current_turn_index=len(base)-1
                        await main.start_turn(extras[0],duration=120,is_challenge=False); return
                    nxt=[s for s in base if s not in muted]; main._gm_muted_next_round.clear(); main._gm_extra_seats.clear(); main._gm_normal_order=list(nxt); main.turn_order=nxt; main.current_turn_index=-1
                    if not nxt: await c.answer('⚠️ بازیکنی برای دور بعد باقی نمانده.',show_alert=True); raise CancelHandler()
                    await main.start_turn(nxt[0],duration=120,is_challenge=False); return
                base=list(main._gm_normal_order or order); muted=set(main._gm_muted_next_round); nxt=[s for s in base if s not in muted]
                main._gm_muted_next_round.clear(); main._gm_extra_seats.clear(); main._gm_extra_phase=False; main._gm_normal_order=list(nxt); main.turn_order=nxt; main.current_turn_index=-1
                if not nxt: await c.answer('⚠️ بازیکنی برای دور بعد باقی نمانده.',show_alert=True); raise CancelHandler()
                await main.start_turn(nxt[0],duration=120,is_challenge=False); return
            await main.start_turn(order[idx],duration=120,is_challenge=False)
        next_v3.__name__='next_turn'; next_v3._gm3=True; dp.register_callback_query_handler(next_v3,lambda c:str(c.data or '').startswith('next_'),state='*'); _move_front(reg,next_v3)

    async def challenge_guard(c):
        requester=c.from_user.id; active=_active(main); seat=next((s for s,u in (getattr(main,'player_slots',{}) or {}).items() if u==requester),None)
        if getattr(main,'_gm_extra_turn_active',False) or (seat is not None and (seat in main._gm_extra_seats or seat in main._gm_muted_next_round)):
            await c.answer('⛔ این نوبت امکان چالش ندارد.',show_alert=True); raise CancelHandler()
        if seat is None or active is None or int(seat)!=int(active) or getattr(main,'challenge_mode',False):
            await c.answer('⛔ فقط صاحب نوبت عادی می‌تواند درخواست چالش بدهد.',show_alert=True); raise CancelHandler()
    dp.register_callback_query_handler(challenge_guard,lambda c:str(c.data or '').startswith('challenge_request_'),state='*')
    for item in list(reg):
        if getattr(_handler(item),'__name__','')=='challenge_guard': _move_front(reg,item); break
    st=getattr(main,'start_turn',None)
    if st is not None and not getattr(st,'_gm3_start',False):
        @wraps(st)
        async def start_v3(seat,duration=120,is_challenge=False):
            _ensure(main); main._gm_extra_turn_active=bool(not is_challenge and seat in main._gm_extra_seats and main._gm_extra_phase); return await st(seat,duration=duration,is_challenge=is_challenge)
        start_v3._gm3_start=True; main.start_turn=start_v3
    main._gm3_installed=True; logging.info('GM V3 authoritative controls installed'); return True
