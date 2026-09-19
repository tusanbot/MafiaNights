"""Friendly scenario CRUD form: dot means keep, roles and sides are entered together, settings use buttons."""
from __future__ import annotations
import html, json
from typing import Any
from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from runtime.scenario_management_v2 import ScenarioForm
from runtime.scenario_management_v3 import ScenarioManagementV3

class ScenarioFormV5(ScenarioManagementV3):
    FEATURES = {
        "allow_players_next": "⏭ نکست برای بازیکنان",
        "allow_moderator_next": "🎛 نکست برای گرداننده",
        "show_player_status": "🤏 نمایش وضعیت چالش",
    }
    DEFAULTS = {k: True for k in FEATURES}

    @staticmethod
    def keep(x: str) -> bool:
        return (x or "").strip() in {".", "-", "بدون تغییر"}

    def keep_kb(self):
        return InlineKeyboardMarkup().add(InlineKeyboardButton("• بدون تغییر", callback_data="sm5:keep"))

    async def start_edit(self, callback, state):
        if not await self._admin(callback): return
        sid = int(callback.data.rsplit(":",1)[1]) if callback.data.count(":") == 2 else None
        if sid is None:
            rows=self.repo.list_active(); kb=self._buttons([(f"✏️ {r['name']}",f"sm2:edit:{r['id']}") for r in rows]+[("⬅️ بازگشت","sm2:menu")])
            await callback.message.edit_text("سناریوی موردنظر را انتخاب کنید:",reply_markup=kb); await callback.answer(); return
        row=self.repo.get_by_id(sid)
        if not row: await callback.answer("سناریو پیدا نشد.",show_alert=True); return
        cfg=row.get("config") or {}; cfg=json.loads(cfg) if isinstance(cfg,str) else cfg
        rc=cfg.get("roles") or {}; sides=cfg.get("sides") or {}
        lines=[f"{r} {((rc.get(str(r)) or {}).get('side') or sides.get(str(r)) or 'شهروند')}" for r in (row.get("roles") or [])]
        data=dict(row); data["config"]=cfg; data["role_lines"]=lines
        self.sessions[int(callback.from_user.id)]={"mode":"edit","id":sid,"data":data}
        await callback.message.answer(f"✏️ ویرایش «{html.escape(str(row['name']))}»\n\nنام جدید را وارد کنید؛ برای حفظ مقدار فعلی «.» را بفرستید.",parse_mode="HTML",reply_markup=self.keep_kb())
        await ScenarioForm.name.set(); await callback.answer()

    async def name(self,message,state):
        uid=int(message.from_user.id); s=self.sessions.setdefault(uid,{"mode":"add"}); d=s.setdefault("data",{}); raw=(message.text or "").strip()
        if s.get("mode")=="edit" and self.keep(raw): value=str(d.get("name") or "")
        else: value=raw
        if not value or (s.get("mode")=="add" and self.keep(raw)): await message.answer("⚠️ نام معتبر نیست."); return
        d["name"]=value
        await message.answer("📖 توضیح سناریو را وارد کنید؛ در ویرایش «.» یعنی بدون تغییر.",reply_markup=self.keep_kb()); await ScenarioForm.description.set()

    async def description(self,message,state):
        uid=int(message.from_user.id); s=self.sessions[uid]; raw=(message.text or "").strip()
        if self.keep(raw) and s.get("mode")=="edit": value=s["data"].get("description")
        elif self.keep(raw): value=None
        else: value=raw
        s["data"]["description"]=value
        await message.answer("👥 حداقل تعداد بازیکنان را وارد کنید." + (" در ویرایش «.» یعنی بدون تغییر." if s.get("mode")=="edit" else ""),reply_markup=self.keep_kb()); await ScenarioForm.min_players.set()

    async def min_players(self,message,state):
        uid=int(message.from_user.id); s=self.sessions[uid]; raw=(message.text or "").strip()
        if s.get("mode")=="edit" and self.keep(raw): value=int(s["data"].get("min_players") or 1)
        elif raw.isdigit(): value=int(raw)
        else: await message.answer("⚠️ عدد وارد کنید."); return
        if value<1: await message.answer("⚠️ حداقل باید بیشتر از صفر باشد."); return
        s["data"]["min_players"]=value
        await message.answer("👥 حداکثر تعداد بازیکنان را وارد کنید." + (" در ویرایش «.» یعنی بدون تغییر." if s.get("mode")=="edit" else ""),reply_markup=self.keep_kb()); await ScenarioForm.max_players.set()

    async def max_players(self,message,state):
        uid=int(message.from_user.id); s=self.sessions[uid]; raw=(message.text or "").strip()
        if s.get("mode")=="edit" and self.keep(raw): value=int(s["data"].get("max_players") or 1)
        elif raw.isdigit(): value=int(raw)
        else: await message.answer("⚠️ عدد وارد کنید."); return
        if value<int(s["data"].get("min_players") or 1): await message.answer("⚠️ حداکثر نمی‌تواند کمتر از حداقل باشد."); return
        s["data"]["max_players"]=value
        await message.answer("🎭 نقش و ساید را همزمان وارد کنید؛ هر خط یک مورد:\n\nپدرخوانده مافیا\nدکتر شهروند\nجوکر مستقل\n\nکلمه آخر ساید است؛ بقیه متن نام نقش است. در ویرایش «.» یعنی بدون تغییر."); await ScenarioForm.roles.set()

    async def roles(self,message,state):
        uid=int(message.from_user.id); s=self.sessions[uid]; raw=(message.text or "").strip()
        if s.get("mode")=="edit" and self.keep(raw): lines=list(s["data"].get("role_lines") or [])
        else: lines=[x.strip() for x in raw.splitlines() if x.strip()]
        if not lines: await message.answer("⚠️ حداقل یک نقش لازم است."); return
        roles=[]; sides={}
        for line in lines:
            if "=" in line: role,side=line.split("=",1)
            elif ":" in line: role,side=line.split(":",1)
            else:
                p=line.rsplit(None,1)
                if len(p)!=2: await message.answer(f"⚠️ قالب درست نیست:\n{html.escape(line)}\n\nمثال: پدرخوانده مافیا"); return
                role,side=p
            role,side=role.strip(),side.strip()
            if not role or not side: await message.answer("⚠️ نقش و ساید هر دو لازم هستند."); return
            if role in sides: await message.answer(f"⚠️ نقش «{html.escape(role)}» تکراری است."); return
            roles.append(role); sides[role]=side
        s["data"]["roles"]=roles; s["data"]["sides"]=sides
        cfg=s["data"].get("config") or {}; old=cfg.get("settings") or {}; settings=dict(self.DEFAULTS)
        if isinstance(old,dict):
            for k in settings:
                if k in old: settings[k]=bool(old[k])
        s["data"]["settings"]=settings
        await self._show_settings(message,settings); await ScenarioForm.settings.set()

    def _settings_kb(self,settings):
        kb=InlineKeyboardMarkup(row_width=1)
        for k,label in self.FEATURES.items():
            kb.add(InlineKeyboardButton(f"{label}: {'🟢 فعال' if settings.get(k) else '🔴 غیرفعال'}",callback_data=f"sm5:toggle:{k}"))
        kb.add(InlineKeyboardButton("💾 ذخیره سناریو",callback_data="sm5:save"))
        return kb

    async def _show_settings(self,message,settings):
        await message.answer("⚙️ <b>تنظیمات سناریو</b>\n\nهر ویژگی را با دکمه فعال یا غیرفعال کنید؛ نیازی به JSON نیست.",parse_mode="HTML",reply_markup=self._settings_kb(settings))

    async def feature_toggle(self,callback,state):
        if not await self._admin(callback): return
        uid=int(callback.from_user.id); s=self.sessions.get(uid); key=callback.data.rsplit(":",1)[1]
        if not s or key not in self.FEATURES: await callback.answer("⚠️ فرم نامعتبر یا منقضی شده است.",show_alert=True); return
        settings=s["data"].setdefault("settings",dict(self.DEFAULTS)); settings[key]=not bool(settings.get(key,False))
        await callback.message.edit_reply_markup(reply_markup=self._settings_kb(settings)); await callback.answer()

    async def feature_save(self,callback,state):
        if not await self._admin(callback): return
        uid=int(callback.from_user.id); s=self.sessions.pop(uid,None)
        if not s: await callback.answer("⚠️ فرم منقضی شده است.",show_alert=True); return
        d=s["data"]; settings=d.get("settings",dict(self.DEFAULTS)); mode=d.get("challenge_mode","limited")
        role_cfg={r:{"side":d["sides"][r],"challenge":mode} for r in d["roles"]}
        cfg={"roles":role_cfg,"sides":d["sides"],"challenge_mode":mode,"challenge_limit":1 if mode=="limited" else None,"settings":settings}
        try:
            if s.get("mode")=="edit": sid=self.repo.update_by_id(s["id"],d["name"],d.get("description"),d["min_players"],d["max_players"],d["roles"],cfg,True)
            else: sid=self.repo.upsert(d["name"],d.get("description"),d["min_players"],d["max_players"],d["roles"],cfg,True)
            await state.finish(); row=self.repo.get_by_id(sid)
            await callback.message.edit_text("✅ سناریو ذخیره شد.\n\n"+self._summary(row),parse_mode="HTML"); await callback.answer("ذخیره شد")
        except Exception as exc:
            self.sessions[uid]=s; await callback.answer("❌ ذخیره انجام نشد.",show_alert=True); await callback.message.answer(f"❌ ذخیره سناریو انجام نشد: {html.escape(str(exc))}")

    async def challenge_mode(self,callback,state):
        if not await self._admin(callback): return
        uid=int(callback.from_user.id); s=self.sessions[uid]; mode=callback.data.rsplit(":",1)[1]
        s["data"]["challenge_mode"]=mode; s["data"]["challenge_limit"]=1 if mode=="limited" else None
        settings=s["data"].get("settings") or dict(self.DEFAULTS); s["data"]["settings"]=settings
        await self._show_settings(callback.message,settings); await ScenarioForm.settings.set(); await callback.answer()

    async def settings(self,message,state):
        await message.answer("⚙️ تنظیمات با دکمه‌ها انجام می‌شود؛ لطفاً یکی از گزینه‌های بالا را انتخاب کنید.")

    def register(self,dp):
        dp.register_callback_query_handler(self.menu,lambda c:c.data=="fp:scenarios")
        dp.register_callback_query_handler(self.menu,lambda c:c.data=="sm2:menu")
        dp.register_callback_query_handler(self.start_add,lambda c:c.data=="sm2:add")
        dp.register_callback_query_handler(self.start_edit,lambda c:c.data.startswith("sm2:edit"))
        dp.register_callback_query_handler(self.view,lambda c:c.data.startswith("sm2:view:"))
        dp.register_callback_query_handler(self.delete_menu,lambda c:c.data=="sm2:delete")
        dp.register_callback_query_handler(self.delete_confirm,lambda c:c.data.startswith("sm2:delete_confirm:"))
        dp.register_callback_query_handler(self.delete,lambda c:c.data.startswith("sm2:delete:"))
        dp.register_callback_query_handler(self.challenge_mode,lambda c:c.data.startswith("sm2:challenge:"),state=ScenarioForm.challenge_mode)
        dp.register_callback_query_handler(self.feature_toggle,lambda c:c.data.startswith("sm5:toggle:"),state=ScenarioForm.settings)
        dp.register_callback_query_handler(self.feature_save,lambda c:c.data=="sm5:save",state=ScenarioForm.settings)
        dp.register_message_handler(self.name,state=ScenarioForm.name)
        dp.register_message_handler(self.description,state=ScenarioForm.description)
        dp.register_message_handler(self.min_players,state=ScenarioForm.min_players)
        dp.register_message_handler(self.max_players,state=ScenarioForm.max_players)
        dp.register_message_handler(self.roles,state=ScenarioForm.roles)
        dp.register_message_handler(self.settings,state=ScenarioForm.settings)
