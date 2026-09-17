"""Small, isolated lobby UI fixes.

This module intentionally patches only lobby-management presentation and the
attendance callback. Gameplay, turns, voting and role distribution are left
untouched.
"""
from __future__ import annotations

import html
import logging
from typing import Any

from aiogram import types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from runtime.game_management import GameManagement


def install(app: Any, management: GameManagement) -> bool:
    """Install isolated lobby fixes after all existing lobby handlers load."""

    original_panel = management.panel

    def panel(game_id: int):
        # Preserve every existing management action except the two lobby UI
        # actions explicitly removed by the product requirement.
        kb = InlineKeyboardMarkup(row_width=3)
        items = [
            ("🔢 شماره بازی", "event"),
            ("📝 تغییر سناریو", "scenario"),
            ("🗑 حذف بازیکن", "remove"),
            ("🎟 لغو رزرو", "unreserve"),
            ("🔄 جایگزین بازیکن", "replace"),
            ("✅ حاضری", "attendance"),
            ("🎂 تولد بازیکن", "birthday"),
            ("⚔ وضعیت چالش", "challenge"),
            ("⏭ مدیریت نکست", "next"),
            ("🚫 لغو بازی", "cancel"),
            ("⬅️ بازگشت به لابی", "back_lobby"),
        ]
        for i in range(0, len(items), 3):
            kb.row(*(InlineKeyboardButton(t, callback_data=f"mgmt:{int(game_id)}:{a}") for t, a in items[i:i + 3]))
        return kb

    management.panel = panel
    GameManagement.panel = panel

    async def back_lobby(self: GameManagement, callback: Any):
        gid = int(callback.message.chat.id)
        game = self._game(gid)
        if not game or not await self._allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید یا بازی فعال نیست.", show_alert=True)
            return
        if str(game.get("status") or "") != "lobby":
            await callback.answer("❌ بازی در حال اجراست و لابی فعال نیست.", show_alert=True)
            return
        renderer = getattr(self.app, "_render_production_lobby", None)
        if not renderer:
            await callback.answer("❌ موتور لابی فعال نیست.", show_alert=True)
            return
        try:
            ok = bool(await renderer(gid, game))
        except Exception:
            logging.exception("back to lobby failed game=%s", game.get("id"))
            ok = False
        await callback.answer("⬅️ به لابی برگشتید." if ok else "❌ بازگشت به لابی انجام نشد.", show_alert=not ok)

    GameManagement.back_lobby = back_lobby

    async def attendance(self: GameManagement, callback: Any):
        gid = int(callback.message.chat.id)
        game = self._game(gid)
        if not game or not await self._allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
            return
        rows = [
            r for r in self._rows(game)
            if r.get("seat") is not None
            and str(r.get("status") or "active") not in {"removed", "dead", "finished"}
        ]
        if not rows:
            await callback.answer("❌ بازیکن فعالی در بازی وجود ندارد.", show_alert=True)
            return

        # Always read the latest DB-backed game snapshot before changing the
        # attendance map. This avoids editing a stale in-memory game object.
        fresh = self._game(gid) or game
        state = self._state(fresh)
        attendance = {str(k): bool(v) for k, v in dict(state.get("attendance") or {}).items()}
        active_ids = {str(int(r["player_id"])) for r in rows}
        attendance = {k: v for k, v in attendance.items() if k in active_ids}
        for uid in active_ids:
            attendance.setdefault(uid, False)
        self._save(fresh, attendance=attendance, attendance_announced=False)

        def mention(row: dict[str, Any]) -> str:
            uid = int(row["player_id"])
            label = row.get("nickname") or row.get("first_name") or row.get("username") or uid
            return f'<a href="tg://user?id={uid}"><b>{html.escape(str(label))}</b></a>'

        lines = ["🟢 <b>بازیکنان حاضر در لیست</b>", ""]
        for row in sorted(rows, key=lambda r: int(r.get("seat") or 999)):
            ready = bool(attendance.get(str(int(row["player_id"])), False))
            lines.append(f"{'🟢' if ready else '⚪️'} {int(row['seat']):02d}. {mention(row)}")
        lines.extend(["", "برای اعلام آمادگی، دکمه «آماده‌ام» را بزنید."])
        kb = InlineKeyboardMarkup(row_width=1).add(
            InlineKeyboardButton("آماده‌ام", callback_data=f"mgmt:{int(fresh['id'])}:attendance_ready")
        )
        message_id = state.get("attendance_message_id")
        try:
            if message_id:
                await self.app.bot.edit_message_text(
                    "\n".join(lines), gid, int(message_id), parse_mode="HTML", reply_markup=kb
                )
            else:
                msg = await self.app.bot.send_message(
                    gid, "\n".join(lines), parse_mode="HTML", reply_markup=kb
                )
                message_id = int(msg.message_id)
            self._save(fresh, attendance_message_id=int(message_id))
            await callback.answer("✅ لیست حاضری به‌روزرسانی شد.")
        except Exception:
            logging.exception("attendance render failed game=%s", fresh.get("id"))
            await callback.answer("❌ نمایش حاضری انجام نشد.", show_alert=True)

    async def attendance_ready(self: GameManagement, callback: Any):
        parts = str(callback.data or "").split(":")
        if len(parts) != 3 or parts[0] != "mgmt" or parts[2] != "attendance_ready":
            return
        gid = int(callback.message.chat.id)
        game = self._game(gid)
        uid = int(callback.from_user.id)
        if not game:
            await callback.answer("❌ بازی فعالی وجود ندارد.", show_alert=True)
            return

        rows = self._rows(game)
        player = next((r for r in rows if int(r["player_id"]) == uid), None)
        if (
            not player
            or player.get("seat") is None
            or str(player.get("status") or "") in {"removed", "dead", "finished"}
        ):
            await callback.answer("⛔ فقط بازیکنان حاضر در بازی می‌توانند اعلام آمادگی کنند.", show_alert=True)
            return

        # Persist against a fresh snapshot, then fetch again for rendering.
        fresh = self._game(gid) or game
        attendance = dict(self._state(fresh).get("attendance") or {})
        attendance[str(uid)] = True
        self._save(fresh, attendance=attendance)
        fresh = self._game(gid) or fresh

        message_id = dict(self._state(fresh).get("attendance_message_id") or {}) if False else self._state(fresh).get("attendance_message_id")
        if message_id:
            rows = [
                r for r in self._rows(fresh)
                if r.get("seat") is not None
                and str(r.get("status") or "active") not in {"removed", "dead", "finished"}
            ]
            active_ids = {str(int(r["player_id"])) for r in rows}
            attendance = {str(k): bool(v) for k, v in dict(self._state(fresh).get("attendance") or {}).items() if str(k) in active_ids}
            for pid in active_ids:
                attendance.setdefault(pid, False)

            def mention(row: dict[str, Any]) -> str:
                pid = int(row["player_id"])
                label = row.get("nickname") or row.get("first_name") or row.get("username") or pid
                return f'<a href="tg://user?id={pid}"><b>{html.escape(str(label))}</b></a>'

            lines = ["🟢 <b>بازیکنان حاضر در لیست</b>", ""]
            for row in sorted(rows, key=lambda r: int(r.get("seat") or 999)):
                ready = bool(attendance.get(str(int(row["player_id"])), False))
                lines.append(f"{'🟢' if ready else '⚪️'} {int(row['seat']):02d}. {mention(row)}")
            lines.extend(["", "برای اعلام آمادگی، دکمه «آماده‌ام» را بزنید."])
            kb = InlineKeyboardMarkup(row_width=1).add(
                InlineKeyboardButton("آماده‌ام", callback_data=f"mgmt:{int(fresh['id'])}:attendance_ready")
            )
            try:
                await self.app.bot.edit_message_text(
                    "\n".join(lines), gid, int(message_id), parse_mode="HTML", reply_markup=kb
                )
            except Exception:
                logging.exception("attendance ready render failed game=%s user=%s", fresh.get("id"), uid)

        players = [
            r for r in self._rows(fresh)
            if r.get("seat") is not None
            and str(r.get("status") or "active") not in {"removed", "dead", "finished"}
        ]
        if players and all(bool(attendance.get(str(int(r["player_id"])), False)) for r in players):
            state = self._state(fresh)
            if not state.get("attendance_announced"):
                self._save(fresh, attendance_announced=True)
                try:
                    await self.app.bot.send_message(gid, "🎉 <b>همه بازیکنان آماده‌اند.</b>", parse_mode="HTML")
                except Exception:
                    logging.exception("all-ready notification failed game=%s", fresh.get("id"))
        await callback.answer("✅ آمادگی شما ثبت شد.")

    GameManagement.attendance = attendance
    GameManagement.attendance_ready = attendance_ready

    # The previous attendance-ready handler was registered before this patch.
    # Remove only that exact callback family and register the patched one.
    registry = getattr(getattr(app.dp, "callback_query_handlers", None), "handlers", [])
    kept = []
    for item in registry:
        fn = getattr(item, "callback", None) or getattr(item, "handler", None)
        name = getattr(fn, "__name__", "")
        if name == "attendance_ready":
            continue
        kept.append(item)
    registry[:] = kept
    app.dp.register_callback_query_handler(
        management.attendance_ready,
        lambda c: str(c.data or "").startswith("mgmt:") and str(c.data or "").endswith(":attendance_ready"),
        state="*",
    )
    app.dp.register_callback_query_handler(
        management.back_lobby,
        lambda c: str(c.data or "").startswith("mgmt:") and str(c.data or "").endswith(":back_lobby"),
        state="*",
    )
    return True
