from __future__ import annotations

import html
import json
import logging
import os
from datetime import datetime
from typing import Any

from aiogram import types
from aiogram.dispatcher.handler import CancelHandler
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import text

from repositories.base import DatabaseRepository
from repositories.rating_repository import RatingRepository

ACHIEVEMENTS = (
    {"id":"games_1","name":"اولین بازی","description":"اولین بازی ثبت‌شده را انجام بده","metric":"games","target":1,"reward":25},
    {"id":"games_10","name":"بازیکن فعال","description":"۱۰ بازی انجام بده","metric":"games","target":10,"reward":75,"tag_name":"بازیکن فعال","tag_emoji":"🔥"},
    {"id":"games_25","name":"بازیکن باتجربه","description":"۲۵ بازی انجام بده","metric":"games","target":25,"reward":150},
    {"id":"games_50","name":"بازیکن حرفه‌ای","description":"۵۰ بازی انجام بده","metric":"games","target":50,"reward":300,"tag_name":"بازیکن حرفه‌ای","tag_emoji":"🎖️"},
    {"id":"games_100","name":"افسانه مافیا","description":"۱۰۰ بازی انجام بده","metric":"games","target":100,"reward":700,"tag_name":"افسانه مافیا","tag_emoji":"👑"},
    {"id":"wins_10","name":"برنده‌ساز","description":"۱۰ برد ثبت کن","metric":"wins","target":10,"reward":200,"tag_name":"برنده‌ساز","tag_emoji":"🏆"},
    {"id":"challenges_100","name":"چالشگر","description":"در مجموع ۱۰۰ چالش ثبت‌شده داشته باش","metric":"challenges","target":100,"reward":500,"tag_name":"چالشگر","tag_emoji":"⚔️"},
    {"id":"clean_10","name":"منضبط","description":"۱۰ بازی را بدون دریافت تذکر به پایان برسان","metric":"clean_games","target":10,"reward":175,"tag_name":"منضبط","tag_emoji":"🛡️"},
    {"id":"win_streak_5","name":"سریال برد","description":"۵ برد پیاپی ثبت کن","metric":"best_win_streak","target":5,"reward":250,"tag_name":"سریال برد","tag_emoji":"🔥"},
    {"id":"positive_50","name":"مثبت پنجاه","description":"مجموع تغییر امتیاز بازی‌هایت به +۵۰ یا بیشتر برسد","metric":"delta","target":50,"reward":125},
    {"id":"avg_70","name":"ثبات درخشان","description":"با حداقل ۱۰ بازی، میانگین امتیاز بازی‌هایت ۷۰ یا بیشتر باشد","metric":"avg_game_score","target":70,"reward":300,"requires_games":10,"tag_name":"ثبات درخشان","tag_emoji":"💎"},
    {"id":"mafia_wins_20","name":"مافیای کارکشته","description":"۲۰ برد در ساید مافیا ثبت کن","metric":"mafia_wins","target":20,"reward":300},
    {"id":"mafia_wins_50","name":"فرمانده مافیا","description":"۵۰ برد در ساید مافیا ثبت کن","metric":"mafia_wins","target":50,"reward":700},
    {"id":"independent_wins_3","name":"مستقل موفق","description":"۳ برد در ساید مستقل ثبت کن","metric":"independent_wins","target":3,"reward":200},
    {"id":"independent_wins_5","name":"مستقل افسانه‌ای","description":"۵ برد در ساید مستقل ثبت کن","metric":"independent_wins","target":5,"reward":400},
    {"id":"citizen_wins_20","name":"شهروند کارکشته","description":"۲۰ برد در ساید شهروند ثبت کن","metric":"citizen_wins","target":20,"reward":300},
    {"id":"citizen_wins_50","name":"قهرمان شهر","description":"۵۰ برد در ساید شهروند ثبت کن","metric":"citizen_wins","target":50,"reward":700},
)
class FeatureRepository(DatabaseRepository):
    def _summary(self, uid):
        with self.SessionLocal() as s:
            rows=s.execute(text("select r.score,r.result,r.warning_penalty,r.challenge_bonus,r.role,g.state from public.mafia_ratings r left join public.mafia_games g on g.id=r.game_id where r.user_id=:uid order by r.created_at asc"),{"uid":int(uid)}).mappings().all()
        games=len(rows); wins=sum(r["result"]=="win" for r in rows); challenges=sum(int(r["challenge_bonus"] or 0) for r in rows)//3; clean=sum(int(r["warning_penalty"] or 0)==0 for r in rows); delta=sum(int(r["score"] or 0) for r in rows); scores=[50+int(r["score"] or 0) for r in rows]; streak=best=0
        for r in rows:
            if r["result"]=="win": streak+=1; best=max(best,streak)
            else: streak=0
        mafia_wins=independent_wins=citizen_wins=0
        for r in rows:
            if r["result"] != "win": continue
            state = r.get("state") or {}
            if isinstance(state, str):
                try: state = json.loads(state)
                except Exception: state = {}
            cfg = state.get("scenario_config") or state.get("scenario") or {}
            rules = cfg.get("role_rules") or {}
            role = r.get("role")
            side = ""
            if isinstance(rules, dict) and isinstance(rules.get(role), dict):
                side = str(rules[role].get("side") or "")
            if not side:
                sides = cfg.get("sides") or {}
                if isinstance(sides, dict): side = str(sides.get(role) or "")
            norm = side.strip().lower().replace("‌"," ")
            if "مافیا" in side or "mafia" in norm: mafia_wins += 1
            elif "مستقل" in side or "independent" in norm: independent_wins += 1
            elif "شهروند" in side or "citizen" in norm: citizen_wins += 1
        return {"games":games,"wins":wins,"challenges":challenges,"clean_games":clean,"delta":delta,
                "avg_game_score":sum(scores)/games if games else 0,"best_win_streak":best,
                "mafia_wins":mafia_wins,"independent_wins":independent_wins,"citizen_wins":citizen_wins}
    def achievement_points(self,uid):
        with self.SessionLocal() as s:return int(s.execute(text("select coalesce(sum(reward_points),0) from public.mafia_achievement_rewards where player_id=:uid"),{"uid":int(uid)}).scalar_one() or 0)
    def sync_achievements(self,uid):
        stats=self._summary(uid); unlocked=[]
        with self.SessionLocal() as s:
            for a in ACHIEVEMENTS:
                if stats.get(a["metric"],0)<a["target"] or (a.get("requires_games") and stats["games"]<a["requires_games"]):continue
                if s.execute(text("select id from public.mafia_player_achievements where player_id=:uid and achievement_id=:aid"),{"uid":int(uid),"aid":a["id"]}).first():unlocked.append(a);continue
                s.execute(text("insert into public.mafia_player_achievements(player_id,achievement_id) values(:uid,:aid)"),{"uid":int(uid),"aid":a["id"]})
                if a.get("reward"):s.execute(text("insert into public.mafia_achievement_rewards(player_id,achievement_id,reward_points) values(:uid,:aid,:reward) on conflict(player_id,achievement_id) do nothing"),{"uid":int(uid),"aid":a["id"],"reward":int(a["reward"])})
                if a.get("tag_name"):s.execute(text("insert into public.mafia_player_tags(player_id,achievement_id,name,emoji) values(:uid,:aid,:name,:emoji) on conflict(player_id,achievement_id) do nothing"),{"uid":int(uid),"aid":a["id"],"name":a["tag_name"],"emoji":a["tag_emoji"]})
                unlocked.append(a)
            s.commit()
        return unlocked
    def achievements(self,uid):
        stats=self._summary(uid)
        with self.SessionLocal() as s:unlocked={r[0] for r in s.execute(text("select achievement_id from public.mafia_player_achievements where player_id=:uid"),{"uid":int(uid)}).all()}
        out=[]
        for a in ACHIEVEMENTS:
            current=stats.get(a["metric"],0);pct=min(100,int(float(current)*100/a["target"])) if a["target"] else 100
            if a.get("requires_games") and stats["games"]<a["requires_games"]:pct=min(pct,int(stats["games"]*100/a["requires_games"]))
            out.append({**a,"current":current,"percent":pct,"unlocked":a["id"] in unlocked})
        return out
    def tags(self,uid):
        with self.SessionLocal() as s:return [dict(r) for r in s.execute(text("select id,achievement_id,name,emoji,is_active from public.mafia_player_tags where player_id=:uid order by id"),{"uid":int(uid)}).mappings().all()]
    def toggle_tag(self,uid,tag_id):
        with self.SessionLocal() as s:
            row=s.execute(text("select is_active from public.mafia_player_tags where id=:id and player_id=:uid"),{"id":int(tag_id),"uid":int(uid)}).first()
            if not row:return False
            active=not bool(row[0])
            if active:s.execute(text("update public.mafia_player_tags set is_active=false where player_id=:uid"),{"uid":int(uid)})
            s.execute(text("update public.mafia_player_tags set is_active=:active where id=:id and player_id=:uid"),{"active":active,"id":int(tag_id),"uid":int(uid)});s.commit();return active
    def active_tag(self,uid):
        with self.SessionLocal() as s:
            row=s.execute(text("select emoji,name from public.mafia_player_tags where player_id=:uid and is_active=true order by id limit 1"),{"uid":int(uid)}).mappings().first();return dict(row) if row else None
    def event_list(self,active_only=False):
        with self.SessionLocal() as s:
            q="select * from public.mafia_events"+(" where status='active'" if active_only else "")+" order by starts_at nulls last,created_at desc";return [dict(r) for r in s.execute(text(q)).mappings().all()]
    def event(self,eid):
        with self.SessionLocal() as s:
            row=s.execute(text("select * from public.mafia_events where id=:id"),{"id":int(eid)}).mappings().first();return dict(row) if row else None
    def event_players(self,eid):
        with self.SessionLocal() as s:return [dict(r) for r in s.execute(text("select ep.*,p.nickname,p.first_name,p.username from public.mafia_event_players ep join public.mafia_players p on p.id=ep.player_id where ep.event_id=:eid order by ep.registered_at"),{"eid":int(eid)}).mappings().all()]
    def event_stages(self,eid):
        with self.SessionLocal() as s:return [dict(r) for r in s.execute(text("select * from public.mafia_event_stages where event_id=:eid order by stage_order,id"),{"eid":int(eid)}).mappings().all()]
    def register_event_player(self,eid,uid):
        with self.SessionLocal() as s:
            if s.execute(text("select status from public.mafia_events where id=:id"),{"id":int(eid)}).scalar_one_or_none()!="active":return False
            s.execute(text("insert into public.mafia_event_players(event_id,player_id) values(:eid,:uid) on conflict(event_id,player_id) do update set status='registered',updated_at=now()"),{"eid":int(eid),"uid":int(uid)});s.commit();return True
    def create_event(self,name,starts_at,created_by):
        with self.SessionLocal() as s:
            row=s.execute(text("insert into public.mafia_events(name,starts_at,status,created_by) values(:name,cast(:starts_at as timestamp),'active',:uid) returning id"),{"name":name.strip(),"starts_at":starts_at,"uid":int(created_by)}).scalar_one();s.commit();return int(row)
    def update_event(self,eid,**values):
        allowed={"name","starts_at","status","grouping_mode","description"};values={k:v for k,v in values.items() if k in allowed}
        if not values:return
        clauses=[];params={"id":int(eid)}
        for k,v in values.items():clauses.append(f"{k}=:{k}");params[k]=v
        with self.SessionLocal() as s:s.execute(text(f"update public.mafia_events set {', '.join(clauses)},updated_at=now() where id=:id"),params);s.commit()
    def create_stage(self,eid,name,kind):
        with self.SessionLocal() as s:
            order=int(s.execute(text("select coalesce(max(stage_order),0)+1 from public.mafia_event_stages where event_id=:eid"),{"eid":int(eid)}).scalar_one());row=s.execute(text("insert into public.mafia_event_stages(event_id,name,stage_type,stage_order) values(:eid,:name,:type,:ord) returning id"),{"eid":int(eid),"name":name,"type":kind,"ord":order}).scalar_one();s.commit();return int(row)
    def stage_players(self,sid):
        with self.SessionLocal() as s:return [dict(r) for r in s.execute(text("select esp.*,p.nickname,p.first_name,p.username from public.mafia_event_stage_players esp join public.mafia_players p on p.id=esp.player_id where esp.stage_id=:sid order by esp.group_no nulls first,p.id"),{"sid":int(sid)}).mappings().all()]
    def assign_group(self,sid,uid,group_no):
        with self.SessionLocal() as s:s.execute(text("insert into public.mafia_event_stage_players(stage_id,player_id,group_no) values(:sid,:uid,:grp) on conflict(stage_id,player_id) do update set group_no=excluded.group_no,updated_at=now()"),{"sid":int(sid),"uid":int(uid),"grp":int(group_no)});s.commit()
    def assign_score(self,sid,uid,score):
        with self.SessionLocal() as s:s.execute(text("insert into public.mafia_event_stage_players(stage_id,player_id,score) values(:sid,:uid,:score) on conflict(stage_id,player_id) do update set score=excluded.score,updated_at=now()"),{"sid":int(sid),"uid":int(uid),"score":int(score)});s.commit()
    def auto_group(self,sid,count):
        with self.SessionLocal() as s:
            rows=s.execute(text("select ep.player_id from public.mafia_event_players ep join public.mafia_event_stages es on es.event_id=ep.event_id where es.id=:sid and ep.status='registered' order by ep.registered_at,ep.player_id"),{"sid":int(sid)}).scalars().all()
            for i,uid in enumerate(rows):s.execute(text("insert into public.mafia_event_stage_players(stage_id,player_id,group_no) values(:sid,:uid,:grp) on conflict(stage_id,player_id) do update set group_no=excluded.group_no,updated_at=now()"),{"sid":int(sid),"uid":int(uid),"grp":(i%max(1,int(count)))+1})
            s.execute(text("update public.mafia_events set grouping_mode='auto',updated_at=now() where id=(select event_id from public.mafia_event_stages where id=:sid)"),{"sid":int(sid)});s.commit()
    def replace_player(self,eid,old_uid,new_uid):
        with self.SessionLocal() as s:
            s.execute(text("update public.mafia_event_players set status='replaced',updated_at=now() where event_id=:eid and player_id=:old"),{"eid":int(eid),"old":int(old_uid)});s.execute(text("insert into public.mafia_event_players(event_id,player_id,status,replaced_player_id) values(:eid,:new,'registered',:old) on conflict(event_id,player_id) do update set status='registered',replaced_player_id=:old,updated_at=now()"),{"eid":int(eid),"new":int(new_uid),"old":int(old_uid)});s.execute(text("update public.mafia_event_stage_players set player_id=:new,status='active',updated_at=now() where player_id=:old and stage_id in (select id from public.mafia_event_stages where event_id=:eid)"),{"eid":int(eid),"old":int(old_uid),"new":int(new_uid)});s.commit()
    def incident(self,gid):
        with self.SessionLocal() as s:
            row=s.execute(text("select * from public.mafia_game_incidents where game_id=:gid"),{"gid":str(gid)}).mappings().first();return dict(row) if row else None
    def save_incident(self,gid,content,actor,finalized,edit=False):
        with self.SessionLocal() as s:
            payload=json.dumps(content,ensure_ascii=False);row=s.execute(text("select id,version from public.mafia_game_incidents where game_id=:gid"),{"gid":str(gid)}).mappings().first()
            if row:
                version=int(row["version"])+(1 if edit else 0)
                if edit:s.execute(text("insert into public.mafia_game_incident_history(incident_id,version,content,action,actor_id) values(:iid,:ver,cast(:content as jsonb),'edit',:actor)"),{"iid":row["id"],"ver":version,"content":payload,"actor":int(actor)})
                s.execute(text("update public.mafia_game_incidents set content=cast(:content as jsonb),version=:version,finalized=:finalized,updated_at=now() where id=:id"),{"content":payload,"version":version,"finalized":finalized,"id":row["id"]})
            else:
                new=s.execute(text("insert into public.mafia_game_incidents(game_id,content,version,finalized,created_by) values(:gid,cast(:content as jsonb),1,:finalized,:actor) returning id"),{"gid":str(gid),"content":payload,"finalized":finalized,"actor":int(actor)}).scalar_one();s.execute(text("insert into public.mafia_game_incident_history(incident_id,version,content,action,actor_id) values(:iid,1,cast(:content as jsonb),'create',:actor)"),{"iid":new,"content":payload,"actor":int(actor)})
            s.commit()

