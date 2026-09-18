"""Canonical progress/event/incident runtime surface.

This is the production owner for the progress UI. It keeps the inherited
feature repository for persistence, but owns the final UX and handler priority.
"""
from __future__ import annotations

import html
import os

from aiogram import types
from aiogram.dispatcher.handler import CancelHandler
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from runtime.progress_features_v3 import ProgressFeaturesV3


class ProgressFeaturesV4(ProgressFeaturesV3):
    async def _is_admin_silent(self, obj):
        uid = int(obj.from_user.id)
        if uid == int(getattr(self.app, "moderator_id", 0) or 0):
            return True
        gid = (
            getattr(self.app, "group_chat_id", None)
            or getattr(self.app, "ALLOWED_GROUP_ID", None)
            or int(os.getenv("ALLOWED_GROUP_ID", "0") or 0)
        )
        if not gid:
            return False
        try:
            return uid in {
                int(x.user.id)
                for x in await self.app.bot.get_chat_administrators(int(gid))
            }
        except Exception:
            return False

    def _incident_game_rows(self):
        with self.repo.SessionLocal() as s:
            active = s.execute(
                self.repo.text(
                    "select id,event_number,status from public.mafia_games "
                    "where status in ('lobby','running','paused') "
                    "order by coalesce(started_at,created_at) desc limit 1"
                )
            ).mappings().all()
            finished = s.execute(
                self.repo.text(
                    "select id,event_number,status from public.mafia_games "
                    "where status='finished' "
                    "order by coalesce(finished_at,created_at) desc limit 3"
                )
            ).mappings().all()
        return [dict(r) for r in active + finished]

    async def events(self, c):
        events = self.repo.event_list()
        admin = await self._is_admin_silent(c)
        kb = InlineKeyboardMarkup(row_width=1)
        for e in events[:15]:
            kb.add(
                InlineKeyboardButton(
                    f"{'🟢' if e['status'] == 'active' else '⚪'} {e['name']}",
                    callback_data=f"progress:event:{int(e['id'])}",
                )
            )
        if admin:
            kb.add(InlineKeyboardButton("➕ افزودن اونت", callback_data="progress:event_add"))
        kb.add(self._back())
        body = "🎪 <b>اونت‌ها</b>\n\n" + (
            "هنوز اونتی ایجاد نشده است."
            if not events
            else "\n".join(
                f"{'🟢' if e['status'] == 'active' else '⚪'} {html.escape(str(e['name']))}"
                for e in events[:15]
            )
        )
        await c.message.edit_text(body, parse_mode="HTML", reply_markup=kb)
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
            f"📌 وضعیت: <b>{html.escape(str(e['status']))}</b>",
            f"👥 ثبت‌نام: <b>{sum(p.get('status') == 'registered' for p in players)}</b>",
            "",
        ]
        for st in stages:
            lines.append(
                f"📚 {html.escape(str(st['name']))} — {html.escape(str(st['status']))}"
            )
            for p in self.repo.stage_players(st["id"]):
                lines.append(
                    f"  └ {html.escape(self._name(p))} | گروه "
                    f"{p.get('group_no') or '—'} | امتیاز "
                    f"{p.get('score') if p.get('score') is not None else '—'}"
                )
        admin = await self._is_admin_silent(c)
        await c.message.edit_text(
            "\n".join(lines),
            parse_mode="HTML",
            reply_markup=self.event_detail_kb(e, admin),
        )
        await c.answer()

    async def event_players(self, c):
        eid = int(str(c.data).split(":")[-1])
        players = self.repo.event_players(eid)
        lines = ["👥 <b>بازیکنان اونت</b>", ""]
        for i, p in enumerate(players, 1):
            lines.append(
                f"{i}. {html.escape(self._name(p))} — {html.escape(str(p.get('status') or '—'))}"
            )
        admin = await self._is_admin_silent(c)
        kb = InlineKeyboardMarkup(row_width=1)
        if admin:
            kb.add(InlineKeyboardButton("➕ افزودن بازیکن", callback_data=f"progress:addplayer:{eid}"))
            kb.add(InlineKeyboardButton("🗑 حذف بازیکن", callback_data=f"progress:removeplayer:{eid}"))
            kb.add(InlineKeyboardButton("⬅️ مدیریت اونت", callback_data=f"progress:event_admin:{eid}"))
        else:
            kb.add(InlineKeyboardButton("⬅️ اونت", callback_data=f"progress:event:{eid}"))
        await c.message.edit_text("\n".join(lines), parse_mode="HTML", reply_markup=kb)
        await c.answer()

    # ---------- incidents: compact game picker ----------

    async def incidents(self, c):
        if not await self._admin(c):
            return
        try:
            games = self._incident_game_rows()
        except Exception:
            import logging
            logging.exception("incident game list failed")
            games = []

        kb = InlineKeyboardMarkup(row_width=1)
        if games:
            for i, g in enumerate(games):
                number = g.get("event_number") or str(g["id"])[:8]
                prefix = "🟢 بازی فعال" if i == 0 and g.get("status") in {"lobby", "running", "paused"} else "🎮 بازی"
                kb.add(
                    InlineKeyboardButton(
                        f"{prefix} #{number}",
                        callback_data=f"progress:incident_game:{g['id']}",
                    )
                )
        else:
            kb.add(InlineKeyboardButton("ℹ️ بازی فعالی وجود ندارد", callback_data="progress:incident_noop"))

        kb.add(InlineKeyboardButton("🔎 جستجوی بازی", callback_data="progress:incident_search"))
        kb.add(InlineKeyboardButton("📖 مشاهده اتفاقات", callback_data="progress:incident_view"))
        kb.add(InlineKeyboardButton("📚 تاریخچه اتفاقات", callback_data="progress:incident_history"))
        kb.add(self._back("progress:management"))

        body = (
            "📝 <b>اتفاقات بازی</b>\n\n"
            "🟢 بازی فعال و حداکثر سه بازی آخر نمایش داده می‌شود.\n"
            "برای بازی‌های قدیمی‌تر از «جستجوی بازی» استفاده کنید."
        )
        await c.message.edit_text(body, parse_mode="HTML", reply_markup=kb)
        await c.answer()

    async def incident_noop(self, c):
        await c.answer("ℹ️ بازی فعالی وجود ندارد.", show_alert=True)

    async def incident_search(self, c):
        if not await self._admin(c):
            return
        self._set_state(c.from_user.id, "incident_search", {})
        await c.message.edit_text(
            "🔎 <b>جستجوی اتفاقات بازی</b>\n\n"
            "شماره بازی را ارسال کنید.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup().add(
                self._back("progress:incidents")
            ),
        )
        await c.answer()

    async def incident_game(self, c):
        if not await self._admin(c):
            return
        gid = str(c.data).split(":", 2)[-1]
        self._set_state(
            c.from_user.id,
            "incident_collect",
            {"game_id": gid, "content": [], "edit": False},
        )
        await c.message.edit_text(
            "📝 <b>ثبت اتفاقات</b>\n\n"
            "اتفاقات را در یک یا چند پیام ارسال کنید؛ سپس «ثبت نهایی» را بزنید.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(row_width=1).add(
                InlineKeyboardButton("⬅️ بازگشت", callback_data="progress:incidents")
            ),
        )
        await c.answer()

    async def incident_view(self, c):
        if not await self._admin(c):
            return
        with self.repo.SessionLocal() as s:
            rows = s.execute(
                self.repo.text(
                    "select i.game_id,g.event_number "
                    "from public.mafia_game_incidents i "
                    "join public.mafia_games g on g.id=i.game_id "
                    "where i.finalized=true "
                    "order by i.updated_at desc limit 30"
                )
            ).mappings().all()
        kb = InlineKeyboardMarkup(row_width=1)
        for r in rows:
            kb.add(
                InlineKeyboardButton(
                    f"🎮 بازی {r['event_number'] or str(r['game_id'])[:8]}",
                    callback_data=f"progress:incident_show:{r['game_id']}",
                )
            )
        kb.add(InlineKeyboardButton("⬅️ اتفاقات", callback_data="progress:incidents"))
        body = (
            "📖 <b>مشاهده اتفاقات</b>\n\n"
            + ("هنوز اتفاق ثبت‌شده‌ای وجود ندارد." if not rows else "بازی را انتخاب کنید:")
        )
        await c.message.edit_text(body, parse_mode="HTML", reply_markup=kb)
        await c.answer()

    async def incident_show(self, c):
        gid = str(c.data).split(":", 2)[-1]
        row = self.repo.incident(gid)
        if not row:
            await c.answer("⚠️ برای این بازی اتفاقی ثبت نشده است.", show_alert=True)
            return
        content = row.get("content") or []
        body = "📝 <b>اتفاقات بازی</b>\n\n" + (
            "هنوز محتوایی ثبت نشده است."
            if not content
            else "\n\n".join(
                f"{i + 1}️⃣ {html.escape(str(x))}"
                for i, x in enumerate(content)
            )
        )
        kb = InlineKeyboardMarkup(row_width=1)
        if await self._is_admin_silent(c):
            kb.add(
                InlineKeyboardButton(
                    "✏️ ویرایش",
                    callback_data=f"progress:incident_edit:{gid}",
                )
            )
        kb.add(InlineKeyboardButton("⬅️ مشاهده اتفاقات", callback_data="progress:incident_view"))
        kb.add(InlineKeyboardButton("⬅️ اتفاقات", callback_data="progress:incidents"))
        await c.message.edit_text(body, parse_mode="HTML", reply_markup=kb)
        await c.answer()

    async def incident_history(self, c):
        if not await self._admin(c):
            return
        with self.repo.SessionLocal() as s:
            rows = s.execute(
                self.repo.text(
                    "select h.version,h.action,h.created_at,g.event_number "
                    "from public.mafia_game_incident_history h "
                    "join public.mafia_game_incidents i on i.id=h.incident_id "
                    "join public.mafia_games g on g.id=i.game_id "
                    "order by h.created_at desc limit 50"
                )
            ).mappings().all()
        if not rows:
            body = "📚 <b>تاریخچه اتفاقات</b>\n\nهنوز سابقه‌ای ثبت نشده است."
        else:
            body = "📚 <b>تاریخچه اتفاقات</b>\n\n" + "\n".join(
                f"🎮 بازی {r['event_number'] or '—'} — نسخه {r['version']} — "
                f"{'ایجاد' if r['action'] == 'create' else 'ویرایش'} — {r['created_at']}"
                for r in rows
            )
        await c.message.edit_text(
            body,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup().add(
                self._back("progress:incidents")
            ),
        )
        await c.answer()

    async def incident_edit(self, c):
        if not await self._admin(c):
            return
        gid = str(c.data).split(":", 2)[-1]
        self._set_state(
            c.from_user.id,
            "incident_collect",
            {"game_id": gid, "content": [], "edit": True},
        )
        await c.message.edit_text(
            "✏️ <b>ویرایش اتفاقات</b>\n\n"
            "نسخه جدید را در یک یا چند پیام ارسال کنید؛ سپس «ثبت نهایی» را بزنید.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(row_width=1).add(
                InlineKeyboardButton("⬅️ لغو و بازگشت", callback_data="progress:incidents")
            ),
        )
        await c.answer()

    async def message_state(self, m):
        if m.chat.type == "private":
            uid = int(m.from_user.id)
            st = self._state(uid)
            if st["state"] == "incident_search":
                raw = (m.text or "").strip()
                try:
                    number = int(raw)
                except ValueError:
                    await m.answer("❌ شماره بازی باید عدد باشد.")
                    return True
                with self.repo.SessionLocal() as s:
                    row = s.execute(
                        self.repo.text(
                            "select id,event_number,status from public.mafia_games "
                            "where event_number=:number order by coalesce(finished_at,created_at) desc limit 1"
                        ),
                        {"number": number},
                    ).mappings().first()
                if not row:
                    await m.answer(f"❌ بازی شماره {number} پیدا نشد.")
                    return True
                self._set_state(uid, None, {})
                await m.answer(
                    f"🎮 <b>بازی #{number}</b>\n\n"
                    "برای ثبت/مشاهده اتفاقات بازی از گزینه زیر استفاده کنید.",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(row_width=1).add(
                        InlineKeyboardButton(
                            "📝 اتفاقات این بازی",
                            callback_data=f"progress:incident_game:{row['id']}",
                        ),
                        InlineKeyboardButton(
                            "⬅️ اتفاقات",
                            callback_data="progress:incidents",
                        ),
                    ),
                )
                return True
        return await super().message_state(m)

    def _promote(self, handler, predicate):
        dp = self.app.dp
        dp.register_callback_query_handler(handler, predicate, state="*")
        handlers = getattr(dp.callback_query_handlers, "handlers", None)
        if handlers is None:
            return
        for i, item in enumerate(list(handlers)):
            fn = getattr(item, "handler", None) or getattr(item, "callback", None)
            if fn is handler:
                handlers.insert(0, handlers.pop(i))
                break

    def _promote_group_command(self):
        async def command(m):
            await self.group_incidents(m)
        dp = self.app.dp
        dp.register_message_handler(
            command,
            lambda m: bool(
                m.chat
                and m.chat.type in {"group", "supergroup"}
                and (m.text or "").strip().replace("‌", " ")
                in {"اتفاقات بازی", "/اتفاقات بازی"}
            ),
            content_types=types.ContentTypes.TEXT,
        )
        handlers = getattr(dp.message_handlers, "handlers", None)
        if handlers is not None:
            for i, item in enumerate(list(handlers)):
                fn = getattr(item, "handler", None) or getattr(item, "callback", None)
                if fn is command:
                    handlers.insert(0, handlers.pop(i))
                    break

    def install(self):
        if getattr(self.app, "_progress_features_v4_installed", False):
            return False
        self._patch_ui()
        self._patch_display_name()

        # V2/V3 routes are registered first; V4 now explicitly owns the
        # final handlers for events and incidents and promotes them to the front.
        super().install()

        self._promote(self.events, lambda c: str(c.data or "") == "progress:events")
        self._promote(self.event_detail, lambda c: str(c.data or "").startswith("progress:event:"))
        self._promote(self.event_players, lambda c: str(c.data or "").startswith("progress:event_players:"))

        self._promote(self.incidents, lambda c: str(c.data or "") == "progress:incidents")
        self._promote(self.incident_noop, lambda c: str(c.data or "") == "progress:incident_noop")
        self._promote(self.incident_search, lambda c: str(c.data or "") == "progress:incident_search")
        self._promote(self.incident_game, lambda c: str(c.data or "").startswith("progress:incident_game:"))
        self._promote(self.incident_view, lambda c: str(c.data or "") == "progress:incident_view")
        self._promote(self.incident_show, lambda c: str(c.data or "").startswith("progress:incident_show:"))
        self._promote(self.incident_edit, lambda c: str(c.data or "").startswith("progress:incident_edit:"))
        self._promote(self.incident_history, lambda c: str(c.data or "") == "progress:incident_history")
        self._promote(self.incident_finalize, lambda c: str(c.data or "") == "progress:incident_finalize")
        self._promote(self.incident_preview, lambda c: str(c.data or "") == "progress:incident_preview")
        self._promote(self.incident_pop, lambda c: str(c.data or "") == "progress:incident_pop")
        self._promote(self.incident_cancel, lambda c: str(c.data or "") == "progress:incident_cancel")
        self._promote_group_command()

        # V4 is the canonical runtime instance retained by player_runtime_entry.
        self.app._progress_features_v4_installed = True
        return True


def install(app):
    instance = ProgressFeaturesV4(app)
    app._progress_features_runtime = instance
    instance.install()
    return instance
