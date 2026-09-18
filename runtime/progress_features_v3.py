"""Final progress feature runtime.

Fixes event edit state handling while inheriting the canonical V2 UI/runtime.
"""
from __future__ import annotations

from runtime.progress_features_v2 import ProgressFeaturesV2


class ProgressFeaturesV3(ProgressFeaturesV2):
    async def event_edit(self, c, field):
        if not await self._admin(c):
            return
        eid = int(str(c.data).split(":")[-1])
        state = "event_edit_name" if field == "name" else "event_edit_time"
        self._set_state(c.from_user.id, state, {"event_id": eid})
        await c.message.answer(
            "📝 نام جدید را ارسال کنید." if field == "name"
            else "🗓 زمان را به صورت YYYY-MM-DD HH:MM ارسال کنید یا «بدون زمان».",
            reply_markup=InlineKeyboardMarkup().add(self._back(f"progress:form_cancel:edit_{field}:{eid}"))
        )
        await c.answer()

    async def message_state(self, m):
        if m.chat.type != "private":
            return False
        uid = int(m.from_user.id)
        st = self._state(uid)
        state, data = st["state"], st["data"]
        raw = (m.text or "").strip()

        if state == "event_edit_name":
            if not raw:
                await m.answer("❌ نام نمی‌تواند خالی باشد.")
                return True
            self.repo.update_event(int(data["event_id"]), name=raw)
            self._set_state(uid, None, {})
            await m.answer("✅ نام اونت ویرایش شد.")
            return True

        if state == "event_edit_time":
            if raw == "بدون زمان":
                start = None
            else:
                try:
                    from datetime import datetime
                    start = datetime.fromisoformat(raw.replace(" ", "T")).strftime("%Y-%m-%d %H:%M:%S")
                except ValueError:
                    await m.answer("❌ فرمت زمان نادرست است.")
                    return True
            self.repo.update_event(int(data["event_id"]), starts_at=start)
            self._set_state(uid, None, {})
            await m.answer("✅ زمان اونت ویرایش شد.")
            return True

        return await super().message_state(m)


def install(app):
    return ProgressFeaturesV3(app).install()
