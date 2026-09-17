"""Final UX corrections for progress features."""
from __future__ import annotations

import html
import os

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from runtime.progress_features_v3 import ProgressFeaturesV3


class ProgressFeaturesV4(ProgressFeaturesV3):
    async def _is_admin_silent(self, obj):
        uid = int(obj.from_user.id)
        if uid == int(getattr(self.app, "moderator_id", 0) or 0):
            return True
        gid = (getattr(self.app, "group_chat_id", None)
               or getattr(self.app, "ALLOWED_GROUP_ID", None)
               or int(os.getenv("ALLOWED_GROUP_ID", "0") or 0))
        if not gid:
            return False
        try:
            return uid in {int(x.user.id) for x in await self.app.bot.get_chat_administrators(int(gid))}
        except Exception:
            return False

    async def events(self, c):
        events = self.repo.event_list()
        admin = await self._is_admin_silent(c)
        kb = InlineKeyboardMarkup(row_width=1)
        for e in events[:15]:
            kb.add(InlineKeyboardButton(
                f"{'🟢' if e['status']=='active' else '⚪'} {e['name']}",
                callback_data=f"progress:event:{int(e['id'])}",
            ))
        if admin:
            kb.add(InlineKeyboardButton("➕ افزودن اونت", callback_data="progress:event_add"))
        kb.add(self._back())
        body = "🎪 <b>اونت‌ها</b>\n\n" + (
            "هنوز اونتی ایجاد نشده است." if not events else
            "\n".join(f"{'🟢' if e['status']=='active' else '⚪'} {html.escape(str(e['name']))}"
                       for e in events[:15])
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
            f"🎪 <b>{html.escape(str(e['name']))}</b>", "",
            f"🗓 شروع: {html.escape(str(e.get('starts_at') or 'تعیین نشده'))}",
            f"📌 وضعیت: <b>{e['status']}</b>",
            f"👥 ثبت‌نام: <b>{sum(p.get('status') == 'registered' for p in players)}</b>", "",
        ]
        for st in stages:
            lines.append(f"📚 {html.escape(str(st['name']))} — {st['status']}")
            for p in self.repo.stage_players(st["id"]):
                lines.append(
                    f"  └ {html.escape(self._name(p))} | گروه {p.get('group_no') or '—'} | "
                    f"امتیاز {p.get('score') if p.get('score') is not None else '—'}"
                )
        admin = await self._is_admin_silent(c)
        await c.message.edit_text("\n".join(lines), parse_mode="HTML",
                                  reply_markup=self.event_detail_kb(e, admin))
        await c.answer()

    async def event_players(self, c):
        eid = int(str(c.data).split(":")[-1])
        players = self.repo.event_players(eid)
        lines = ["👥 <b>بازیکنان اونت</b>", ""]
        for i, p in enumerate(players, 1):
            lines.append(f"{i}. {html.escape(self._name(p))} — {p.get('status')}")
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


def install(app):
    return ProgressFeaturesV4(app).install()
