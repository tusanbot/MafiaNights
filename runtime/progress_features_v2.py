"""Canonical progress, achievement, tag, event and game-incident runtime.

This module is the single production owner for the new progress features.
It deliberately reuses the database repository from the original feature
module, but owns all UI routes itself.
"""
from __future__ import annotations

import html
import json
import logging
import os
from datetime import datetime

from aiogram import types
from aiogram.dispatcher.handler import CancelHandler
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import text

from repositories.rating_repository import RatingRepository
from runtime.mafia_progress_events import FeatureRepository, ACHIEVEMENTS


class ProgressFeaturesV2:
    def __init__(self, app):
        self.app = app
        self.repo = FeatureRepository()
        self.ratings = RatingRepository()
        app._achievement_engine = self.repo

    def _private(self, obj):
        return bool(getattr(getattr(obj, "message", None), "chat", None)
                    and obj.message.chat.type == "private")

    async def _admin(self, obj):
        if not self._private(obj):
            await obj.answer("⛔ این بخش فقط در گفت‌وگوی خصوصی در دسترس است.", show_alert=True)
            return False
        uid = int(obj.from_user.id)
        if uid == int(getattr(self.app, "moderator_id", 0) or 0):
            return True
        gid = (getattr(self.app, "group_chat_id", None)
               or getattr(self.app, "ALLOWED_GROUP_ID", None)
               or int(os.getenv("ALLOWED_GROUP_ID", "0") or 0))
        if not gid:
            await obj.answer("⚠️ گروه فعال پیدا نشد.", show_alert=True)
            return False
        try:
            ids = {int(x.user.id) for x in await self.app.bot.get_chat_administrators(int(gid))}
            if uid in ids:
                return True
        except Exception:
            logging.exception("progress admin check failed")
        await obj.answer("⛔ فقط گرداننده یا مدیر گروه دسترسی دارد.", show_alert=True)
        return False

    def _state(self, uid):
        with self.repo.SessionLocal() as s:
            row = s.execute(
                text("select state,data from public.mafia_fsm_state "
                     "where chat_id='private' and user_id=:uid"),
                {"uid": str(uid)},
            ).mappings().first()
        return {"state": row["state"], "data": dict(row["data"] or {})} if row else {"state": None, "data": {}}

    def _set_state(self, uid, state, data=None):
        with self.repo.SessionLocal() as s:
            s.execute(
                text("insert into public.mafia_fsm_state(chat_id,user_id,state,data) "
                     "values('private',:uid,:state,cast(:data as jsonb)) "
                     "on conflict(chat_id,user_id) do update set state=excluded.state,"
                     "data=excluded.data,updated_at=now()"),
                {"uid": str(uid), "state": state, "data": json.dumps(data or {}, ensure_ascii=False)},
            )
            s.commit()

    @staticmethod
    def _name(row):
        return str(row.get("nickname") or row.get("first_name") or row.get("username")
                   or row.get("player_id") or "بازیکن")

    @staticmethod
    def _progress(current, target):
        target = float(target or 0)
        if target <= 0:
            return "🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩 100%"
        pct = min(100, max(0, int(float(current or 0) * 100 / target)))
        full = round(pct / 10)
        return f"{'🟩' * full}{'⬜' * (10 - full)} {pct}%"

    # ---------- keyboards ----------

    def _back(self, data="progress:home"):
        return InlineKeyboardButton("⬅️ بازگشت", callback_data=data)

    def achievements_kb(self):
        kb = InlineKeyboardMarkup(row_width=1)
        kb.add(InlineKeyboardButton("🏷 تگ‌های من", callback_data="progress:tags"))
        kb.add(self._back("progress:profile"))
        return kb

    def events_kb(self, events):
        kb = InlineKeyboardMarkup(row_width=1)
        for e in events[:15]:
            kb.add(InlineKeyboardButton(
                f"{'🟢' if e['status']=='active' else '⚪'} {e['name']}",
                callback_data=f"progress:event:{int(e['id'])}",
            ))
        kb.add(InlineKeyboardButton("➕ افزودن اونت", callback_data="progress:event_add"))
        kb.add(self._back())
        return kb

    def event_detail_kb(self, e, admin=False):
        eid = int(e["id"])
        kb = InlineKeyboardMarkup(row_width=2)
        if e["status"] == "active":
            kb.row(
                InlineKeyboardButton("✅ ثبت‌نام", callback_data=f"progress:event_register:{eid}"),
                InlineKeyboardButton("👥 بازیکنان", callback_data=f"progress:event_players:{eid}"),
            )
        if admin:
            kb.row(InlineKeyboardButton("⚙️ مدیریت", callback_data=f"progress:event_admin:{eid}"))
        kb.add(InlineKeyboardButton("⬅️ اونت‌ها", callback_data="progress:events"))
        return kb

    def event_admin_kb(self, eid):
        kb = InlineKeyboardMarkup(row_width=2)
        kb.row(
            InlineKeyboardButton("📝 تغییر نام", callback_data=f"progress:event_name:{eid}"),
            InlineKeyboardButton("🗓 تغییر زمان", callback_data=f"progress:event_time:{eid}"),
        )
        kb.row(
            InlineKeyboardButton("👥 بازیکنان", callback_data=f"progress:event_players:{eid}"),
            InlineKeyboardButton("➕ مرحله مقدماتی", callback_data=f"progress:stage:preliminary:{eid}"),
        )
        kb.row(InlineKeyboardButton("🏆 مرحله فینال", callback_data=f"progress:stage:final:{eid}"))
        kb.row(
            InlineKeyboardButton("🤖 گروه‌بندی خودکار", callback_data=f"progress:auto:{eid}"),
            InlineKeyboardButton("✋ گروه‌بندی دستی", callback_data=f"progress:manual:{eid}"),
        )
        kb.row(
            InlineKeyboardButton("⭐ امتیازات", callback_data=f"progress:scores:{eid}"),
            InlineKeyboardButton("🔄 جایگزینی", callback_data=f"progress:replace:{eid}"),
        )
        kb.row(
            InlineKeyboardButton("❌ لغو اونت", callback_data=f"progress:cancel:{eid}"),
            InlineKeyboardButton("🏁 اتمام اونت", callback_data=f"progress:finish:{eid}"),
        )
        kb.add(InlineKeyboardButton("⬅️ اونت", callback_data=f"progress:event:{eid}"))
        return kb

    # ---------- achievements / tags ----------

    async def achievements(self, c):
        uid = int(c.from_user.id)
        self.repo.sync_achievements(uid)
        rows = self.repo.achievements(uid)
        lines = ["🏆 <b>دستاوردها</b>", "", f"🎁 امتیاز دستاوردها: <b>{self.repo.achievement_points(uid)}</b>", ""]
        for a in rows:
            current = min(float(a["current"]), float(a["target"]))
            lines += [
                f"{'✅' if a['unlocked'] else '🔒'} <b>{html.escape(a['name'])}</b>",
                f"   {current:g}/{float(a['target']):g} تکمیل شده",
                f"   {self._progress(a['current'], a['target'])}",
                f"   🎁 +{int(a.get('reward') or 0)} امتیاز"
                + (f" | 🏷 {a['tag_emoji']} {html.escape(a['tag_name'])}" if a.get("tag_name") else ""),
                "",
            ]
        await c.message.edit_text("\n".join(lines), parse_mode="HTML", reply_markup=self.achievements_kb())
        await c.answer()

    async def tags(self, c):
        uid = int(c.from_user.id)
        self.repo.sync_achievements(uid)
        tags = self.repo.tags(uid)
        body = "🏷 <b>تگ‌های من</b>\n\n"
        body += "هنوز تگی آزاد نشده است." if not tags else "\n".join(
            f"{'✅' if t['is_active'] else '▫️'} {html.escape(str(t['emoji']))} {html.escape(str(t['name']))}"
            for t in tags
        )
        kb = InlineKeyboardMarkup(row_width=1)
        for t in tags:
            kb.add(InlineKeyboardButton(
                ("✅ " if t["is_active"] else "▫️ ") + f"{t['emoji']} {t['name']}",
                callback_data=f"progress:tag:{int(t['id'])}",
            ))
        kb.add(self._back("progress:achievements"))
        await c.message.edit_text(body, parse_mode="HTML", reply_markup=kb)
        await c.answer()

    async def tag_toggle(self, c):
        active = self.repo.toggle_tag(c.from_user.id, int(str(c.data).split(":")[-1]))
        await c.answer("✅ تگ فعال شد." if active else "▫️ تگ غیرفعال شد.")
        await self.tags(c)

    # ---------- events ----------

    async def events(self, c):
        events = self.repo.event_list()
        await c.message.edit_text(
            "🎪 <b>اونت‌ها</b>\n\n" +
            ("هنوز اونتی ایجاد نشده است." if not events else
             "\n".join(f"{'🟢' if e['status']=='active' else '⚪'} {html.escape(str(e['name']))}"
                        for e in events[:15])),
            parse_mode="HTML",
            reply_markup=self.events_kb(events),
        )
        await c.answer()

    async def event_detail(self, c):
        eid = int(str(c.data).split(":")[-1])
        e = self.repo.event(eid)
        if not e:
            await c.answer("❌ اونت پیدا نشد.", show_alert=True)
            return
        players = self.repo.event_players(eid)
        stages = self.repo.event_stages(eid)
        lines = [
            f"🎪 <b>{html.escape(str(e['name']))}</b>",
            "",
            f"🗓 شروع: {html.escape(str(e.get('starts_at') or 'تعیین نشده'))}",
            f"📌 وضعیت: <b>{e['status']}</b>",
            f"👥 ثبت‌نام: <b>{sum(p.get('status') == 'registered' for p in players)}</b>",
            "",
        ]
        for st in stages:
            lines.append(f"📚 {html.escape(str(st['name']))} — {st['status']}")
            for p in self.repo.stage_players(st["id"]):
                lines.append(
                    f"  └ {html.escape(self._name(p))} | گروه {p.get('group_no') or '—'} | "
                    f"امتیاز {p.get('score') if p.get('score') is not None else '—'}"
                )
        admin = await self._admin(c)
        await c.message.edit_text("\n".join(lines), parse_mode="HTML",
                                  reply_markup=self.event_detail_kb(e, admin))
        await c.answer()

    async def event_register(self, c):
        eid = int(str(c.data).split(":")[-1])
        ok = self.repo.register_event_player(eid, c.from_user.id)
        await c.answer("✅ ثبت‌نام انجام شد." if ok else "❌ اونت فعال نیست.", show_alert=not ok)
        if ok:
            await self.event_detail(c)

    async def event_players(self, c):
        eid = int(str(c.data).split(":")[-1])
        players = self.repo.event_players(eid)
        lines = ["👥 <b>بازیکنان اونت</b>", ""]
        for i, p in enumerate(players, 1):
            lines.append(f"{i}. {html.escape(self._name(p))} — {p.get('status')}")
        kb = InlineKeyboardMarkup(row_width=1)
        if await self._admin(c):
            kb.add(InlineKeyboardButton("➕ افزودن بازیکن", callback_data=f"progress:addplayer:{eid}"))
            kb.add(InlineKeyboardButton("🗑 حذف بازیکن", callback_data=f"progress:removeplayer:{eid}"))
            kb.add(InlineKeyboardButton("⬅️ مدیریت اونت", callback_data=f"progress:event_admin:{eid}"))
        else:
            kb.add(InlineKeyboardButton("⬅️ اونت", callback_data=f"progress:event:{eid}"))
        await c.message.edit_text("\n".join(lines), parse_mode="HTML", reply_markup=kb)
        await c.answer()

    async def event_admin(self, c):
        if not await self._admin(c):
            return
        eid = int(str(c.data).split(":")[-1])
        e = self.repo.event(eid)
        if not e:
            await c.answer("❌ اونت پیدا نشد.", show_alert=True)
            return
        await c.message.edit_text(
            f"⚙️ <b>مدیریت اونت</b>\n\n{html.escape(str(e['name']))}",
            parse_mode="HTML",
            reply_markup=self.event_admin_kb(eid),
        )
        await c.answer()

    async def event_add(self, c):
        if not await self._admin(c):
            return
        self._set_state(c.from_user.id, "event_name", {})
        await c.message.edit_text("➕ <b>افزودن اونت</b>\n\nنام اونت را ارسال کنید.", parse_mode="HTML")
        await c.answer()

    async def event_stage(self, c):
        if not await self._admin(c):
            return
        parts = str(c.data).split(":")
        kind, eid = parts[2], int(parts[3])
        self.repo.create_stage(eid, "مرحله مقدماتی" if kind == "preliminary" else "فینال", kind)
        await c.answer("✅ مرحله اضافه شد.", show_alert=True)
        await self.event_admin(c)

    async def event_auto(self, c):
        if not await self._admin(c):
            return
        eid = int(str(c.data).split(":")[-1])
        stages = self.repo.event_stages(eid)
        if not stages:
            await c.answer("⚠️ ابتدا مرحله بسازید.", show_alert=True)
            return
        self._set_state(c.from_user.id, "event_auto_count", {"stage_id": int(stages[0]["id"]), "event_id": eid})
        await c.message.answer("🤖 تعداد گروه‌ها را ارسال کنید.")
        await c.answer()

    async def event_manual(self, c):
        if not await self._admin(c):
            return
        eid = int(str(c.data).split(":")[-1])
        stages = self.repo.event_stages(eid)
        if not stages:
            await c.answer("⚠️ ابتدا مرحله بسازید.", show_alert=True)
            return
        self._set_state(c.from_user.id, "event_manual", {"stage_id": int(stages[0]["id"]), "event_id": eid})
        await c.message.answer("✋ شناسه بازیکن و شماره گروه را با فاصله ارسال کنید. مثال: 123456 2")
        await c.answer()

    async def event_scores(self, c):
        if not await self._admin(c):
            return
        eid = int(str(c.data).split(":")[-1])
        stages = self.repo.event_stages(eid)
        kb = InlineKeyboardMarkup(row_width=1)
        for st in stages:
            kb.add(InlineKeyboardButton(str(st["name"]), callback_data=f"progress:scorestage:{int(st['id'])}"))
        kb.add(InlineKeyboardButton("⬅️ مدیریت اونت", callback_data=f"progress:event_admin:{eid}"))
        await c.message.edit_text("⭐ <b>مرحله را انتخاب کنید:</b>", parse_mode="HTML", reply_markup=kb)
        await c.answer()

    async def score_stage(self, c):
        if not await self._admin(c):
            return
        sid = int(str(c.data).split(":")[-1])
        players = self.repo.stage_players(sid)
        kb = InlineKeyboardMarkup(row_width=1)
        for p in players:
            score = p.get("score")
            kb.add(InlineKeyboardButton(
                f"{self._name(p)} — {score if score is not None else '—'}",
                callback_data=f"progress:score:{sid}:{int(p['player_id'])}",
            ))
        await c.message.edit_text("⭐ بازیکن را انتخاب کنید:", reply_markup=kb)
        await c.answer()

    async def score_player(self, c):
        if not await self._admin(c):
            return
        _, _, sid, uid = str(c.data).split(":")
        self._set_state(c.from_user.id, "event_score", {"stage_id": int(sid), "player_id": int(uid)})
        await c.message.answer("⭐ امتیاز جدید را ارسال کنید.")
        await c.answer()

    async def event_cancel(self, c):
        if not await self._admin(c): return
        eid = int(str(c.data).split(":")[-1]); self.repo.update_event(eid, status="cancelled")
        await c.answer("❌ اونت لغو شد.", show_alert=True); await self.event_admin(c)

    async def event_finish(self, c):
        if not await self._admin(c): return
        eid = int(str(c.data).split(":")[-1]); self.repo.update_event(eid, status="finished")
        await c.answer("🏁 اونت به پایان رسید.", show_alert=True); await self.event_admin(c)

    async def event_edit(self, c, field):
        if not await self._admin(c): return
        eid = int(str(c.data).split(":")[-1])
        self._set_state(c.from_user.id, "event_name" if field == "name" else "event_time",
                        {"event_id": eid, "edit": True})
        await c.message.answer("📝 نام جدید را ارسال کنید." if field == "name"
                                else "🗓 زمان را به صورت YYYY-MM-DD HH:MM ارسال کنید یا «بدون زمان».")
        await c.answer()

    async def event_replace(self, c):
        if not await self._admin(c): return
        eid = int(str(c.data).split(":")[-1])
        self._set_state(c.from_user.id, "event_old", {"event_id": eid})
        await c.message.answer("🔄 شناسه بازیکن فعلی را ارسال کنید.")
        await c.answer()

    async def event_add_player(self, c):
        if not await self._admin(c): return
        eid = int(str(c.data).split(":")[-1])
        self._set_state(c.from_user.id, "event_add_player", {"event_id": eid})
        await c.message.answer("➕ شناسه عددی بازیکن را ارسال کنید.")
        await c.answer()

    async def event_remove_player(self, c):
        if not await self._admin(c): return
        eid = int(str(c.data).split(":")[-1])
        kb = InlineKeyboardMarkup(row_width=1)
        for p in self.repo.event_players(eid):
            if p.get("status") == "registered":
                kb.add(InlineKeyboardButton(self._name(p),
                                            callback_data=f"progress:remove:{eid}:{int(p['player_id'])}"))
        kb.add(InlineKeyboardButton("⬅️ بازیکنان", callback_data=f"progress:event_players:{eid}"))
        await c.message.edit_text("🗑 بازیکن را انتخاب کنید:", reply_markup=kb)
        await c.answer()

    async def event_remove(self, c):
        if not await self._admin(c): return
        _, _, eid, uid = str(c.data).split(":")
        with self.repo.SessionLocal() as s:
            s.execute(text("update public.mafia_event_players set status='withdrawn',updated_at=now() "
                           "where event_id=:eid and player_id=:uid"), {"eid": int(eid), "uid": int(uid)})
            s.commit()
        await c.answer("🗑 بازیکن حذف شد.")
        await self.event_players(c)

    # ---------- incidents ----------

    async def incidents(self, c):
        if not await self._admin(c): return
        with self.repo.SessionLocal() as s:
            games = s.execute(
                text("select id,event_number,status from public.mafia_games "
                     "where status='finished' order by coalesce(finished_at,created_at) desc limit 30")
            ).mappings().all()
        kb = InlineKeyboardMarkup(row_width=1)
        for g in games:
            kb.add(InlineKeyboardButton(
                f"🎮 بازی {g.get('event_number') or str(g['id'])[:8]}",
                callback_data=f"progress:incident_game:{g['id']}",
            ))
        kb.add(InlineKeyboardButton("📖 مشاهده اتفاقات", callback_data="progress:incident_view"))
        kb.add(InlineKeyboardButton("📚 تاریخچه اتفاقات", callback_data="progress:incident_history"))
        kb.add(self._back("progress:management"))
        await c.message.edit_text("📝 <b>اتفاقات بازی</b>\n\nبازی را انتخاب کنید:", parse_mode="HTML", reply_markup=kb)
        await c.answer()

    async def incident_game(self, c):
        if not await self._admin(c): return
        gid = str(c.data).split(":", 2)[-1]
        self._set_state(c.from_user.id, "incident_collect", {"game_id": gid, "content": [], "edit": False})
        await c.message.edit_text("📝 <b>ثبت اتفاقات</b>\n\nاتفاقات را در یک یا چند پیام ارسال کنید. سپس «ثبت نهایی» را بزنید.",
                                  parse_mode="HTML")
        await c.answer()

    async def incident_view(self, c):
        if not await self._admin(c): return
        with self.repo.SessionLocal() as s:
            rows = s.execute(text(
                "select i.game_id,g.event_number from public.mafia_game_incidents i "
                "join public.mafia_games g on g.id=i.game_id where i.finalized=true "
                "order by i.updated_at desc limit 30"
            )).mappings().all()
        kb = InlineKeyboardMarkup(row_width=1)
        for r in rows:
            kb.add(InlineKeyboardButton(f"🎮 بازی {r['event_number'] or str(r['game_id'])[:8]}",
                                        callback_data=f"progress:incident_show:{r['game_id']}"))
        kb.add(self._back("progress:incidents"))
        await c.message.edit_text("📖 <b>اتفاقات ثبت‌شده</b>", parse_mode="HTML", reply_markup=kb)
        await c.answer()

    async def incident_show(self, c):
        gid = str(c.data).split(":", 2)[-1]
        row = self.repo.incident(gid)
        if not row:
            await c.answer("⚠️ اتفاقی ثبت نشده است.", show_alert=True); return
        body = "📝 <b>اتفاقات بازی</b>\n\n" + "\n\n".join(
            f"{i+1}️⃣ {html.escape(str(x))}" for i, x in enumerate(row.get("content") or [])
        )
        kb = InlineKeyboardMarkup(row_width=2)
        if await self._admin(c):
            kb.row(InlineKeyboardButton("✏️ ویرایش", callback_data=f"progress:incident_edit:{gid}"))
        kb.add(self._back("progress:incidents"))
        await c.message.edit_text(body, parse_mode="HTML", reply_markup=kb)
        await c.answer()

    async def incident_edit(self, c):
        if not await self._admin(c): return
        gid = str(c.data).split(":", 2)[-1]
        self._set_state(c.from_user.id, "incident_collect", {"game_id": gid, "content": [], "edit": True})
        await c.message.answer("✏️ نسخه جدید اتفاقات را در یک یا چند پیام ارسال کنید؛ سپس «ثبت نهایی» را بزنید.")
        await c.answer()

    async def incident_finalize(self, c):
        st = self._state(c.from_user.id)
        if st["state"] != "incident_collect" or not st["data"].get("content"):
            await c.answer("⚠️ پیش‌نویس فعالی وجود ندارد یا خالی است.", show_alert=True); return
        d = st["data"]
        self.repo.save_incident(str(d["game_id"]), list(d["content"]), c.from_user.id, True, bool(d.get("edit")))
        self._set_state(c.from_user.id, None, {})
        await c.answer("✅ اتفاقات ثبت نهایی شد.", show_alert=True)
        await c.message.answer("✅ اتفاقات بازی ثبت شد.")

    async def incident_preview(self, c):
        st = self._state(c.from_user.id)
        content = st["data"].get("content") or []
        await c.message.answer("👁 <b>پیش‌نمایش</b>\n\n" +
                                "\n\n".join(f"{i+1}️⃣ {html.escape(str(x))}" for i, x in enumerate(content)),
                                parse_mode="HTML")
        await c.answer()

    async def incident_pop(self, c):
        st = self._state(c.from_user.id); content = list(st["data"].get("content") or [])
        if content: content.pop()
        data = st["data"]; data["content"] = content
        self._set_state(c.from_user.id, st["state"], data)
        await c.answer("🗑 آخرین پیام حذف شد.")

    async def incident_cancel(self, c):
        self._set_state(c.from_user.id, None, {})
        await c.answer("❌ لغو شد.")
        await self.incidents(c)

    async def incident_history(self, c):
        if not await self._admin(c): return
        with self.repo.SessionLocal() as s:
            rows = s.execute(text(
                "select h.version,h.action,h.created_at,g.event_number "
                "from public.mafia_game_incident_history h "
                "join public.mafia_game_incidents i on i.id=h.incident_id "
                "join public.mafia_games g on g.id=i.game_id "
                "order by h.created_at desc limit 30"
            )).mappings().all()
        body = "📚 <b>تاریخچه اتفاقات</b>\n\n" + "\n".join(
            f"🎮 بازی {r['event_number'] or '—'} — نسخه {r['version']} — {r['action']} — {r['created_at']}"
            for r in rows
        )
        await c.message.edit_text(body, parse_mode="HTML",
                                  reply_markup=InlineKeyboardMarkup().add(self._back("progress:incidents")))
        await c.answer()

    async def group_incidents(self, m):
        if m.chat.type not in {"group", "supergroup"}:
            return
        if (m.text or "").strip().replace("‌", " ") not in {"اتفاقات بازی", "/اتفاقات بازی"}:
            return
        with self.repo.SessionLocal() as s:
            row = s.execute(text(
                "select i.content,g.event_number from public.mafia_game_incidents i "
                "join public.mafia_games g on g.id=i.game_id "
                "where g.group_chat_id=:gid and i.finalized=true "
                "order by g.finished_at desc nulls last,g.created_at desc limit 1"
            ), {"gid": int(m.chat.id)}).mappings().first()
        if not row:
            await m.answer("📝 برای آخرین بازی این گروه هنوز اتفاقاتی ثبت نشده است.")
            raise CancelHandler()
        content = row["content"] or []
        await m.answer(
            f"📝 <b>اتفاقات بازی {row['event_number'] or '—'}</b>\n\n" +
            "\n\n".join(f"{i+1}️⃣ {html.escape(str(x))}" for i, x in enumerate(content)),
            parse_mode="HTML",
        )
        raise CancelHandler()

    # ---------- message FSM ----------

    async def message_state(self, m):
        if m.chat.type != "private":
            return False
        uid = int(m.from_user.id)
        st = self._state(uid); state, data = st["state"], st["data"]
        raw = (m.text or "").strip()
        if not state:
            return False
        if state == "event_name":
            if not raw:
                await m.answer("❌ نام نمی‌تواند خالی باشد."); return True
            data["name"] = raw
            self._set_state(uid, "event_time", data)
            await m.answer("🗓 زمان شروع را به صورت YYYY-MM-DD HH:MM ارسال کنید یا «بدون زمان».")
            return True
        if state == "event_time":
            if raw == "بدون زمان": start = None
            else:
                try: start = datetime.fromisoformat(raw.replace(" ", "T")).strftime("%Y-%m-%d %H:%M:%S")
                except ValueError:
                    await m.answer("❌ فرمت زمان نادرست است."); return True
            if data.get("edit"):
                self.repo.update_event(int(data["event_id"]), starts_at=start)
            else:
                eid = self.repo.create_event(data["name"], start, uid)
            self._set_state(uid, None, {})
            await m.answer("✅ زمان/اونت ثبت شد.")
            if data.get("edit"):
                await self.event_admin(types.SimpleNamespace(data=f"progress:event_admin:{data['event_id']}",
                                                             from_user=m.from_user, message=m, answer=m.answer))
            return True
        if state == "event_add_player":
            try: player = int(raw)
            except ValueError:
                await m.answer("❌ شناسه بازیکن نامعتبر است."); return True
            ok = self.repo.register_event_player(int(data["event_id"]), player)
            self._set_state(uid, None, {})
            await m.answer("✅ بازیکن اضافه شد." if ok else "❌ اونت فعال نیست.")
            return True
        if state == "event_score":
            try: score = int(raw)
            except ValueError:
                await m.answer("❌ امتیاز باید عدد صحیح باشد."); return True
            self.repo.assign_score(int(data["stage_id"]), int(data["player_id"]), score)
            self._set_state(uid, None, {})
            await m.answer("✅ امتیاز ثبت/ویرایش شد."); return True
        if state == "event_auto_count":
            try: count = int(raw)
            except ValueError:
                await m.answer("❌ تعداد گروه نامعتبر است."); return True
            self.repo.auto_group(int(data["stage_id"]), count)
            self._set_state(uid, None, {})
            await m.answer("✅ گروه‌بندی خودکار انجام شد."); return True
        if state == "event_manual":
            try: player, group_no = (int(x) for x in raw.split())
            except Exception:
                await m.answer("❌ قالب صحیح: player_id group_number"); return True
            self.repo.assign_group(int(data["stage_id"]), player, group_no)
            self._set_state(uid, None, {})
            await m.answer("✅ گروه بازیکن ثبت شد."); return True
        if state == "event_name" and data.get("edit"):
            self.repo.update_event(int(data["event_id"]), name=raw)
            self._set_state(uid, None, {})
            await m.answer("✅ نام ویرایش شد."); return True
        if state == "event_old":
            try: old = int(raw)
            except ValueError:
                await m.answer("❌ شناسه نامعتبر است."); return True
            data["old"] = old; self._set_state(uid, "event_new", data)
            await m.answer("🔄 شناسه بازیکن جایگزین را ارسال کنید."); return True
        if state == "event_new":
            try: new = int(raw)
            except ValueError:
                await m.answer("❌ شناسه نامعتبر است."); return True
            self.repo.replace_player(int(data["event_id"]), int(data["old"]), new)
            self._set_state(uid, None, {})
            await m.answer("✅ بازیکن جایگزین شد."); return True
        if state == "incident_collect":
            content = list(data.get("content") or []); content.append(raw); data["content"] = content
            self._set_state(uid, state, data)
            kb = InlineKeyboardMarkup(row_width=2)
            kb.row(InlineKeyboardButton("✅ ثبت نهایی", callback_data="progress:incident_finalize"),
                   InlineKeyboardButton("👁 پیش‌نمایش", callback_data="progress:incident_preview"))
            kb.row(InlineKeyboardButton("🗑 حذف آخرین", callback_data="progress:incident_pop"),
                   InlineKeyboardButton("❌ لغو", callback_data="progress:incident_cancel"))
            await m.answer(f"📝 پیام شماره {len(content)} دریافت شد.", reply_markup=kb)
            return True
        return False

    # ---------- integration ----------

    def _patch_ui(self):
        try:
            from runtime import final_private_ui as pui
            original_start = pui.start_keyboard
            original_management = pui.management_keyboard

            def start_keyboard():
                kb = original_start()
                rows = getattr(kb, "inline_keyboard", [])
                if not any(getattr(b, "callback_data", "") == "progress:events" for row in rows for b in row):
                    # Insert before help/back, never below the final back button.
                    button = InlineKeyboardButton("🎪 اونت‌ها", callback_data="progress:events")
                    idx = max(0, len(rows) - 1)
                    rows.insert(idx, [button])
                return kb

            def management_keyboard():
                kb = original_management()
                rows = getattr(kb, "inline_keyboard", [])
                if not any(getattr(b, "callback_data", "") == "progress:incidents" for row in rows for b in row):
                    button = InlineKeyboardButton("📝 اتفاقات بازی", callback_data="progress:incidents")
                    idx = max(0, len(rows) - 1)
                    rows.insert(idx, [button])
                return kb

            pui.start_keyboard = start_keyboard
            pui.management_keyboard = management_keyboard
        except Exception:
            logging.exception("progress UI patch failed")

    def _patch_display_name(self):
        try:
            from player_service import player_service
            if getattr(player_service, "_mafia_tag_display_patched_v2", False):
                return
            original = player_service.display_name

            def display_name(user_id, fallback="❓"):
                base = original(user_id, fallback)
                try:
                    tag = self.repo.active_tag(int(user_id))
                    emoji = str((tag or {}).get("emoji") or "").strip()
                    if emoji and not str(base).startswith(emoji):
                        return f"{emoji} {base}"
                except Exception:
                    logging.exception("tag display failed")
                return base

            player_service.display_name = display_name
            player_service._mafia_tag_display_patched_v2 = True
        except Exception:
            logging.exception("tag display patch failed")

    def _front(self, fn, predicate):
        self.app.dp.register_callback_query_handler(fn, predicate, state="*")
        reg = self.app.dp.callback_query_handlers.handlers
        for i, item in enumerate(list(reg)):
            cb = getattr(item, "callback", None) or getattr(item, "handler", None)
            if cb is fn:
                reg.insert(0, reg.pop(i)); break

    def install(self):
        if getattr(self.app, "_progress_features_v2_installed", False):
            return False
        self._patch_ui()
        self._patch_display_name()

        # Profile/stat routes.
        self._front(self.achievements, lambda c: str(c.data or "") in {"progress:achievements", "profile:advanced:achievements"})
        self._front(self.tags, lambda c: str(c.data or "") in {"progress:tags", "mfeature:tags"})
        self._front(self.tag_toggle, lambda c: str(c.data or "").startswith(("progress:tag:", "mfeature:tag:")))

        # Events.
        self._front(self.events, lambda c: str(c.data or "") == "progress:events")
        self._front(self.event_detail, lambda c: str(c.data or "").startswith("progress:event:"))
        self._front(self.event_register, lambda c: str(c.data or "").startswith("progress:event_register:"))
        self._front(self.event_players, lambda c: str(c.data or "").startswith("progress:event_players:"))
        self._front(self.event_admin, lambda c: str(c.data or "").startswith("progress:event_admin:"))
        self._front(self.event_add, lambda c: str(c.data or "") == "progress:event_add")
        self._front(self.event_stage, lambda c: str(c.data or "").startswith("progress:stage:"))
        self._front(self.event_auto, lambda c: str(c.data or "").startswith("progress:auto:"))
        self._front(self.event_manual, lambda c: str(c.data or "").startswith("progress:manual:"))
        self._front(self.event_scores, lambda c: str(c.data or "").startswith("progress:scores:"))
        self._front(self.score_stage, lambda c: str(c.data or "").startswith("progress:scorestage:"))
        self._front(self.score_player, lambda c: str(c.data or "").startswith("progress:score:"))
        self._front(self.event_cancel, lambda c: str(c.data or "").startswith("progress:cancel:"))
        self._front(self.event_finish, lambda c: str(c.data or "").startswith("progress:finish:"))
        self._front(lambda c: self.event_edit(c, "name"), lambda c: str(c.data or "").startswith("progress:event_name:"))
        self._front(lambda c: self.event_edit(c, "time"), lambda c: str(c.data or "").startswith("progress:event_time:"))
        self._front(self.event_replace, lambda c: str(c.data or "").startswith("progress:replace:"))
        self._front(self.event_add_player, lambda c: str(c.data or "").startswith("progress:addplayer:"))
        self._front(self.event_remove_player, lambda c: str(c.data or "").startswith("progress:removeplayer:"))
        self._front(self.event_remove, lambda c: str(c.data or "").startswith("progress:remove:"))

        # Incidents.
        self._front(self.incidents, lambda c: str(c.data or "") == "progress:incidents")
        self._front(self.incident_game, lambda c: str(c.data or "").startswith("progress:incident_game:"))
        self._front(self.incident_view, lambda c: str(c.data or "") == "progress:incident_view")
        self._front(self.incident_show, lambda c: str(c.data or "").startswith("progress:incident_show:"))
        self._front(self.incident_edit, lambda c: str(c.data or "").startswith("progress:incident_edit:"))
        self._front(self.incident_finalize, lambda c: str(c.data or "") == "progress:incident_finalize")
        self._front(self.incident_preview, lambda c: str(c.data or "") == "progress:incident_preview")
        self._front(self.incident_pop, lambda c: str(c.data or "") == "progress:incident_pop")
        self._front(self.incident_cancel, lambda c: str(c.data or "") == "progress:incident_cancel")
        self._front(self.incident_history, lambda c: str(c.data or "") == "progress:incident_history")

        async def state_handler(m):
            if await self.message_state(m):
                raise CancelHandler()
        self.app.dp.register_message_handler(
            state_handler,
            lambda m: bool(m.chat and m.from_user and m.chat.type == "private"),
            state="*",
        )
        mh = self.app.dp.message_handlers.handlers
        for i, item in enumerate(list(mh)):
            cb = getattr(item, "callback", None) or getattr(item, "handler", None)
            if cb is state_handler:
                mh.insert(0, mh.pop(i)); break

        async def group_command(m):
            await self.group_incidents(m)
        self.app.dp.register_message_handler(
            group_command,
            lambda m: bool(m.chat and m.chat.type in {"group", "supergroup"} and
                           (m.text or "").strip().replace("‌", " ") in {"اتفاقات بازی", "/اتفاقات بازی"}),
            content_types=types.ContentTypes.TEXT,
        )
        # The command must beat all generic group text/FSM routes.
        gh = self.app.dp.message_handlers.handlers
        for i, item in enumerate(list(gh)):
            cb = getattr(item, "callback", None) or getattr(item, "handler", None)
            if cb is group_command:
                gh.insert(0, gh.pop(i)); break

        self.app._progress_features_v2_installed = True
        return True


def install(app):
    return ProgressFeaturesV2(app).install()
