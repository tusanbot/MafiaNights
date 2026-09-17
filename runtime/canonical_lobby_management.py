"""Canonical final owner for the current lobby/management/attendance surface.

This installer is deliberately registered last. It removes the competing
management/lobby-navigation callback families and installs one coherent path:
management -> back to lobby, attendance -> ready state, and text commands.
"""
from __future__ import annotations

import html
import logging
from datetime import datetime
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

from aiogram import types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.exceptions import MessageCantBeEdited, MessageNotModified, MessageToEditNotFound

from repositories.scenario_repository import ScenarioRepository
from runtime.game_management import GameManagement


LEGACY_MODULES = {
    "runtime.game_management",
    "runtime.management_navigation",
    "runtime.lobby_final_patch",
    "runtime.lobby_management_fix",
}
LEGACY_NAMES = {
    "open", "event", "event_delta", "event_input", "scenario", "scenario_pick",
    "moderator_pick", "remove", "remove_pick", "unreserve", "unreserve_pick",
    "replace", "replace_sub", "replace_target", "attendance", "attendance_pick",
    "attendance_ready", "birthday", "birthday_pick", "challenge", "challenge_toggle",
    "next", "next_toggle", "cancel", "refresh", "close", "back_lobby",
}


def _unwrap(fn: Any) -> Any:
    seen: set[int] = set()
    while fn is not None and id(fn) not in seen:
        seen.add(id(fn))
        nxt = getattr(fn, "__wrapped__", None)
        if nxt is None:
            break
        fn = nxt
    return fn


def _callback_name(fn: Any) -> str:
    fn = _unwrap(fn)
    return str(getattr(fn, "__name__", ""))


def _callback_module(fn: Any) -> str:
    fn = _unwrap(fn)
    return str(getattr(fn, "__module__", ""))


def _remove_competing_handlers(app: Any) -> int:
    removed = 0
    registries = [
        getattr(getattr(app, "dp", None), "callback_query_handlers", None),
    ]
    for registry_obj in registries:
        table = getattr(registry_obj, "handlers", None)
        if table is None:
            continue
        kept = []
        for item in list(table):
            fn = getattr(item, "callback", None) or getattr(item, "handler", None)
            name = _callback_name(fn)
            module = _callback_module(fn)
            if module in LEGACY_MODULES and name in LEGACY_NAMES:
                removed += 1
                continue
            kept.append(item)
        table[:] = kept
    return removed


async def _answer(_: Any, *args: Any, **kwargs: Any) -> None:
    return None


def _callback_like(message: types.Message, game_id: int, action: str) -> Any:
    return SimpleNamespace(
        message=message,
        from_user=message.from_user,
        data=f"mgmt:{int(game_id)}:{action}",
        answer=_answer,
    )