class MafiaProgressEvents:
    def __init__(self,app):self.app=app;self.repo=FeatureRepository();self.ratings=RatingRepository();app._achievement_engine=self.repo
    def _is_private(self,obj):return bool(getattr(getattr(obj,"message",None),"chat",None) and obj.message.chat.type=="private")
    async def _admin(self,callback):
        if not self._is_private(callback):await callback.answer("⛔ این بخش فقط در گفت‌وگوی خصوصی در دسترس است.",show_alert=True);return False
        uid=int(callback.from_user.id)
        if uid==int(getattr(self.app,"moderator_id",0) or 0):return True
        gid=getattr(self.app,"group_chat_id",None) or getattr(self.app,"ALLOWED_GROUP_ID",None) or int(os.getenv("ALLOWED_GROUP_ID","0") or 0)
        if not gid:return False
        try:return uid in {int(x.user.id) for x in await self.app.bot.get_chat_administrators(int(gid))}
        except Exception:logging.exception("feature admin check failed");return False
    def _state(self,uid):
        with self.repo.SessionLocal() as s:
            row=s.execute(text("select state,data from public.mafia_fsm_state where chat_id='private' and user_id=:uid"),{"uid":str(uid)}).mappings().first();return {"state":row["state"],"data":dict(row["data"] or {})} if row else {"state":None,"data":{}}
    def _set_state(self,uid,state,data=None):
        with self.repo.SessionLocal() as s:s.execute(text("insert into public.mafia_fsm_state(chat_id,user_id,state,data) values('private',:uid,:state,cast(:data as jsonb)) on conflict(chat_id,user_id) do update set state=excluded.state,data=excluded.data,updated_at=now()"),{"uid":str(uid),"state":state,"data":json.dumps(data or {},ensure_ascii=False)});s.commit()
    def _name(self,row):return str(row.get("nickname") or row.get("first_name") or row.get("username") or row.get("player_id") or "بازیکن")
    def _progress(self,current,target):
        pct=min(100,int(float(current)*100/target)) if target else 100;full=round(pct/10);return f"{'🟩'*full}{'⬜'*(10-full)} {pct}%"
    async def achievements(self,callback):
        uid=int(callback.from_user.id);self.repo.sync_achievements(uid);rows=self.repo.achievements(uid);lines=["🏆 <b>دستاوردها</b>","",f"🎁 امتیاز دستاوردها: <b>{self.repo.achievement_points(uid)}</b>",""]
        for a in rows:lines += [f"{'✅' if a['unlocked'] else '🔒'} <b>{a['name']}</b> — {a['description']}",f"   {min(float(a['current']),float(a['target'])):g}/{a['target']:g} تکمیل شده",f"   {self._progress(a['current'],a['target'])}",f"   🎁 +{a['reward']} امتیاز" +(f" | 🏷 {a['tag_emoji']} {a['tag_name']}" if a.get('tag_name') else ""),""]
        kb=InlineKeyboardMarkup(row_width=1);kb.add(InlineKeyboardButton("🏷 تگ‌های من",callback_data="mfeature:tags"));kb.add(InlineKeyboardButton("⬅️ پروفایل پیشرفته",callback_data="profile:advanced"));await callback.message.edit_text("\n".join(lines),parse_mode="HTML",reply_markup=kb);await callback.answer()
    async def tags(self,callback):
        uid=int(callback.from_user.id);self.repo.sync_achievements(uid);tags=self.repo.tags(uid);text_body="🏷 <b>تگ‌های من</b>\n\n"+("هنوز تگی آزاد نشده است." if not tags else "\n".join(f"{'✅' if t['is_active'] else '▫️'} {html.escape(str(t['emoji']))} {html.escape(str(t['name']))}" for t in tags));kb=InlineKeyboardMarkup(row_width=1)
        for t in tags:kb.add(InlineKeyboardButton(("✅ " if t["is_active"] else "▫️ ")+f"{t['emoji']} {t['name']}",callback_data=f"mfeature:tag:{int(t['id'])}"))
        kb.add(InlineKeyboardButton("⬅️ دستاوردها",callback_data="profile:advanced:achievements"));await callback.message.edit_text(text_body,parse_mode="HTML",reply_markup=kb);await callback.answer()
    async def tag_toggle(self,callback):
        active=self.repo.toggle_tag(callback.from_user.id,int(str(callback.data).split(":")[-1]));await callback.answer("✅ تگ فعال شد." if active else "▫️ تگ غیرفعال شد.");await self.tags(callback)
    async def profile_override(self,callback):
        uid=int(callback.from_user.id);row=self.ratings.player_profile(uid) or {"user_id":uid,"games":0,"score":50,"wins":0,"losses":0,"draws":0};summary=self.ratings.player_summary(uid);rank=self.ratings.rank(uid);name=html.escape(str(row.get("nickname") or row.get("first_name") or row.get("username") or uid));avg=float(summary.get("avg_game_score") or 0);text_body=("👤 <b>پروفایل بازیکن</b>\n\n"f"🧑 نام: {name}\n"f"🎮 تعداد بازی: {int(row.get('games') or 0)}\n"f"🏆 برد: {int(row.get('wins') or 0)}\n❌ باخت: {int(row.get('losses') or 0)}\n🤝 مساوی: {int(row.get('draws') or 0)}\n"f"⭐ امتیاز: {int(row.get('score') or 50)}\n📊 میانگین امتیاز هر بازی: <b>{avg:.1f}</b>\n"f"🏅 رتبه: {rank.get('rank') or '—'} از {rank.get('total_players',0)}");kb=InlineKeyboardMarkup(row_width=2);kb.row(InlineKeyboardButton("📊 آمار",callback_data="ustats:stats"),InlineKeyboardButton("🏆 دستاوردها",callback_data="profile:advanced:achievements"));kb.add(InlineKeyboardButton("🔄 بروزرسانی",callback_data="ustats:profile"));await callback.message.edit_text(text_body,parse_mode="HTML",reply_markup=kb);await callback.answer()
    async def stats_override(self,callback):
        uid=int(callback.from_user.id);row=self.ratings.player_summary(uid)
        if not row or int(row.get("games",0) or 0)==0:text_body="📊 <b>آمار</b>\n\nهنوز بازی‌ای برای شما ثبت نشده است.\n⭐ امتیاز پایه: <b>50</b>"
        else:text_body=("📊 <b>آمار بازیکن</b>\n\n"f"🎮 بازی‌ها: <b>{int(row.get('games') or 0)}</b>\n"f"🏆 برد: <b>{int(row.get('wins') or 0)}</b>\n❌ باخت: <b>{int(row.get('losses') or 0)}</b>\n🤝 مساوی: <b>{int(row.get('draws') or 0)}</b>\n"f"⭐ امتیاز کل: <b>{int(row.get('score') or 50)}</b>\n🎁 امتیاز دستاوردها: <b>{int(row.get('achievement_points') or 0)}</b>\n📊 میانگین امتیاز هر بازی: <b>{float(row.get('avg_game_score') or 0):.1f}</b>");kb=InlineKeyboardMarkup(row_width=2);kb.row(InlineKeyboardButton("🏆 دستاوردها",callback_data="profile:advanced:achievements"),InlineKeyboardButton("⬅️ پروفایل",callback_data="ustats:profile"));await callback.message.edit_text(text_body,parse_mode="HTML",reply_markup=kb);await callback.answer()
    def _event_text(self,e,players):return f"🎪 <b>{html.escape(str(e['name']))}</b>\n\n🗓 شروع: {html.escape(str(e.get('starts_at') or 'تعیین نشده'))}\n📌 وضعیت: <b>{e['status']}</b>\n👥 ثبت‌نام: <b>{len([p for p in players if p.get('status')=='registered'])}</b>"
    async def events(self,callback):
        events=self.repo.event_list();text_body="🎪 <b>اونت‌ها</b>\n\n"+("هنوز اونتی ایجاد نشده است." if not events else "\n".join(f"{'🟢' if e['status']=='active' else '⚪'} {e['id']} — {html.escape(str(e['name']))}" for e in events[:10]));kb=InlineKeyboardMarkup(row_width=1)
        for e in events[:10]:kb.add(InlineKeyboardButton(f"🎪 {e['name']}",callback_data=f"mfeature:event:{int(e['id'])}"))
        if await self._admin(callback):kb.add(InlineKeyboardButton("➕ افزودن اونت",callback_data="mfeature:event_add"))
        await callback.message.edit_text(text_body,parse_mode="HTML",reply_markup=kb);await callback.answer()
    async def event_detail(self,callback):
        eid=int(str(callback.data).split(":")[-1]);e=self.repo.event(eid);players=self.repo.event_players(eid);stages=self.repo.event_stages(eid)
        if not e:await callback.answer("❌ اونت پیدا نشد.",show_alert=True);return
        lines=[self._event_text(e,players),""]
        for stage in stages:
            lines.append(f"📚 {stage['name']} — {stage['status']}")
            for p in self.repo.stage_players(stage["id"]):lines.append(f"  └ {self._name(p)} [گروه {p.get('group_no') or '—'}] = {p.get('score') if p.get('score') is not None else '—'}")
        kb=InlineKeyboardMarkup(row_width=2)
        if e["status"]=="active":kb.row(InlineKeyboardButton("✅ ثبت‌نام",callback_data=f"mfeature:event_register:{eid}"),InlineKeyboardButton("👥 بازیکنان",callback_data=f"mfeature:event_players:{eid}"))
        if await self._admin(callback):kb.row(InlineKeyboardButton("⚙️ مدیریت",callback_data=f"mfeature:event_admin:{eid}"))
        kb.add(InlineKeyboardButton("⬅️ اونت‌ها",callback_data="mfeature:events"));await callback.message.edit_text("\n".join(lines),parse_mode="HTML",reply_markup=kb);await callback.answer()
    async def event_register(self,callback):
        eid=int(str(callback.data).split(":")[-1]);ok=self.repo.register_event_player(eid,callback.from_user.id);await callback.answer("✅ ثبت‌نام شما در اونت انجام شد." if ok else "❌ اونت فعال نیست.",show_alert=not ok)
        if ok:await self.event_detail(callback)
    async def event_players(self,callback):
        eid=int(str(callback.data).split(":")[-1]);players=self.repo.event_players(eid);lines=["👥 <b>بازیکنان اونت</b>",""]+[f"{i}. {html.escape(self._name(p))} — {'ثبت‌نام‌شده' if p.get('status')=='registered' else p.get('status')}" for i,p in enumerate(players,1)];lines.append(f"\n⭐ بازیکنان ثبت‌نام‌شده: {sum(p.get('status')=='registered' for p in players)}");kb=InlineKeyboardMarkup(row_width=2)
        if await self._admin(callback):kb.row(InlineKeyboardButton("➕ افزودن بازیکن",callback_data=f"mfeature:event_add_player:{eid}"),InlineKeyboardButton("🗑 حذف بازیکن",callback_data=f"mfeature:event_remove_player:{eid}"));kb.add(InlineKeyboardButton("⬅️ مدیریت اونت",callback_data=f"mfeature:event_admin:{eid}"))
        else:kb.add(InlineKeyboardButton("⬅️ اونت",callback_data=f"mfeature:event:{eid}"))
        await callback.message.edit_text("\n".join(lines),parse_mode="HTML",reply_markup=kb);await callback.answer()
    async def event_add_player(self,callback):
        if not await self._admin(callback):return
        eid=int(str(callback.data).split(":")[-1]);self._set_state(callback.from_user.id,"event_add_player",{"event_id":eid});await callback.message.answer("➕ شناسه عددی بازیکن را ارسال کنید.");await callback.answer()
    async def event_remove_player(self,callback):
        if not await self._admin(callback):return
        eid=int(str(callback.data).split(":")[-1]);kb=InlineKeyboardMarkup(row_width=1)
        for p in self.repo.event_players(eid):
            if p.get("status")=="registered":kb.add(InlineKeyboardButton(f"🗑 {self._name(p)}",callback_data=f"mfeature:event_remove:{eid}:{int(p['player_id'])}"))
        kb.add(InlineKeyboardButton("⬅️ بازیکنان",callback_data=f"mfeature:event_players:{eid}"));await callback.message.edit_text("🗑 بازیکنی که باید از ثبت‌نام خارج شود را انتخاب کنید:",reply_markup=kb);await callback.answer()
    async def event_remove(self,callback):
        if not await self._admin(callback):return
        parts=str(callback.data).split(":");eid,uid=int(parts[2]),int(parts[3])
        with self.repo.SessionLocal() as s:
            s.execute(text("update public.mafia_event_players set status='withdrawn',updated_at=now() where event_id=:eid and player_id=:uid"),{"eid":eid,"uid":uid});s.execute(text("update public.mafia_event_stage_players set status='replaced',updated_at=now() where player_id=:uid and stage_id in (select id from public.mafia_event_stages where event_id=:eid)"),{"eid":eid,"uid":uid});s.commit()
        await callback.answer("🗑 بازیکن از ثبت‌نام خارج شد.");await self.event_players(types.SimpleNamespace(from_user=callback.from_user,message=callback.message,data=f"mfeature:event_players:{eid}",answer=callback.answer))
    async def event_admin(self,callback):
        if not await self._admin(callback):await callback.answer("⛔ دسترسی ندارید.",show_alert=True);return
        eid=int(str(callback.data).split(":")[-1]);e=self.repo.event(eid);kb=InlineKeyboardMarkup(row_width=2);kb.row(InlineKeyboardButton("📝 تغییر نام",callback_data=f"mfeature:event_edit_name:{eid}"),InlineKeyboardButton("🗓 تغییر زمان",callback_data=f"mfeature:event_edit_time:{eid}"));kb.row(InlineKeyboardButton("👥 بازیکنان",callback_data=f"mfeature:event_players:{eid}"));kb.row(InlineKeyboardButton("➕ مرحله مقدماتی",callback_data=f"mfeature:stage_add:preliminary:{eid}"),InlineKeyboardButton("🏆 مرحله فینال",callback_data=f"mfeature:stage_add:final:{eid}"));kb.row(InlineKeyboardButton("🤖 گروه‌بندی خودکار",callback_data=f"mfeature:auto_group:{eid}"),InlineKeyboardButton("✋ گروه‌بندی دستی",callback_data=f"mfeature:manual_group:{eid}"));kb.row(InlineKeyboardButton("⭐ امتیازات",callback_data=f"mfeature:event_scores:{eid}"),InlineKeyboardButton("🔄 جایگزینی",callback_data=f"mfeature:event_replace:{eid}"));kb.row(InlineKeyboardButton("❌ لغو اونت",callback_data=f"mfeature:event_cancel:{eid}"),InlineKeyboardButton("🏁 اتمام اونت",callback_data=f"mfeature:event_finish:{eid}"));kb.add(InlineKeyboardButton("⬅️ اونت",callback_data=f"mfeature:event:{eid}"));await callback.message.edit_text(f"⚙️ <b>مدیریت اونت</b>\n\n{html.escape(str(e['name']))}",parse_mode="HTML",reply_markup=kb);await callback.answer()
    async def start_add_event(self,callback):
        if not await self._admin(callback):return
        self._set_state(callback.from_user.id,"event_add_name",{});await callback.message.edit_text("➕ <b>افزودن اونت</b>\n\nنام اونت را ارسال کنید.",parse_mode="HTML");await callback.answer()
    async def event_scores(self,callback):
        if not await self._admin(callback):return
        eid=int(str(callback.data).split(":")[-1]);stages=self.repo.event_stages(eid)
        if not stages:await callback.answer("⚠️ ابتدا یک مرحله ایجاد کنید.",show_alert=True);return
        kb=InlineKeyboardMarkup(row_width=1)
        for stage in stages:kb.add(InlineKeyboardButton(f"⭐ {stage['name']}",callback_data=f"mfeature:score_stage:{int(stage['id'])}"))
        kb.add(InlineKeyboardButton("⬅️ مدیریت اونت",callback_data=f"mfeature:event_admin:{eid}"));await callback.message.edit_text("⭐ <b>مرحله موردنظر را انتخاب کنید:</b>",parse_mode="HTML",reply_markup=kb);await callback.answer()
    async def score_stage(self,callback):
        if not await self._admin(callback):return
        sid=int(str(callback.data).split(":")[-1]);players=self.repo.stage_players(sid);kb=InlineKeyboardMarkup(row_width=1)
        for p in players:kb.add(InlineKeyboardButton(f"{self._name(p)} — {p.get('score') if p.get('score') is not None else '—'}",callback_data=f"mfeature:score_player:{sid}:{int(p['player_id'])}"))
        await callback.message.edit_text("⭐ <b>بازیکن را انتخاب کنید:</b>",parse_mode="HTML",reply_markup=kb);await callback.answer()
    async def score_player(self,callback):
        if not await self._admin(callback):return
        _,_,sid,uid=str(callback.data).split(":");self._set_state(callback.from_user.id,"event_score",{"stage_id":int(sid),"player_id":int(uid)});await callback.message.answer("⭐ امتیاز بازیکن را ارسال کنید (عدد صحیح). ");await callback.answer()
    async def auto_group(self,callback):
        if not await self._admin(callback):return
        eid=int(str(callback.data).split(":")[-1]);stages=self.repo.event_stages(eid)
        if not stages:await callback.answer("⚠️ ابتدا مرحله ایجاد کنید.",show_alert=True);return
        self._set_state(callback.from_user.id,"event_group_count",{"stage_id":int(stages[0]["id"]),"event_id":eid});await callback.message.answer("👥 تعداد گروه‌ها را ارسال کنید (مثلاً 2 یا 3). ");await callback.answer()
    async def stage_add(self,callback):
        if not await self._admin(callback):return
        parts=str(callback.data).split(":");kind,eid=parts[2],int(parts[3]);name="مرحله مقدماتی" if kind=="preliminary" else "فینال"
        try:self.repo.create_stage(eid,name,kind)
        except Exception:await callback.answer("⚠️ این مرحله قبلاً ایجاد شده است.",show_alert=True);return
        await callback.answer("✅ مرحله اضافه شد.");await self.event_admin(callback)
    async def event_cancel(self,callback):
        if not await self._admin(callback):return
        self.repo.update_event(int(str(callback.data).split(":")[-1]),status="cancelled");await callback.answer("❌ اونت لغو شد.");await self.event_admin(callback)
    async def event_finish(self,callback):
        if not await self._admin(callback):return
        self.repo.update_event(int(str(callback.data).split(":")[-1]),status="finished");await callback.answer("🏁 اونت به پایان رسید.");await self.event_admin(callback)
    async def event_edit_name(self,callback):
        if not await self._admin(callback):return
        eid=int(str(callback.data).split(":")[-1]);self._set_state(callback.from_user.id,"event_edit_name",{"event_id":eid});await callback.message.answer("📝 نام جدید اونت را ارسال کنید.");await callback.answer()
    async def event_edit_time(self,callback):
        if not await self._admin(callback):return
        eid=int(str(callback.data).split(":")[-1]);self._set_state(callback.from_user.id,"event_edit_time",{"event_id":eid});await callback.message.answer("🗓 زمان جدید را به صورت YYYY-MM-DD HH:MM ارسال کنید یا «بدون زمان».");await callback.answer()
    async def event_replace(self,callback):
        if not await self._admin(callback):return
        eid=int(str(callback.data).split(":")[-1]);self._set_state(callback.from_user.id,"event_replace_old",{"event_id":eid});await callback.message.answer("🔄 شناسه عددی بازیکن فعلی را ارسال کنید.");await callback.answer()
    async def manual_group(self,callback):
        if not await self._admin(callback):return
        eid=int(str(callback.data).split(":")[-1]);stages=self.repo.event_stages(eid)
        if not stages:await callback.answer("⚠️ ابتدا مرحله ایجاد کنید.",show_alert=True);return
        self._set_state(callback.from_user.id,"event_manual_group",{"stage_id":int(stages[0]["id"]),"event_id":eid});await callback.message.answer("✋ شناسه بازیکن و شماره گروه را با فاصله ارسال کنید. مثال: 123456 2");await callback.answer()
    async def _message_state(self,message):
        uid=int(message.from_user.id);st=self._state(uid);state,data=st["state"],st["data"];raw=(message.text or "").strip()
        if not state:return False
        if state=="event_add_name":
            if not raw:await message.answer("❌ نام نمی‌تواند خالی باشد.");return True
            data["name"]=raw;self._set_state(uid,"event_add_time",data);await message.answer("🗓 زمان شروع را به صورت YYYY-MM-DD HH:MM ارسال کنید یا «بدون زمان».");return True
        if state=="event_add_time":
            if raw=="بدون زمان":start=None
            else:
                try:start=datetime.fromisoformat(raw.replace(" ","T")).strftime("%Y-%m-%d %H:%M:%S")
                except ValueError:await message.answer("❌ فرمت زمان نادرست است.");return True
            eid=self.repo.create_event(data["name"],start,uid);self._set_state(uid,None,{});await message.answer(f"✅ اونت «{html.escape(data['name'])}» ایجاد شد.",parse_mode="HTML");await self._send_event_admin(message,eid);return True
        if state=="event_add_player":
            try:player=int(raw)
            except ValueError:await message.answer("❌ شناسه بازیکن نامعتبر است.");return True
            if self.repo.register_event_player(int(data["event_id"]),player):self._set_state(uid,None,{});await message.answer("✅ بازیکن به اونت اضافه شد.")
            else:await message.answer("❌ اونت فعال نیست.")
            return True
        if state=="event_score":
            try:score=int(raw)
            except ValueError:await message.answer("❌ امتیاز باید عدد صحیح باشد.");return True
            self.repo.assign_score(int(data["stage_id"]),int(data["player_id"]),score);self._set_state(uid,None,{});await message.answer("✅ امتیاز ثبت/ویرایش شد.");return True
        if state=="event_group_count":
            try:count=int(raw)
            except ValueError:await message.answer("❌ تعداد گروه نامعتبر است.");return True
            self.repo.auto_group(int(data["stage_id"]),count);self._set_state(uid,None,{});await message.answer("✅ گروه‌بندی خودکار انجام شد.");return True
        if state=="event_edit_name":self.repo.update_event(int(data["event_id"]),name=raw);self._set_state(uid,None,{});await message.answer("✅ نام اونت ویرایش شد.");return True
        if state=="event_edit_time":
            if raw=="بدون زمان":start=None
            else:
                try:start=datetime.fromisoformat(raw.replace(" ","T")).strftime("%Y-%m-%d %H:%M:%S")
                except ValueError:await message.answer("❌ فرمت زمان نادرست است.");return True
            self.repo.update_event(int(data["event_id"]),starts_at=start);self._set_state(uid,None,{});await message.answer("✅ زمان اونت ویرایش شد.");return True
        if state=="event_manual_group":
            try:player,grp=(int(x) for x in raw.split())
            except Exception:await message.answer("❌ قالب صحیح: player_id group_number");return True
            self.repo.assign_group(int(data["stage_id"]),player,grp);self._set_state(uid,None,{});await message.answer("✅ گروه بازیکن ثبت شد.");return True
        if state=="event_replace_old":
            try:old=int(raw)
            except ValueError:await message.answer("❌ شناسه نامعتبر است.");return True
            data["old"]=old;self._set_state(uid,"event_replace_new",data);await message.answer("🔄 شناسه عددی بازیکن جایگزین را ارسال کنید.");return True
        if state=="event_replace_new":
            try:new=int(raw)
            except ValueError:await message.answer("❌ شناسه نامعتبر است.");return True
            self.repo.replace_player(int(data["event_id"]),int(data["old"]),new);self._set_state(uid,None,{});await message.answer("✅ بازیکن جایگزین شد.");return True
        if state in {"incident_collect","incident_edit"}:
            content=list(data.get("content") or []);content.append(raw);data["content"]=content;self._set_state(uid,state,data);kb=InlineKeyboardMarkup(row_width=2);kb.row(InlineKeyboardButton("✅ ثبت نهایی",callback_data="mfeature:incident_finalize"),InlineKeyboardButton("👁 پیش‌نمایش",callback_data="mfeature:incident_preview"));kb.row(InlineKeyboardButton("🗑 حذف آخرین",callback_data="mfeature:incident_pop"),InlineKeyboardButton("❌ لغو",callback_data="mfeature:incident_cancel"));await message.answer(f"📝 پیام شماره {len(content)} دریافت شد.",reply_markup=kb);return True
        return False
    async def _send_event_admin(self,message,eid):await message.answer(f"⚙️ مدیریت اونت #{eid}",reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("⚙️ مدیریت",callback_data=f"mfeature:event_admin:{eid}")))
    async def incidents(self,callback):
        if not await self._admin(callback):await callback.answer("⛔ دسترسی ندارید.",show_alert=True);return
        kb=InlineKeyboardMarkup(row_width=1)
        with self.repo.SessionLocal() as s:games=[dict(r) for r in s.execute(text("select id,event_number,status from public.mafia_games where status='finished' order by coalesce(finished_at,created_at) desc limit 20")).mappings().all()]
        for g in games:kb.add(InlineKeyboardButton(f"🎮 بازی {g.get('event_number') or str(g['id'])[:8]}",callback_data=f"mfeature:incident_game:{g['id']}"))
        kb.add(InlineKeyboardButton("📖 مشاهده اتفاقات",callback_data="mfeature:incident_view"));kb.add(InlineKeyboardButton("📚 تاریخچه اتفاقات",callback_data="mfeature:incident_history"));await callback.message.edit_text("📝 <b>اتفاقات بازی</b>\n\nیکی از بازی‌ها را انتخاب کنید یا تاریخچه را ببینید:",parse_mode="HTML",reply_markup=kb);await callback.answer()
    async def incident_game(self,callback):
        if not await self._admin(callback):return
        gid=str(callback.data).split(":",2)[-1];self._set_state(callback.from_user.id,"incident_collect",{"game_id":gid,"content":[],"edit":False});await callback.message.edit_text("📝 <b>ثبت اتفاقات</b>\n\nاتفاقات را در یک یا چند پیام ارسال کنید. پس از پایان، «ثبت نهایی» را بزنید.",parse_mode="HTML");await callback.answer()
    async def incident_view(self,callback):
        if not await self._admin(callback):return
        with self.repo.SessionLocal() as s:rows=s.execute(text("select i.game_id,g.event_number from public.mafia_game_incidents i join public.mafia_games g on g.id=i.game_id where i.finalized=true order by i.updated_at desc limit 20")).mappings().all()
        kb=InlineKeyboardMarkup(row_width=1)
        for r in rows:kb.add(InlineKeyboardButton(f"🎮 بازی {r['event_number'] or str(r['game_id'])[:8]}",callback_data=f"mfeature:incident_show:{r['game_id']}"))
        kb.add(InlineKeyboardButton("⬅️ اتفاقات",callback_data="mfeature:incidents"));await callback.message.edit_text("📖 <b>اتفاقات ثبت‌شده</b>",parse_mode="HTML",reply_markup=kb);await callback.answer()
    async def incident_show(self,callback):
        gid=str(callback.data).split(":",2)[-1];row=self.repo.incident(gid)
        if not row:await callback.answer("⚠️ اتفاقی ثبت نشده است.",show_alert=True);return
        text_body="📝 <b>اتفاقات بازی</b>\n\n"+"\n\n".join(f"{i+1}️⃣ {html.escape(str(x))}" for i,x in enumerate(row.get("content") or []));kb=InlineKeyboardMarkup(row_width=2)
        if await self._admin(callback):kb.row(InlineKeyboardButton("✏️ ویرایش",callback_data=f"mfeature:incident_edit:{gid}"),InlineKeyboardButton("⬅️ اتفاقات",callback_data="mfeature:incidents"))
        await callback.message.edit_text(text_body,parse_mode="HTML",reply_markup=kb);await callback.answer()
    async def incident_edit(self,callback):
        if not await self._admin(callback):return
        gid=str(callback.data).split(":",2)[-1];self._set_state(callback.from_user.id,"incident_edit",{"game_id":gid,"content":[],"edit":True});await callback.message.answer("✏️ ویرایش فعال شد. نسخه جدید اتفاقات را در یک یا چند پیام ارسال کنید؛ سپس «ثبت نهایی» را بزنید.",reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("❌ لغو",callback_data="mfeature:incident_cancel")));await callback.answer()
    async def incident_finalize(self,callback):
        st=self._state(callback.from_user.id);data=st["data"]
        if st["state"] not in {"incident_collect","incident_edit"}:await callback.answer("⚠️ پیش‌نویس فعالی وجود ندارد.",show_alert=True);return
        if not data.get("content"):await callback.answer("⚠️ حداقل یک پیام اتفاقات ارسال کنید.",show_alert=True);return
        self.repo.save_incident(str(data["game_id"]),list(data["content"]),callback.from_user.id,True,bool(data.get("edit")));self._set_state(callback.from_user.id,None,{});await callback.answer("✅ اتفاقات ثبت نهایی شد.",show_alert=True);await callback.message.answer("✅ اتفاقات بازی با موفقیت ثبت شد.")
    async def incident_preview(self,callback):
        st=self._state(callback.from_user.id);content=st["data"].get("content") or [];await callback.message.answer("👁 <b>پیش‌نمایش</b>\n\n"+"\n\n".join(f"{i+1}️⃣ {html.escape(str(x))}" for i,x in enumerate(content)),parse_mode="HTML");await callback.answer()
    async def incident_pop(self,callback):
        st=self._state(callback.from_user.id);content=list(st["data"].get("content") or []);content.pop() if content else None;data=st["data"];data["content"]=content;self._set_state(callback.from_user.id,st["state"],data);await callback.answer("🗑 آخرین پیام حذف شد.");await callback.message.answer(f"تعداد پیام‌ها: {len(content)}")
    async def incident_cancel(self,callback):self._set_state(callback.from_user.id,None,{});await callback.answer("❌ ثبت اتفاقات لغو شد.");await self.incidents(callback)
    async def incident_history(self,callback):
        if not await self._admin(callback):return
        with self.repo.SessionLocal() as s:rows=s.execute(text("select h.incident_id,h.version,h.action,h.created_at,g.event_number from public.mafia_game_incident_history h join public.mafia_game_incidents i on i.id=h.incident_id join public.mafia_games g on g.id=i.game_id order by h.created_at desc limit 30")).mappings().all()
        lines=["📚 <b>تاریخچه اتفاقات</b>",""]+[f"🎮 بازی {r['event_number'] or '—'} — نسخه {r['version']} — {r['action']} — {r['created_at']}" for r in rows];await callback.message.edit_text("\n".join(lines),parse_mode="HTML",reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("⬅️ اتفاقات",callback_data="mfeature:incidents")));await callback.answer()
    async def group_incidents(self,message):
        if message.chat.type not in {"group","supergroup"}:return
        if (message.text or "").strip().replace("‌"," ") not in {"اتفاقات بازی","/اتفاقات بازی"}:return
        with self.repo.SessionLocal() as s:row=s.execute(text("select i.content,g.event_number from public.mafia_game_incidents i join public.mafia_games g on g.id=i.game_id where g.group_chat_id=:gid and i.finalized=true order by g.finished_at desc nulls last,g.created_at desc limit 1"),{"gid":int(message.chat.id)}).mappings().first()
        if not row:await message.answer("📝 برای آخرین بازی این گروه هنوز اتفاقاتی ثبت نشده است.");raise CancelHandler()
        await message.answer(f"📝 <b>اتفاقات بازی {row['event_number'] or '—'}</b>\n\n"+"\n\n".join(f"{i+1}️⃣ {html.escape(str(x))}" for i,x in enumerate(row["content"] or [])),parse_mode="HTML");raise CancelHandler()
    def _patch_private_ui(self):
        try:
            from runtime import final_private_ui as pui
            original_start,original_mgmt=pui.start_keyboard,pui.management_keyboard
            def start_keyboard():kb=original_start();kb.add(InlineKeyboardButton("🎪 اونت‌ها",callback_data="mfeature:events"));return kb
            def management_keyboard():kb=original_mgmt();kb.add(InlineKeyboardButton("📝 اتفاقات بازی",callback_data="mfeature:incidents"));return kb
            pui.start_keyboard,pui.management_keyboard=start_keyboard,management_keyboard
        except Exception:logging.exception("feature UI patch failed")
    def _patch_display_name(self):
        try:
            from player_service import player_service
            if getattr(player_service,"_mafia_tag_display_patched",False):return
            original=player_service.display_name
            def display_name(user_id,fallback="❓"):
                base=original(user_id,fallback)
                try:
                    tag=self.repo.active_tag(int(user_id));emoji=str((tag or {}).get("emoji") or "").strip()
                    if emoji and not str(base).startswith(emoji):return f"{emoji} {base}"
                except Exception:logging.exception("active tag display failed")
                return base
            player_service.display_name=display_name;player_service._mafia_tag_display_patched=True
        except Exception:logging.exception("tag display patch failed")
    def _front(self,fn,predicate):
        reg=getattr(getattr(self.app.dp,"callback_query_handlers",None),"handlers",[]);self.app.dp.register_callback_query_handler(fn,predicate,state="*")
        for i,item in enumerate(list(reg)):
            cb=getattr(item,"callback",None) or getattr(item,"handler",None)
            if cb is fn:reg.insert(0,reg.pop(i));break
    def install(self):
        if getattr(self.app,"_mafia_progress_events_installed",False):return False
        self._patch_display_name();self._patch_private_ui()
        self._front(self.achievements,lambda c:str(c.data or "")=="profile:advanced:achievements");self._front(self.profile_override,lambda c:str(c.data or "")=="ustats:profile");self._front(self.stats_override,lambda c:str(c.data or "")=="ustats:stats");self._front(self.tags,lambda c:str(c.data or "")=="mfeature:tags");self._front(self.tag_toggle,lambda c:str(c.data or "").startswith("mfeature:tag:"))
        self._front(self.events,lambda c:str(c.data or "")=="mfeature:events");self._front(self.event_detail,lambda c:str(c.data or "").startswith("mfeature:event:") and not str(c.data).startswith("mfeature:event_"));self._front(self.event_register,lambda c:str(c.data or "").startswith("mfeature:event_register:"));self._front(self.event_players,lambda c:str(c.data or "").startswith("mfeature:event_players:"));self._front(self.event_add_player,lambda c:str(c.data or "").startswith("mfeature:event_add_player:"));self._front(self.event_remove_player,lambda c:str(c.data or "").startswith("mfeature:event_remove_player:"));self._front(self.event_remove,lambda c:str(c.data or "").startswith("mfeature:event_remove:"));self._front(self.event_admin,lambda c:str(c.data or "").startswith("mfeature:event_admin:"));self._front(self.start_add_event,lambda c:str(c.data or "")=="mfeature:event_add");self._front(self.event_scores,lambda c:str(c.data or "").startswith("mfeature:event_scores:"));self._front(self.score_stage,lambda c:str(c.data or "").startswith("mfeature:score_stage:"));self._front(self.score_player,lambda c:str(c.data or "").startswith("mfeature:score_player:"));self._front(self.auto_group,lambda c:str(c.data or "").startswith("mfeature:auto_group:"));self._front(self.stage_add,lambda c:str(c.data or "").startswith("mfeature:stage_add:"));self._front(self.manual_group,lambda c:str(c.data or "").startswith("mfeature:manual_group:"));self._front(self.event_cancel,lambda c:str(c.data or "").startswith("mfeature:event_cancel:"));self._front(self.event_finish,lambda c:str(c.data or "").startswith("mfeature:event_finish:"));self._front(self.event_edit_name,lambda c:str(c.data or "").startswith("mfeature:event_edit_name:"));self._front(self.event_edit_time,lambda c:str(c.data or "").startswith("mfeature:event_edit_time:"));self._front(self.event_replace,lambda c:str(c.data or "").startswith("mfeature:event_replace:"))
        self._front(self.incidents,lambda c:str(c.data or "")=="mfeature:incidents");self._front(self.incident_game,lambda c:str(c.data or "").startswith("mfeature:incident_game:"));self._front(self.incident_view,lambda c:str(c.data or "")=="mfeature:incident_view");self._front(self.incident_show,lambda c:str(c.data or "").startswith("mfeature:incident_show:"));self._front(self.incident_edit,lambda c:str(c.data or "").startswith("mfeature:incident_edit:"));self._front(self.incident_finalize,lambda c:str(c.data or "")=="mfeature:incident_finalize");self._front(self.incident_preview,lambda c:str(c.data or "")=="mfeature:incident_preview");self._front(self.incident_pop,lambda c:str(c.data or "")=="mfeature:incident_pop");self._front(self.incident_cancel,lambda c:str(c.data or "")=="mfeature:incident_cancel");self._front(self.incident_history,lambda c:str(c.data or "")=="mfeature:incident_history")
        mh=self.app.dp.message_handlers.handlers
        async def state_handler(message):
            if await self._message_state(message):raise CancelHandler()
        self.app.dp.register_message_handler(state_handler,lambda m:bool(m.chat and m.from_user and m.chat.type=="private"),state="*")
        for i,item in enumerate(list(mh)):
            cb=getattr(item,"callback",None) or getattr(item,"handler",None)
            if cb is state_handler:mh.insert(0,mh.pop(i));break
        self.app.dp.register_message_handler(self.group_incidents,lambda m:m.chat and m.chat.type in {"group","supergroup"} and (m.text or "").strip().replace("‌"," ") in {"اتفاقات بازی","/اتفاقات بازی"},content_types=types.ContentTypes.TEXT);self.app._mafia_progress_events_installed=True;return True

def install(app):return MafiaProgressEvents(app).install()
