"""Central game-management panel shared by lobby and live games."""
from __future__ import annotations

import html
import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from repositories.scenario_repository import ScenarioRepository


class ManagementState(StatesGroup):
    waiting_event_number = State()


class GameManagement:
    def __init__(self, app: Any):
        self.app = app
        self.scenarios = ScenarioRepository()

    def _game(self, gid: int):
        return self.app.runtime.state.active_game(int(gid))

    def _state(self, game: dict[str, Any]) -> dict[str, Any]:
        return dict(game.get("state") or {})

    def _save(self, game: dict[str, Any], **changes: Any) -> bool:
        state = self._state(game)
        state.update(changes)
        game["state"] = state
        return bool(self.app.runtime.state.games.update_game(game["id"], state=state))

    async def _allowed(self, obj: Any, gid: int, game=None) -> bool:
        game = game or self._game(gid)
        if not game:
            return False
        uid = int(obj.from_user.id)
        if uid == int(game.get("moderator_id") or 0):
            return True
        try:
            return (await self.app.bot.get_chat_member(gid, uid)).status in {"creator", "administrator"}
        except Exception:
            return False

    @staticmethod
    def _name(row):
        return str(row.get("nickname") or row.get("first_name") or row.get("username") or row.get("player_id") or "👤")

    @staticmethod
    def _mention(row):
        uid = int(row.get("player_id") or row.get("user_id") or 0)
        name = GameManagement._name(row)
        return f'<a href="tg://user?id={uid}"><b>{html.escape(name)}</b></a>'

    @staticmethod
    def _parts(callback, action, size):
        p = str(callback.data or "").split(":")
        return p if len(p) == size and p[0] == "mgmt" and p[2] == action else None

    def panel(self, game_id):
        kb = InlineKeyboardMarkup(row_width=3)
        items = [
            ("🔢 شماره بازی", "event"), ("📝 تغییر سناریو", "scenario"), ("🗑 حذف بازیکن", "remove"),
            ("🎟 لغو رزرو", "unreserve"), ("🔄 جایگزین بازیکن", "replace"), ("✅ حاضری", "attendance"),
            ("🎂 تولد بازیکن", "birthday"), ("⚔ وضعیت چالش", "challenge"), ("⏭ مدیریت نکست", "next"),
            ("🚫 لغو بازی", "cancel"), ("⬅️ بازگشت به لابی", "back_lobby"),
        ]
        for i in range(0, len(items), 3):
            kb.row(*(InlineKeyboardButton(t, callback_data=f"mgmt:{game_id}:{a}") for t, a in items[i:i + 3]))
        return kb

    async def open(self, callback):
        gid = int(callback.message.chat.id)
        game = self._game(gid)
        if not game or not await self._allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید یا بازی فعال نیست.", show_alert=True)
            return
        await callback.message.edit_text(
            f"⚙️ <b>مدیریت بازی</b>\n\n🔢 شماره: {int(game.get('event_number') or 1)}\n"
            f"📌 وضعیت: {html.escape(str(game.get('status') or 'lobby'))}\n\n"
            "این پنل در لابی و حین بازی قابل استفاده است.",
            parse_mode="HTML", reply_markup=self.panel(int(game["id"])),
        )
        await callback.answer()

    async def event(self, callback):
        gid = int(callback.message.chat.id)
        game = self._game(gid)
        if not game or not await self._allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
            return
        n = int(game.get("event_number") or 1)
        i = int(game["id"])
        kb = InlineKeyboardMarkup(row_width=3)
        kb.row(
            InlineKeyboardButton("−100", callback_data=f"mgmt:{i}:event_delta:-100"),
            InlineKeyboardButton("−10", callback_data=f"mgmt:{i}:event_delta:-10"),
            InlineKeyboardButton("−1", callback_data=f"mgmt:{i}:event_delta:-1"),
        )
        kb.row(
            InlineKeyboardButton(f"🔢 {n}", callback_data=f"mgmt:{i}:noop"),
            InlineKeyboardButton("+1", callback_data=f"mgmt:{i}:event_delta:1"),
            InlineKeyboardButton("+10", callback_data=f"mgmt:{i}:event_delta:10"),
        )
        kb.row(
            InlineKeyboardButton("+100", callback_data=f"mgmt:{i}:event_delta:100"),
            InlineKeyboardButton("✍️ ورود دستی", callback_data=f"mgmt:{i}:event_input"),
            InlineKeyboardButton("⬅️ مدیریت", callback_data=f"mgmt:{i}:open"),
        )
        await callback.message.edit_text(
            "🔢 <b>تغییر شماره بازی</b>\n\nعدد را مستقیم وارد کنید یا با ±1، ±10 و ±100 تغییر دهید.",
            parse_mode="HTML", reply_markup=kb,
        )
        await callback.answer()

    async def event_delta(self, callback):
        p = self._parts(callback, "event_delta", 4)
        if not p:
            return
        gid = int(callback.message.chat.id)
        game = self._game(gid)
        if not game or not await self._allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
            return
        n = max(1, int(game.get("event_number") or 1) + int(p[3]))
        self.app.runtime.state.games.update_game(game["id"], event_number=n)
        await callback.answer(f"🔢 {n}")
        await self.event(callback)

    async def event_input(self, callback, state: FSMContext):
        gid = int(callback.message.chat.id)
        game = self._game(gid)
        if not game or not await self._allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
            return
        await state.update_data(game_id=int(game["id"]), group_id=gid, message_id=int(callback.message.message_id))
        await state.set_state(ManagementState.waiting_event_number)
        await callback.message.edit_text("✍️ <b>شماره بازی جدید</b>\n\nیک عدد مثبت وارد کنید:", parse_mode="HTML")
        await callback.answer()

    async def event_input_value(self, message, state: FSMContext):
        d = await state.get_data()
        gid = int(d.get("group_id") or message.chat.id)
        game = self._game(gid)
        if not game or not await self._allowed(message, gid, game):
            await state.finish()
            await message.reply("⛔ دسترسی ندارید.")
            return
        raw = (message.text or "").strip().replace("٬", "").replace(",", "")
        if not raw.isdigit() or int(raw) < 1:
            await message.reply("❌ فقط یک عدد مثبت وارد کنید.")
            return
        n = int(raw)
        self.app.runtime.state.games.update_game(game["id"], event_number=n)
        await state.finish()
        # Restore the management message instead of leaving the admin in a dead-end FSM screen.
        try:
            target = types.Message(message_id=int(d.get("message_id") or 0), chat=message.chat, from_user=message.from_user)
        except Exception:
            target = None
        if target and target.message_id:
            try:
                await self.app.bot.edit_message_text(
                    f"⚙️ <b>مدیریت بازی</b>\n\n🔢 شماره: {n}\n📌 وضعیت: {html.escape(str(game.get('status') or 'lobby'))}\n\n"
                    "این پنل در لابی و حین بازی قابل استفاده است.",
                    gid, target.message_id, parse_mode="HTML", reply_markup=self.panel(int(game["id"])),
                )
                await message.delete()
                return
            except Exception:
                pass
        await message.reply(f"✅ شماره بازی روی <b>{n}</b> تنظیم شد.", parse_mode="HTML", reply_markup=self.panel(int(game["id"])))

    async def scenario(self, callback):
        gid = int(callback.message.chat.id); game = self._game(gid)
        if not game or not await self._allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        kb = InlineKeyboardMarkup(row_width=2)
        for r in self.scenarios.list_active():
            kb.insert(InlineKeyboardButton(f"📝 {r.get('name')} ({len(r.get('roles') or [])})", callback_data=f"mgmt:{game['id']}:scenario_pick:{int(r['id'])}"))
        kb.row(InlineKeyboardButton("⬅️ مدیریت", callback_data=f"mgmt:{game['id']}:open"))
        await callback.message.edit_text("📝 <b>تغییر سناریو</b>\n\nبا تغییر سناریو، انتخاب گرداننده الزامی است.", parse_mode="HTML", reply_markup=kb)
        await callback.answer()

    async def scenario_pick(self, callback):
        p = self._parts(callback, "scenario_pick", 4)
        if not p: return
        gid = int(callback.message.chat.id); game = self._game(gid); sid = int(p[3])
        if not game or not await self._allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        row = self.scenarios.get_by_id(sid)
        if not row or not row.get("is_active", True):
            await callback.answer("❌ سناریو معتبر نیست.", show_alert=True); return
        self.app.runtime.state.games.update_game(game["id"], scenario_id=sid, moderator_id=None)
        kb = InlineKeyboardMarkup(row_width=2)
        for a in await self.app.bot.get_chat_administrators(gid):
            kb.insert(InlineKeyboardButton(a.user.full_name, callback_data=f"mgmt:{game['id']}:moderator_pick:{int(a.user.id)}"))
        await callback.message.edit_text("🎩 <b>انتخاب گرداننده</b>\n\nتغییر سناریو بدون تعیین گرداننده کامل نمی‌شود:", parse_mode="HTML", reply_markup=kb)
        await callback.answer("سناریو ثبت شد؛ گرداننده را انتخاب کنید.")

    async def moderator_pick(self, callback):
        p = self._parts(callback, "moderator_pick", 4)
        if not p: return
        gid = int(callback.message.chat.id); game = self._game(gid); uid = int(p[3])
        if not game or not await self._allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        if uid not in {int(a.user.id) for a in await self.app.bot.get_chat_administrators(gid)}:
            await callback.answer("❌ کاربر مدیر گروه نیست.", show_alert=True); return
        self.app.runtime.state.games.update_game(game["id"], moderator_id=uid)
        await callback.message.edit_text("✅ <b>سناریو و گرداننده ثبت شدند.</b>", parse_mode="HTML", reply_markup=self.panel(int(game["id"])))
        await callback.answer()

    def _rows(self, game):
        return self.app.runtime.state.games.list_players(game["id"])

    async def _pick(self, callback, action, title, rows):
        gid = int(callback.message.chat.id); game = self._game(gid)
        if not game or not await self._allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        kb = InlineKeyboardMarkup(row_width=2)
        for r in rows:
            uid = int(r["player_id"]); seat = r.get("seat")
            label = f"{seat}. {self._name(r)}" if seat is not None else self._name(r)
            kb.insert(InlineKeyboardButton(label, callback_data=f"mgmt:{game['id']}:{action}:{uid}"))
        kb.row(InlineKeyboardButton("⬅️ مدیریت", callback_data=f"mgmt:{game['id']}:open"))
        await callback.message.edit_text(title, parse_mode="HTML", reply_markup=kb)
        await callback.answer()

    async def remove(self, callback):
        gid = int(callback.message.chat.id); game = self._game(gid)
        rows = [] if not game else [r for r in self._rows(game) if r.get("seat") is not None and str(r.get("status") or "") not in {"removed", "dead"}]
        await self._pick(callback, "remove_pick", "🗑 <b>حذف بازیکن</b>", rows)

    async def remove_pick(self, callback):
        p = self._parts(callback, "remove_pick", 4)
        if not p: return
        gid = int(callback.message.chat.id); game = self._game(gid); uid = int(p[3])
        if not game or not await self._allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        row = next((r for r in self._rows(game) if int(r["player_id"]) == uid), None)
        if not row:
            await callback.answer("❌ بازیکن پیدا نشد.", show_alert=True); return
        seat = row.get("seat")
        state = self._state(game)
        return_seats = dict(state.get("birthday_return_seats") or {})
        if seat is not None:
            return_seats[str(uid)] = int(seat)
            self._save(game, birthday_return_seats=return_seats)
        self.app.runtime.state.games.set_player_seat(game["id"], uid, None)
        self.app.runtime.state.games.set_player_status(game["id"], uid, "removed")
        if seat is not None and str(game.get("status")) == "lobby":
            # Pre-start removal is a lobby operation, not a death. It must not
            # leave a resurrection marker.
            state = self._state(game)
            rs = dict(state.get("birthday_return_seats") or {})
            rs.pop(str(uid), None)
            self._save(game, birthday_return_seats=rs)
            try: self.app.runtime.lobby.promote_waiting(game["id"], int(seat))
            except Exception: pass
        await callback.message.edit_text(f"✅ {html.escape(self._name(row))} از بازی حذف شد.", parse_mode="HTML", reply_markup=self.panel(game["id"]))
        await callback.answer()

    async def unreserve(self, callback):
        gid = int(callback.message.chat.id); game = self._game(gid)
        rows = [] if not game else [r for r in self._rows(game) if r.get("seat") is None and str(r.get("status") or "") == "waiting"]
        await self._pick(callback, "unreserve_pick", "🎟 <b>لغو رزرو</b>", rows)

    async def unreserve_pick(self, callback):
        p = self._parts(callback, "unreserve_pick", 4)
        if not p: return
        gid = int(callback.message.chat.id); game = self._game(gid); uid = int(p[3])
        if not game or not await self._allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        self.app.runtime.state.games.remove_player(game["id"], uid)
        await callback.message.edit_text("✅ رزرو بازیکن لغو شد.", reply_markup=self.panel(game["id"]))
        await callback.answer()

    async def replace(self, callback):
        gid = int(callback.message.chat.id); game = self._game(gid)
        rows = [] if not game else [r for r in self._rows(game) if r.get("seat") is None and str(r.get("status") or "") == "waiting"]
        await self._pick(callback, "replace_sub", "🔄 <b>جایگزین بازیکن</b>\n\nابتدا جایگزین را انتخاب کنید:", rows)

    async def replace_sub(self, callback):
        p = self._parts(callback, "replace_sub", 4)
        if not p: return
        gid = int(callback.message.chat.id); game = self._game(gid)
        if not game or not await self._allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        rows = [r for r in self._rows(game) if r.get("seat") is not None and str(r.get("status") or "") not in {"removed"}]
        kb = InlineKeyboardMarkup(row_width=2)
        for r in rows:
            kb.insert(InlineKeyboardButton(f"{r.get('seat')}. {self._name(r)}", callback_data=f"mgmt:{game['id']}:replace_target:{p[3]}:{int(r['player_id'])}"))
        kb.row(InlineKeyboardButton("⬅️ مدیریت", callback_data=f"mgmt:{game['id']}:open"))
        await callback.message.edit_text("👤 <b>بازیکن مقصد</b>", reply_markup=kb)
        await callback.answer()

    async def replace_target(self, callback):
        p = str(callback.data or "").split(":")
        if len(p) != 5 or p[0] != "mgmt" or p[2] != "replace_target": return
        gid = int(callback.message.chat.id); game = self._game(gid); sub = int(p[3]); old = int(p[4])
        if not game or not await self._allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        rows = self._rows(game)
        a = next((r for r in rows if int(r["player_id"]) == old), None)
        b = next((r for r in rows if int(r["player_id"]) == sub), None)
        if not a or not b or a.get("seat") is None or b.get("seat") is not None:
            await callback.answer("❌ اطلاعات جایگزینی نامعتبر است.", show_alert=True); return
        seat = int(a["seat"])
        try:
            self.app.runtime.state.games.set_player_seat(game["id"], old, None)
            self.app.runtime.state.games.set_player_status(game["id"], old, "removed")
            self.app.runtime.state.games.set_player_seat(game["id"], sub, seat)
            self.app.runtime.state.games.set_player_status(game["id"], sub, "active")
        except Exception:
            logging.exception("replace failed")
            await callback.answer("❌ جایگزینی انجام نشد.", show_alert=True); return
        await callback.message.edit_text(f"✅ {html.escape(self._name(a))} با {html.escape(self._name(b))} جایگزین شد.\n💺 صندلی {seat}", parse_mode="HTML", reply_markup=self.panel(game["id"]))
        await callback.answer()

    async def _render_attendance_message(self, callback, game):
        """Render readiness in a separate message; never replace the lobby."""
        rows = [
            r for r in self._rows(game)
            if r.get("seat") is not None
            and str(r.get("status") or "active") not in {"removed", "dead", "finished", "kicked"}
        ]
        rows.sort(key=lambda r: int(r.get("seat") or 999))
        state = self._state(game)
        ready = {int(x) for x in (state.get("ready_players") or [])}
        lines = ["📢 <b>حاضری بازیکنان</b>", ""]
        for row in rows:
            uid = int(row["player_id"])
            marker = "🟢" if uid in ready else "⚪"
            lines.append(f"{int(row['seat']):02d}. {marker} {self._mention(row)}")
        lines.append("")
        all_ready = bool(rows) and all(int(r["player_id"]) in ready for r in rows)
        if all_ready:
            lines.append("✅ <b>همه آماده‌ان؛ نقش‌ها را پخش کن.</b>")
            button_text = "✖️ بستن پیام"
            button_data = f"mgmt:{int(game['id'])}:attendance_close"
        else:
            lines.append("⏳ بازیکنان حاضر، روی «آماده‌ام» بزنند.")
            button_text = "🙋‍♂️ آماده‌ام"
            button_data = f"mgmt:{int(game['id'])}:attendance_ready"
        kb = InlineKeyboardMarkup(row_width=1).add(
            InlineKeyboardButton(button_text, callback_data=button_data)
        )
        message_id = state.get("attendance_message_id")
        try:
            if message_id:
                await self.app.bot.edit_message_text(
                    "\n".join(lines), int(game["group_chat_id"]), int(message_id),
                    parse_mode="HTML", reply_markup=kb
                )
                return
        except Exception:
            logging.info("attendance message edit failed game=%s", game.get("id"))
        msg = await self.app.bot.send_message(
            int(game["group_chat_id"]), "\n".join(lines),
            parse_mode="HTML", reply_markup=kb
        )
        self._save(game, attendance_message_id=int(msg.message_id))

    async def attendance(self, callback):
        gid = int(callback.message.chat.id); game = self._game(gid)
        if not game or not await self._allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        await self._render_attendance_message(callback, game)
        await callback.answer("📢 پیام حاضری ارسال شد.")

    async def attendance_ready(self, callback):
        p = self._parts(callback, "attendance_ready", 3)
        if not p:
            return
        gid = int(callback.message.chat.id); game = self._game(gid)
        if not game:
            await callback.answer("❌ بازی فعال نیست.", show_alert=True); return
        uid = int(callback.from_user.id)
        if not any(int(r.get("player_id") or 0) == uid and r.get("seat") is not None for r in self._rows(game)):
            await callback.answer("⛔ فقط بازیکنان حاضر می‌توانند آماده شوند.", show_alert=True); return
        state = self._state(game)
        ready = {int(x) for x in (state.get("ready_players") or [])}
        ready.add(uid)
        self._save(game, ready_players=sorted(ready))
        game = self._game(gid) or game
        await self._render_attendance_message(callback, game)
        await callback.answer("✅ آماده‌ام ثبت شد.")

    async def attendance_close(self, callback):
        p = self._parts(callback, "attendance_close", 3)
        if not p:
            return
        gid = int(callback.message.chat.id); game = self._game(gid)
        if not game or not await self._allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        try:
            await callback.message.delete()
        except Exception:
            pass
        state = self._state(game)
        state.pop("attendance_message_id", None)
        self._save(game, **{"attendance_message_id": None})
        await callback.answer("✖️ پیام حاضری بسته شد.")

    async def birthday(self, callback):
        gid = int(callback.message.chat.id); game = self._game(gid)
        # «تولد» is a gameplay action, never a lobby action. A player removed
        # before the game started must not become eligible for revival.
        started = bool(game and (game.get("started_at") or str(game.get("status") or "") in {"running", "paused"}))
        rows = [] if not started else [
            r for r in self._rows(game)
            if str(r.get("status") or "") == "dead" or (
                str(r.get("status") or "") == "removed"
                and bool((self._state(game).get("birthday_return_seats") or {}).get(str(int(r.get("player_id") or 0))))
            ) or not bool(r.get("is_alive", True))
        ]
        await self._pick(callback, "birthday_pick", "🎂 <b>تولد بازیکن</b>\n\nبازیکن مرده/حذف‌شده بازی را انتخاب کنید:", rows)

    async def birthday_pick(self, callback):
        p = self._parts(callback, "birthday_pick", 4)
        if not p: return
        gid = int(callback.message.chat.id); game = self._game(gid); uid = int(p[3])
        if not game or not await self._allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        row = next((r for r in self._rows(game) if int(r.get("player_id") or 0) == uid), None)
        if not row:
            await callback.answer("❌ بازیکن پیدا نشد.", show_alert=True)
            return
        state = self._state(game)
        return_seats = dict(state.get("birthday_return_seats") or {})
        target_seat = row.get("seat")
        if target_seat is None:
            target_seat = return_seats.get(str(uid))
        if target_seat is not None:
            occupied = {
                int(r.get("seat")) for r in self._rows(game)
                if r.get("seat") is not None and int(r.get("player_id") or 0) != uid
                and str(r.get("status") or "active") not in {"removed", "dead", "finished", "kicked"}
            }
            if int(target_seat) in occupied:
                target_seat = None
        if target_seat is None:
            await callback.answer("⚠️ صندلی قبلی آزاد نیست؛ ابتدا یک صندلی آزاد برای بازگشت فراهم کنید.", show_alert=True)
            return
        self.app.runtime.state.games.set_player_seat(game["id"], uid, int(target_seat))
        self.app.runtime.state.games.set_player_status(game["id"], uid, "active")
        alive = getattr(self.app.runtime.state.games, "set_player_alive", None)
        if alive: alive(game["id"], uid, True)
        return_seats.pop(str(uid), None)
        self._save(game, birthday_return_seats=return_seats)
        await callback.message.edit_text(f"🎂 <b>بازیکن بازگردانده شد.</b>\n\n💺 صندلی: <b>{int(target_seat):02d}</b>", parse_mode="HTML", reply_markup=self.panel(game["id"]))
        await callback.answer()

    async def challenge(self, callback):
        gid = int(callback.message.chat.id); game = self._game(gid)
        parts = str(callback.data or "").split(":")
        context = parts[3] if len(parts) >= 4 else "management"
        if not game or not await self._allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        rows = self.app.runtime.state.challenges.list_challenges(game["id"])
        state = self._state(game); settings = dict(state.get("challenge_settings") or {})
        enabled = bool(settings.get("enabled", getattr(self.app, "challenge_enabled", {}).get(gid, True)))
        show = bool(settings.get("show_player_status", True))
        pending = sum(1 for r in rows if str(r.get("status")) == "pending")
        active = sum(1 for r in rows if str(r.get("status")) in {"accepted", "active"})
        executed = sum(1 for r in rows if str(r.get("status")) == "executed")
        kb = InlineKeyboardMarkup(row_width=2)
        kb.row(
            InlineKeyboardButton("🟢 چالش: روشن" if enabled else "🔴 چالش: خاموش", callback_data=f"mgmt:{game['id']}:challenge_toggle"),
            InlineKeyboardButton("🤏 نمایش وضعیت: روشن" if show else "🚫 نمایش وضعیت: خاموش", callback_data=f"mgmt:{game['id']}:challenge_visibility_toggle"),
        )
        kb.row(
            InlineKeyboardButton(f"⏳ در انتظار: {pending}", callback_data=f"mgmt:{game['id']}:noop"),
            InlineKeyboardButton(f"🤏 اجراشده: {executed}", callback_data=f"mgmt:{game['id']}:noop"),
        )
        back_data = f"mgmt:{game['id']}:challenge_back:start" if context == "start" else (f"mgmt:{game['id']}:challenge_back:round" if context == "round" else f"mgmt:{game['id']}:open")
        back_text = "⬅️ شروع بازی" if context == "start" else ("⬅️ منوی دور" if context == "round" else "⬅️ مدیریت بازی")
        kb.row(InlineKeyboardButton(back_text, callback_data=back_data))
        await callback.message.edit_text(f"⚔ <b>مدیریت چالش</b>\n\n🟢 سرویس: {'فعال' if enabled else 'خاموش'}\n⏳ در انتظار: {pending}\n⚡ فعال: {active}\n🤏 اجراشده: {executed}\n📦 کل: {len(rows)}\n\n🤏 نمایش وضعیت کنار نام بازیکنان: {'فعال' if show else 'غیرفعال'}", parse_mode="HTML", reply_markup=kb)
        await callback.answer()

    async def challenge_toggle(self, callback):
        gid = int(callback.message.chat.id); game = self._game(gid)
        if not game or not await self._allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        if not hasattr(self.app, "challenge_enabled"): self.app.challenge_enabled = {}
        enabled = not bool(self.app.challenge_enabled.get(gid, True))
        self.app.challenge_enabled[gid] = enabled
        state = self._state(game); settings = dict(state.get("challenge_settings") or {})
        settings["enabled"] = enabled; state["challenge_settings"] = settings
        self.app.runtime.state.games.update_game(game["id"], state=state)
        self.app.challenge_active = enabled
        await callback.answer("⚔ وضعیت چالش تغییر کرد.")
        await self.challenge(callback)

    async def challenge_visibility_toggle(self, callback):
        gid = int(callback.message.chat.id); game = self._game(gid)
        if not game or not await self._allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        state = self._state(game); settings = dict(state.get("challenge_settings") or {})
        settings["show_player_status"] = not bool(settings.get("show_player_status", True))
        state["challenge_settings"] = settings
        self.app.runtime.state.games.update_game(game["id"], state=state)
        await callback.answer("🤏 نمایش وضعیت چالش تغییر کرد.")
        await self.challenge(callback)

    async def challenge_back(self, callback):
        gid = int(callback.message.chat.id); game = self._game(gid)
        if not game or not await self._allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        parts = str(callback.data or "").split(":")
        context = parts[3] if len(parts) >= 4 else "management"
        if context == "start":
            from runtime.role_distribution import _day_markup
            await callback.message.edit_text("🎭 <b>شروع بازی</b>\n\nسر صحبت و تنظیمات دور را انتخاب کنید:", reply_markup=_day_markup(int(game["id"])), parse_mode="HTML")
            await callback.answer("⬅️ به منوی شروع بازی برگشتید."); return
        if context == "round":
            kb = InlineKeyboardMarkup(row_width=1)
            kb.add(InlineKeyboardButton("🎲 انتخاب خودکار", callback_data="speaker_auto"))
            kb.add(InlineKeyboardButton("✋ انتخاب دستی", callback_data="speaker_manual"))
            kb.add(InlineKeyboardButton("⚔ وضعیت چالش", callback_data=f"mgmt:{int(game['id'])}:challenge:round"))
            kb.add(InlineKeyboardButton("▶️ شروع دور", callback_data="start_turn"))
            await callback.message.edit_text("🌞 <b>منوی دور</b>\n\nسر صحبت را انتخاب کنید:", reply_markup=kb, parse_mode="HTML")
            await callback.answer("⬅️ به منوی دور برگشتید."); return
        await self.open(callback)

    async def back_lobby(self, callback):
        gid = int(callback.message.chat.id); game = self._game(gid)
        if not game or not await self._allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        renderer = getattr(self.app, "_render_final_lobby", None) or getattr(self.app, "_render_production_lobby", None)
        if renderer:
            try:
                await renderer(callback); await callback.answer("↩️ لابی باز شد."); return
            except Exception: logging.exception("management back_lobby failed game=%s",game.get("id"))
        await callback.answer("❌ باز کردن لابی انجام نشد.", show_alert=True)

    async def next(self, callback):
        gid = int(callback.message.chat.id); game = self._game(gid)
        if not game or not await self._allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        s = dict(self._state(game).get("next_settings") or {})
        s.setdefault("allow_players_next", True); s.setdefault("allow_moderator_next", True); s.setdefault("anti_spam", True)
        kb = InlineKeyboardMarkup(row_width=2)
        for k, t in (("allow_players_next", "👤 نکست بازیکن"), ("allow_moderator_next", "🎩 نکست گرداننده"), ("anti_spam", "🛡 ضداسپم")):
            kb.insert(InlineKeyboardButton(f"{t}: {'روشن' if s[k] else 'خاموش'}", callback_data=f"mgmt:{game['id']}:next_toggle:{k}"))
        kb.row(InlineKeyboardButton("⬅️ مدیریت", callback_data=f"mgmt:{game['id']}:open"))
        await callback.message.edit_text("⏭ <b>مدیریت نکست</b>", parse_mode="HTML", reply_markup=kb)
        await callback.answer()

    async def next_toggle(self, callback):
        p = self._parts(callback, "next_toggle", 4)
        if not p: return
        gid = int(callback.message.chat.id); game = self._game(gid)
        if not game or not await self._allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        allowed = {"allow_players_next", "allow_moderator_next", "anti_spam"}
        if p[3] not in allowed:
            await callback.answer("❌ گزینه نامعتبر است.", show_alert=True); return
        s = dict(self._state(game).get("next_settings") or {})
        s[p[3]] = not bool(s.get(p[3], True))
        self._save(game, next_settings=s)
        await callback.answer("⏭ ذخیره شد.")
        await self.next(callback)

    async def cancel(self, callback):
        gid = int(callback.message.chat.id); game = self._game(gid)
        if not game or not await self._allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
            return
        confirmer = getattr(self.app, "_confirm_cancel_game", None)
        if confirmer:
            await confirmer(callback)
            return
        state = self._state(game)
        state.update({"cancelled": True, "cancel_reason": "legacy_management_path"})
        self.app.runtime.state.games.update_game(game["id"], status="cancelled", event_number=0, state=state)
        await callback.answer("🚫 بازی لغو شد.")

    async def refresh(self, callback):
        gid = int(callback.message.chat.id)
        game = self._game(gid)
        if not game or not await self._allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید یا بازی فعال نیست.", show_alert=True); return
        if str(game.get("status") or "") != "lobby":
            await callback.answer("❌ بازسازی لابی فقط وقتی بازی در لابی است ممکن است.", show_alert=True); return
        # Prefer the canonical renderer if production_lobby exposes it.
        renderer = getattr(self.app, "_render_final_lobby", None) or getattr(self.app, "_render_production_lobby", None)
        if renderer:
            try:
                await renderer(callback)
                await callback.answer("↩️ لابی بازسازی شد.")
            except Exception:
                logging.exception("management canonical lobby refresh failed game=%s", game.get("id"))
                await callback.answer("❌ بازسازی لابی انجام نشد.", show_alert=True)
            return
        # Fallback renderer uses the same durable snapshot and lobby_message_id.
        data = self.app.runtime.lobby_snapshot(gid)
        game = data.get("game") or game
        scenario = self.scenarios.get_by_id(int(game.get("scenario_id"))) if game.get("scenario_id") else None
        scenario_name = str((scenario or {}).get("name") or game.get("scenario_id") or "---")
        cap = len((scenario or {}).get("roles") or [])
        rows = data.get("players") or []
        active = [r for r in rows if r.get("seat") is not None and str(r.get("status") or "active") not in {"removed", "dead"}]
        waiting = [r for r in rows if r.get("seat") is None and str(r.get("status") or "waiting") == "waiting"]
        active.sort(key=lambda r: int(r.get("seat") or 999))
        occupied = {int(r["seat"]): r for r in active}
        def mention(row):
            return f'<a href="tg://user?id={int(row["player_id"])}"><b>{html.escape(self._name(row))}</b></a>'
        lines = [
            "༄ <b>لیست بازی Mafia Nights</b>", "",
            f"📅 <b>تاریخ:</b> {datetime.now(ZoneInfo('Asia/Tehran')).strftime('%Y/%m/%d')}",
            f"🎭 <b>سناریو:</b> {html.escape(scenario_name)}",
            f"🔢 <b>شماره بازی:</b> {int(game.get('event_number') or 1)}",
            f"🎩 <b>گرداننده:</b> <a href=\"tg://user?id={int(game['moderator_id'])}\"><b>{int(game['moderator_id'])}</b></a>", "",
            "━━━━━━━━━━━━━━━━━━", f"👥 <b>بازیکنان:</b> {len(active)}/{cap}", "", "🪑 <b>لیست صندلی‌ها</b>",
        ]
        for seat in range(1, cap + 1):
            row = occupied.get(seat); lines.append(f"{seat:02d}. {mention(row) if row else '⬜ آزاد'}")
        if waiting:
            lines += ["", "🎟 <b>لیست رزرو</b>"] + [f"{i}. {mention(r)}" for i, r in enumerate(waiting, 1)]
        lines += ["", "━━━━━━━━━━━━━━━━━━", "༄"]
        kb = InlineKeyboardMarkup(row_width=3)
        for seat in range(1, cap + 1):
            row = occupied.get(seat); label = f"{seat:02d} {self._name(row)[:10]}" if row else f"{seat:02d} ⬜"
            kb.insert(InlineKeyboardButton(label, callback_data=f"lobby:{int(game['id'])}:seat:{seat}"))
        kb.row(InlineKeyboardButton("🚪 ورود / خروج", callback_data=f"lobby:{int(game['id'])}:toggle"))
        if len(active) >= cap > 0:
            kb.row(InlineKeyboardButton("🎟 رزرو / لغو رزرو", callback_data=f"lobby:{int(game['id'])}:reserve"))
            kb.row(InlineKeyboardButton("🎭 پخش نقش", callback_data=f"lobby:{int(game['id'])}:distribute"))
        kb.row(InlineKeyboardButton("⚙️ مدیریت بازی", callback_data=f"lobby:{int(game['id'])}:management"))
        kb.row(InlineKeyboardButton("🚫 لغو بازی", callback_data=f"lobby:{int(game['id'])}:cancel"))
        lid = self._state(game).get("lobby_message_id")
        try:
            if lid:
                await self.app.bot.edit_message_text("\n".join(lines), gid, int(lid), parse_mode="HTML", reply_markup=kb)
            else:
                msg = await self.app.bot.send_message(gid, "\n".join(lines), parse_mode="HTML", reply_markup=kb)
                self._save(game, lobby_message_id=int(msg.message_id))
            await callback.answer("↩️ لابی بازسازی شد.")
        except Exception:
            logging.exception("management lobby refresh failed game=%s", game.get("id"))
            await callback.answer("❌ بازسازی لابی انجام نشد.", show_alert=True)

    async def close(self, callback):
        # Closing management must never delete the canonical lobby message.
        await self.refresh(callback)

    def install(self):
        dp = self.app.dp
        dp.register_callback_query_handler(self.open, lambda c: str(c.data or "").startswith("lobby:") and c.data.endswith(":management"), state="*")
        dp.register_callback_query_handler(self.open, lambda c: str(c.data or "").startswith("mgmt:") and c.data.endswith(":open"), state="*")
        handlers = {
            "event": self.event, "event_delta": self.event_delta, "event_input": self.event_input,
            "scenario": self.scenario, "scenario_pick": self.scenario_pick, "moderator_pick": self.moderator_pick,
            "remove": self.remove, "remove_pick": self.remove_pick,
            "unreserve": self.unreserve, "unreserve_pick": self.unreserve_pick,
            "replace": self.replace, "replace_sub": self.replace_sub, "replace_target": self.replace_target,
            "attendance": self.attendance, "attendance_ready": self.attendance_ready, "attendance_close": self.attendance_close,
            "birthday": self.birthday, "birthday_pick": self.birthday_pick,
            "challenge": self.challenge, "challenge_toggle": self.challenge_toggle, "challenge_visibility_toggle": self.challenge_visibility_toggle,
            "next": self.next, "next_toggle": self.next_toggle,
            "cancel": self.cancel, "back_lobby": self.back_lobby, "challenge_back": self.challenge_back,
        }
        for action, fn in handlers.items():
            dp.register_callback_query_handler(
                fn,
                lambda c, a=action: (lambda p: len(p) >= 3 and p[0] == "mgmt" and p[2] == a)(str(c.data or "").split(":")),
                state="*",
            )
        # Keep noop explicitly handled so Telegram does not leave a stale spinner.
        dp.register_callback_query_handler(
            lambda c: c.answer(),
            lambda c: str(c.data or "").startswith("mgmt:") and str(c.data or "").split(":")[2] == "noop",
            state="*",
        )
        dp.register_message_handler(self.event_input_value, state=ManagementState.waiting_event_number)