def install(app: Any, management: GameManagement) -> bool:
    removed = _remove_competing_handlers(app)
    scenarios = ScenarioRepository()

    def game_for(group_id: int) -> dict[str, Any] | None:
        return app.runtime.state.active_game(int(group_id))

    def state(game: dict[str, Any]) -> dict[str, Any]:
        return dict(game.get("state") or {})

    def save(game: dict[str, Any], **changes: Any) -> bool:
        value = state(game)
        value.update(changes)
        game["state"] = value
        return bool(app.runtime.state.games.update_game(int(game["id"]), state=value))

    def name(row: dict[str, Any] | None) -> str:
        if not row:
            return "👤"
        return str(row.get("nickname") or row.get("first_name") or row.get("username") or row.get("name") or row.get("player_id") or "👤")

    def mention(row: dict[str, Any]) -> str:
        uid = int(row["player_id"])
        return f'<a href="tg://user?id={uid}"><b>{html.escape(name(row))}</b></a>'

    def active_rows(game: dict[str, Any]) -> list[dict[str, Any]]:
        rows = app.runtime.state.games.list_players(int(game["id"]))
        return [r for r in rows if r.get("seat") is not None and str(r.get("status") or "active") not in {"removed", "dead", "finished"}]

    def capacity(game: dict[str, Any], rows: list[dict[str, Any]]) -> int:
        sid = game.get("scenario_id")
        scenario = None
        if sid is not None:
            try:
                scenario = scenarios.get_by_id(int(sid))
            except (TypeError, ValueError):
                scenario = scenarios.get_by_name(str(sid))
        cap = len((scenario or {}).get("roles") or [])
        if cap:
            return cap
        st = state(game)
        for key in ("seat_count", "player_count", "max_players"):
            try:
                value = int(st.get(key) or 0)
                if value > 0:
                    return value
            except (TypeError, ValueError):
                pass
        seats = [int(r["seat"]) for r in rows if r.get("seat") is not None]
        return max(seats, default=0)

    def panel(game_id: int) -> InlineKeyboardMarkup:
        items = [
            ("🔢 شماره بازی", "event"), ("📝 تغییر سناریو", "scenario"), ("🗑 حذف بازیکن", "remove"),
            ("🎟 لغو رزرو", "unreserve"), ("🔄 جایگزین بازیکن", "replace"), ("✅ حاضری", "attendance"),
            ("🎂 تولد بازیکن", "birthday"), ("⚔ وضعیت چالش", "challenge"), ("⏭ مدیریت نکست", "next"),
            ("🚫 لغو بازی", "cancel"), ("⬅️ بازگشت به لابی", "back_lobby"),
        ]
        kb = InlineKeyboardMarkup(row_width=3)
        for i in range(0, len(items), 3):
            kb.row(*(InlineKeyboardButton(t, callback_data=f"mgmt:{int(game_id)}:{a}") for t, a in items[i:i + 3]))
        return kb

    management.panel = panel
    GameManagement.panel = panel

    async def open_management(callback: Any) -> None:
        gid = int(callback.message.chat.id)
        game = game_for(gid)
        if not game or not await management._allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید یا بازی فعال نیست.", show_alert=True)
            return
        await callback.message.edit_text(
            f"⚙️ <b>مدیریت بازی</b>\n\n🔢 شماره: {int(game.get('event_number') or 1)}\n"
            f"📌 وضعیت: {html.escape(str(game.get('status') or 'lobby'))}\n\n"
            "پنل مدیریت فعال است.",
            parse_mode="HTML", reply_markup=panel(int(game["id"])),
        )
        await callback.answer()

    async def back_lobby(callback: Any) -> None:
        gid = int(callback.message.chat.id)
        game = game_for(gid)
        if not game or not await management._allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید یا بازی فعال نیست.", show_alert=True)
            return
        if str(game.get("status") or "") != "lobby":
            await callback.answer("❌ بازی در حال اجراست و لابی فعال نیست.", show_alert=True)
            return
        renderer = getattr(app, "_render_production_lobby", None)
        if not renderer:
            await callback.answer("❌ موتور لابی فعال نیست.", show_alert=True)
            return
        try:
            ok = bool(await renderer(gid, game))
        except TypeError:
            ok = bool(await renderer(gid))
        except Exception:
            logging.exception("canonical back_lobby failed game=%s", game.get("id"))
            ok = False
        await callback.answer("⬅️ به لابی برگشتید." if ok else "❌ بازگشت به لابی انجام نشد.", show_alert=not ok)

    async def attendance(callback: Any) -> None:
        gid = int(callback.message.chat.id)
        game = game_for(gid)
        if not game or not await management._allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
            return
        players = sorted(active_rows(game), key=lambda r: int(r.get("seat") or 999))
        if not players:
            await callback.answer("❌ بازیکن فعالی در بازی وجود ندارد.", show_alert=True)
            return
        attendance_state = {str(k): bool(v) for k, v in dict(state(game).get("attendance") or {}).items()}
        active_ids = {str(int(r["player_id"])) for r in players}
        attendance_state = {k: v for k, v in attendance_state.items() if k in active_ids}
        for uid in active_ids:
            attendance_state.setdefault(uid, False)
        save(game, attendance=attendance_state, attendance_announced=False)
        lines = ["🟢 <b>بازیکنان حاضر در لیست</b>", ""]
        for row in players:
            icon = "🟢" if attendance_state.get(str(int(row["player_id"])), False) else "⚪️"
            lines.append(f"{icon} {int(row['seat']):02d}. {mention(row)}")
        lines += ["", "برای اعلام آمادگی، دکمه «آماده‌ام» را بزنید."]
        kb = InlineKeyboardMarkup(row_width=1).add(
            InlineKeyboardButton("آماده‌ام", callback_data=f"mgmt:{int(game['id'])}:attendance_ready")
        )
        mid = state(game).get("attendance_message_id")
        try:
            if mid:
                await app.bot.edit_message_text("\n".join(lines), gid, int(mid), parse_mode="HTML", reply_markup=kb)
            else:
                msg = await app.bot.send_message(gid, "\n".join(lines), parse_mode="HTML", reply_markup=kb)
                mid = int(msg.message_id)
            save(game, attendance_message_id=int(mid))
            await callback.answer("✅ لیست حاضری به‌روزرسانی شد.")
        except Exception:
            logging.exception("canonical attendance render failed game=%s", game.get("id"))
            await callback.answer("❌ نمایش حاضری انجام نشد.", show_alert=True)

    async def attendance_ready(callback: Any) -> None:
        gid = int(callback.message.chat.id)
        game = game_for(gid)
        uid = int(callback.from_user.id)
        if not game:
            await callback.answer("❌ بازی فعالی وجود ندارد.", show_alert=True)
            return
        rows = app.runtime.state.games.list_players(int(game["id"]))
        player = next((r for r in rows if int(r["player_id"]) == uid), None)
        if not player or player.get("seat") is None or str(player.get("status") or "") in {"removed", "dead", "finished"}:
            await callback.answer("⛔ فقط بازیکنان حاضر در بازی می‌توانند اعلام آمادگی کنند.", show_alert=True)
            return
        current = game_for(gid) or game
        attendance_state = dict(state(current).get("attendance") or {})
        attendance_state[str(uid)] = True
        save(current, attendance=attendance_state)
        current = game_for(gid) or current
        players = sorted(active_rows(current), key=lambda r: int(r.get("seat") or 999))
        attendance_state = dict(state(current).get("attendance") or {})
        lines = ["🟢 <b>بازیکنان حاضر در لیست</b>", ""]
        for row in players:
            icon = "🟢" if attendance_state.get(str(int(row["player_id"])), False) else "⚪️"
            lines.append(f"{icon} {int(row['seat']):02d}. {mention(row)}")
        lines += ["", "برای اعلام آمادگی، دکمه «آماده‌ام» را بزنید."]
        kb = InlineKeyboardMarkup(row_width=1).add(
            InlineKeyboardButton("آماده‌ام", callback_data=f"mgmt:{int(current['id'])}:attendance_ready")
        )
        mid = state(current).get("attendance_message_id")
        if mid:
            try:
                await app.bot.edit_message_text("\n".join(lines), gid, int(mid), parse_mode="HTML", reply_markup=kb)
            except (MessageNotModified, MessageCantBeEdited, MessageToEditNotFound):
                pass
            except Exception:
                logging.exception("canonical attendance ready render failed game=%s", current.get("id"))
        if players and all(bool(attendance_state.get(str(int(r["player_id"])), False)) for r in players):
            if not state(current).get("attendance_announced"):
                save(current, attendance_announced=True)
                try:
                    await app.bot.send_message(gid, "🎉 <b>همه بازیکنان آماده‌اند.</b>", parse_mode="HTML")
                except Exception:
                    logging.exception("canonical all-ready notification failed game=%s", current.get("id"))
        await callback.answer("✅ آمادگی شما ثبت شد.")

    async def render_lobby(group_id: int, game: dict[str, Any] | None = None) -> bool:
        game = game or game_for(group_id)
        if not game or str(game.get("status") or "") != "lobby":
            return False
        data = app.runtime.lobby_snapshot(int(group_id))
        game = data.get("game") or game
        rows = data.get("players") or app.runtime.state.games.list_players(int(game["id"]))
        cap = capacity(game, rows)
        if cap <= 0:
            logging.warning("canonical lobby: scenario has no capacity game=%s scenario=%s", game.get("id"), game.get("scenario_id"))
        active = sorted([r for r in rows if r.get("seat") is not None and str(r.get("status") or "active") not in {"removed", "dead", "finished"}], key=lambda r: int(r.get("seat") or 999))
        waiting = [r for r in rows if r.get("seat") is None and str(r.get("status") or "waiting") in {"waiting", "substitute"}]
        occupied = {int(r["seat"]): r for r in active}
        sid = game.get("scenario_id")
        scenario = None
        try:
            scenario = scenarios.get_by_id(int(sid)) if sid is not None else None
        except (TypeError, ValueError):
            scenario = scenarios.get_by_name(str(sid)) if sid is not None else None
        scenario_name = str((scenario or {}).get("name") or sid or "انتخاب نشده")
        moderator_id = int(game.get("moderator_id") or 0)
        moderator_row = next((r for r in rows if int(r.get("player_id") or 0) == moderator_id), None)
        moderator_name = name(moderator_row) if moderator_row else "❌ انتخاب نشده"
        lines = [
            "༄ <b>لیست بازی Mafia Nights</b>", "",
            f"📅 <b>تاریخ:</b> {datetime.now(ZoneInfo('Asia/Tehran')).strftime('%Y/%m/%d')}",
            f"📝 <b>سناریو:</b> {html.escape(scenario_name)}",
            f"🔢 <b>شماره بازی:</b> {int(game.get('event_number') or 1)}",
            f"🎩 <b>گرداننده:</b> {html.escape(moderator_name) if not moderator_id else f'<a href=\"tg://user?id={moderator_id}\"><b>{html.escape(moderator_name)}</b></a>'}",
            "", "━━━━━━━━━━━━━━━━━━", f"👥 <b>بازیکنان:</b> {len(active)}/{cap}", "", "🪑 <b>لیست صندلی‌ها</b>",
        ]
        for seat in range(1, cap + 1):
            row = occupied.get(seat)
            lines.append(f"{seat:02d}. {mention(row) if row else '⬜ آزاد'}")
        if waiting:
            lines += ["", "🎟 <b>لیست رزرو</b>"]
            for i, row in enumerate(waiting, 1):
                lines.append(f"{i}. {mention(row)}")
        lines += ["", "━━━━━━━━━━━━━━━━━━"]
        kb = InlineKeyboardMarkup(row_width=3)
        for seat in range(1, cap + 1):
            row = occupied.get(seat)
            label = f"{seat:02d} {name(row)[:10]}" if row else f"{seat:02d} ⬜"
            kb.insert(InlineKeyboardButton(label, callback_data=f"lobby:{int(game['id'])}:seat:{seat}"))
        kb.row(
            InlineKeyboardButton("✅ ورود", callback_data=f"lobby:{int(game['id'])}:join"),
            InlineKeyboardButton("❌ خروج", callback_data=f"lobby:{int(game['id'])}:leave"),
        )
        if cap > 0 and len(active) >= cap:
            kb.row(InlineKeyboardButton("🎟 رزرو / لغو رزرو", callback_data=f"lobby:{int(game['id'])}:reserve"))
            kb.row(InlineKeyboardButton("🎭 پخش نقش", callback_data=f"lobby:{int(game['id'])}:distribute"))
        kb.row(InlineKeyboardButton("📝 انتخاب سناریو", callback_data=f"lobby:{int(game['id'])}:change_scenario"))
        kb.row(InlineKeyboardButton("🎩 انتخاب گرداننده", callback_data=f"lobby:{int(game['id'])}:change_moderator"))
        kb.row(InlineKeyboardButton("⚙️ مدیریت بازی", callback_data=f"lobby:{int(game['id'])}:management"))
        kb.row(InlineKeyboardButton("🚫 لغو بازی", callback_data=f"lobby:{int(game['id'])}:cancel"))
        text = "\n".join(lines)
        mid = state(game).get("lobby_message_id")
        try:
            if mid:
                await app.bot.edit_message_text(text, int(group_id), int(mid), parse_mode="HTML", reply_markup=kb)
            else:
                msg = await app.bot.send_message(int(group_id), text, parse_mode="HTML", reply_markup=kb)
                save(game, lobby_message_id=int(msg.message_id))
            return True
        except (MessageNotModified, MessageCantBeEdited):
            return True
        except MessageToEditNotFound:
            pass
        except Exception:
            logging.exception("canonical lobby render failed game=%s", game.get("id"))
        try:
            msg = await app.bot.send_message(int(group_id), text, parse_mode="HTML", reply_markup=kb)
            save(game, lobby_message_id=int(msg.message_id))
            return True
        except Exception:
            logging.exception("canonical lobby replacement failed game=%s", game.get("id"))
            return False

    app._render_production_lobby = render_lobby
    app._production_lobby_render = render_lobby

    # Management callbacks.
    dp = app.dp
    dp.register_callback_query_handler(open_management, lambda c: str(c.data or "") in {"manage_game", "fp:panel"}, state="*")
    dp.register_callback_query_handler(open_management, lambda c: str(c.data or "").startswith("lobby:") and str(c.data or "").endswith(":management"), state="*")
    dp.register_callback_query_handler(open_management, lambda c: str(c.data or "").startswith("mgmt:") and str(c.data or "").endswith(":open"), state="*")
    dp.register_callback_query_handler(back_lobby, lambda c: str(c.data or "").startswith("mgmt:") and str(c.data or "").endswith(":back_lobby"), state="*")
    dp.register_callback_query_handler(attendance_ready, lambda c: str(c.data or "").startswith("mgmt:") and str(c.data or "").endswith(":attendance_ready"), state="*")

    # Delegate all remaining management actions to the canonical GameManagement
    # implementation after removing its old competing registrations.
    delegated = {
        "event": management.event, "event_delta": management.event_delta, "event_input": management.event_input,
        "scenario": management.scenario, "scenario_pick": management.scenario_pick, "moderator_pick": management.moderator_pick,
        "remove": management.remove, "remove_pick": management.remove_pick, "unreserve": management.unreserve,
        "unreserve_pick": management.unreserve_pick, "replace": management.replace, "replace_sub": management.replace_sub,
        "replace_target": management.replace_target, "birthday": management.birthday, "birthday_pick": management.birthday_pick,
        "challenge": management.challenge, "challenge_toggle": management.challenge_toggle, "next": management.next,
        "next_toggle": management.next_toggle, "cancel": management.cancel,
    }
    for action, fn in delegated.items():
        dp.register_callback_query_handler(
            fn,
            lambda c, a=action: (lambda p: len(p) >= 3 and p[0] == "mgmt" and p[2] == a)(str(c.data or "").split(":")),
            state="*",
        )
    dp.register_callback_query_handler(attendance, lambda c: str(c.data or "").startswith("mgmt:") and str(c.data or "").split(":")[2] == "attendance", state="*")
    dp.register_callback_query_handler(management.attendance_pick, lambda c: str(c.data or "").startswith("mgmt:") and str(c.data or "").split(":")[2] == "attendance_pick", state="*")

    # Text commands: one source of truth for opening attendance and marking the
    # sender ready. Both Persian spacing variants and slash forms are accepted.
    def normalize(value: str | None) -> str:
        text = (value or "").strip().replace("‌", " ")
        text = " ".join(text.split()).casefold()
        return text[1:] if text.startswith("/") else text

    async def text_attendance(message: types.Message):
        if message.chat.type not in {"group", "supergroup"}:
            await message.reply("⚠️ این دستور فقط داخل گروه قابل استفاده است.")
            return
        game = game_for(int(message.chat.id))
        if not game:
            await message.reply("❌ بازی فعالی وجود ندارد.")
            return
        await attendance(_callback_like(message, int(game["id"]), "attendance"))

    async def text_ready(message: types.Message):
        if message.chat.type not in {"group", "supergroup"}:
            await message.reply("⚠️ این دستور فقط داخل گروه قابل استفاده است.")
            return
        game = game_for(int(message.chat.id))
        if not game:
            await message.reply("❌ بازی فعالی وجود ندارد.")
            return
        await attendance_ready(_callback_like(message, int(game["id"]), "attendance_ready"))

    dp.register_message_handler(
        text_attendance,
        lambda m: normalize(getattr(m, "text", None)) in {"حاضری", "حاضری لیست", "attendance"},
        content_types=types.ContentTypes.TEXT,
        state="*",
    )
    dp.register_message_handler(
        text_ready,
        lambda m: normalize(getattr(m, "text", None)) in {"آماده ام", "آماده‌ام", "آمادهام", "آماده", "ready"},
        content_types=types.ContentTypes.TEXT,
        state="*",
    )

    logging.info("CANONICAL_LOBBY_MANAGEMENT installed removed=%s", removed)
    return True
