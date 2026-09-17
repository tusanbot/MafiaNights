"""Final production-runtime cutover for the Vercel Telegram entrypoint."""
from __future__ import annotations

import html
import logging
import sys
from typing import Any

from aiogram.dispatcher.handler import CancelHandler
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

_INSTALLED = False


def _production_app() -> Any | None:
    module = sys.modules.get("player_runtime_entry")
    return getattr(module, "main", None) if module is not None else None


def _protect_legacy_management_assignment() -> None:
    from runtime.game_management import GameManagement
    if getattr(GameManagement, "_production_panel_assignment_guard", False):
        return
    original_setattr = GameManagement.__setattr__

    def guarded_setattr(self, name: str, value: Any) -> None:
        if name == "panel":
            app = getattr(self, "app", None)
            if app is not None and getattr(app, "_management_surface_final", False):
                logging.info("PRODUCTION CUTOVER: ignored legacy management.panel replacement")
                return
        original_setattr(self, name, value)

    GameManagement.__setattr__ = guarded_setattr
    GameManagement._production_panel_assignment_guard = True


def _handler(item: Any) -> Any:
    return getattr(item, "callback", None) or getattr(item, "handler", None)


def _remove_legacy_management_surface(app: Any) -> None:
    """Undo the earlier player_runtime_entry wrapper before installing the sole final surface."""
    management = getattr(app, "game_management", None)
    if management is None:
        return
    from runtime.game_management import GameManagement
    if getattr(app, "_canonical_management_surface", False):
        management.panel = GameManagement.panel.__get__(management, GameManagement)
        app._canonical_management_surface = False
        logging.info("PRODUCTION CUTOVER: removed legacy canonical management wrapper")
    registry = getattr(getattr(app.dp, "callback_query_handlers", None), "handlers", None)
    if registry is None:
        return
    legacy_names = {"info", "kick", "kick_pick", "warning", "warning_pick", "back_lobby", "ready"}
    kept = []
    removed = 0
    for item in list(registry):
        fn = _handler(item)
        if getattr(fn, "__module__", "") == "player_runtime_entry" and getattr(fn, "__name__", "") in legacy_names:
            removed += 1
            continue
        kept.append(item)
    registry[:] = kept
    if removed:
        logging.info("PRODUCTION CUTOVER: removed %d legacy management handlers", removed)


def _install_canonical_management_surface(app: Any) -> bool:
    """Install management_surface_final as the only management owner."""
    _remove_legacy_management_surface(app)
    try:
        from runtime.management_surface_final import install as install_management_surface
        installed = bool(install_management_surface(app))
        if installed or getattr(app, "_management_surface_final", False):
            app._management_surface_final = True
            logging.info("PRODUCTION CUTOVER: management_surface_final is sole management owner")
            return True
    except Exception:
        logging.exception("PRODUCTION CUTOVER: management_surface_final install failed")
    return False


def _normalize_scenario_ids(app: Any) -> None:
    """Make UUID scenario ids compatible with the legacy int() call in lobby_ui_final."""
    if getattr(app, "_scenario_id_compat", False):
        return
    state = getattr(getattr(app, "runtime", None), "state", None)
    original = getattr(state, "active_game", None)
    if state is None or not callable(original):
        return
    from repositories.scenario_repository import ScenarioId

    def active_game_compat(gid, _original=original):
        game = _original(gid)
        if isinstance(game, dict) and game.get("scenario_id") is not None and not isinstance(game.get("scenario_id"), ScenarioId):
            game["scenario_id"] = ScenarioId(game["scenario_id"])
        return game

    state.active_game = active_game_compat
    app._scenario_id_compat = True
    logging.info("PRODUCTION CUTOVER: UUID scenario_id compatibility active")


def _install_lobby_attendance_fix(app: Any) -> None:
    if getattr(app, "_production_attendance_fix", False):
        return
    registry = getattr(getattr(app.dp, "callback_query_handlers", None), "handlers", None)
    if registry is None:
        return
    target = None
    for item in list(registry):
        fn = _handler(item)
        if getattr(fn, "__module__", "") == "runtime.lobby_ui_final" and getattr(fn, "__name__", "") == "ready":
            target = item
            break

    def game(gid):
        return app.runtime.state.active_game(int(gid))
    def players(g):
        return app.runtime.state.games.list_players(g["id"]) if g else []
    def pname(p):
        return str(p.get("nickname") or p.get("first_name") or p.get("username") or p.get("player_id") or "👤")
    def mention(uid, fallback=None):
        try:
            name = app.display_name(int(uid), fallback or app.players.get(int(uid)))
        except Exception:
            name = fallback or app.players.get(int(uid)) or str(uid)
        return f'<a href="tg://user?id={int(uid)}"><b>{html.escape(str(name))}</b></a>'

    async def fixed_ready(callback):
        gid = int(callback.message.chat.id); uid = int(callback.from_user.id)
        g = game(gid); ps = players(g) if g else []
        player = next((p for p in ps if int(p.get("player_id") or 0) == uid), None)
        if not g or not player or player.get("seat") is None or str(player.get("status") or "active") in {"removed", "dead", "finished", "kicked"}:
            await callback.answer("⛔ فقط بازیکنان داخل بازی می‌توانند آماده شوند.", show_alert=True)
            raise CancelHandler()
        current = dict((g or {}).get("state") or {}); ready = set()
        for value in current.get("ready_players") or []:
            try: ready.add(int(value))
            except (TypeError, ValueError): pass
        ready.add(uid); current["ready_players"] = sorted(ready)
        app.runtime.state.games.update_game(g["id"], state=current)
        fresh = app.runtime.state.games.get_game(g["id"]); ps = players(fresh)
        active = sorted([p for p in ps if p.get("seat") is not None and str(p.get("status") or "active") not in {"removed", "dead", "finished", "kicked"}], key=lambda p: int(p.get("seat") or 999))
        lines = ["📢 <b>تگ لیست / حاضری</b>", ""] + [f"{'🟢' if int(p['player_id']) in ready else '⚪️'} {int(p['seat']):02d}. {mention(int(p['player_id']), pname(p))}" for p in active]
        kb = InlineKeyboardMarkup(row_width=1).add(InlineKeyboardButton("🙋‍♂️ آماده‌ام", callback_data="fl_ready"), InlineKeyboardButton("⬅️ بازگشت به لابی", callback_data="fl_back"))
        await callback.message.edit_text("\n".join(lines), parse_mode="HTML", reply_markup=kb)
        await callback.answer("✅ آماده‌ام ثبت شد")
        raise CancelHandler()

    fixed_ready._production_attendance_fix = True
    if target is not None:
        if hasattr(target, "callback"): target.callback = fixed_ready
        else: target.handler = fixed_ready
        try: registry.remove(target)
        except ValueError: pass
        registry.insert(0, target)
    else:
        app.dp.register_callback_query_handler(fixed_ready, lambda c: str(c.data or "") == "fl_ready", state="*")
    app._production_attendance_fix = True
    logging.info("PRODUCTION ATTENDANCE FIX active: ready_players is the sole ready state")


def _install_speaker_order_guard(app: Any) -> None:
    """Ensure selected speaker order survives the stable engine's start_round reset."""
    if getattr(app, "_speaker_order_start_guard", False):
        return
    registry = getattr(getattr(app.dp, "callback_query_handlers", None), "handlers", None)
    if registry is None:
        return
    for item in list(registry):
        fn = _handler(item)
        if getattr(fn, "__name__", "") != "start_round":
            continue
        if getattr(fn, "_production_speaker_start_guard", False):
            continue
        original = fn

        async def guarded_start_round(callback, _original=original):
            try:
                game = app.runtime.state.active_game(int(callback.message.chat.id))
                persisted = [int(x) for x in ((game or {}).get("state") or {}).get("turn_order") or []]
                if persisted:
                    app.turn_order = list(persisted)
                    app._stable_normal_order = list(persisted)
                    app._gm_normal_order = list(persisted)
                    app._canonical_speaker_seat = int(persisted[0])
                    logging.info("PRODUCTION SPEAKER ORDER GUARD: restored persisted turn_order=%s", persisted)
            except Exception:
                logging.exception("PRODUCTION SPEAKER ORDER GUARD restore failed")
            return await _original(callback)

        guarded_start_round.__name__ = "start_round"
        guarded_start_round._production_speaker_start_guard = True
        try: item.handler = guarded_start_round
        except Exception: item.callback = guarded_start_round
        try: registry.remove(item); registry.insert(0, item)
        except ValueError: pass
        break
    app._speaker_order_start_guard = True


def _install_management_fallback_panel(app: Any) -> None:
    """Fallback only if management_surface_final cannot be loaded."""
    management = getattr(app, "game_management", None)
    if management is None or getattr(app, "_management_panel_cutover", False):
        return
    app._management_panel_cutover = True

    def panel(game_id):
        game = management.app.runtime.state.games.get_game(game_id) or {}
        status = str(game.get("status") or "lobby")
        items = [
            ("🔢 شماره بازی", "event"), ("📝 تغییر سناریو", "scenario"), ("🗑 حذف بازیکن", "remove"),
            ("🎟 لغو رزرو", "unreserve"), ("🔄 جایگزین بازیکن", "replace"), ("✅ حاضری", "attendance"),
            ("🎂 تولد بازیکن", "birthday"), ("⚔ وضعیت چالش", "challenge"), ("⏭ مدیریت نکست", "next"),
            ("🚫 لغو بازی", "cancel"), ("ℹ️ اطلاعات بازی", "info"), ("🦵 کیک از بازی", "kick"),
            ("⚠️ تذکر بازیکن", "warning"), ("➕ ترن اضافه", "extra"), ("🔇 سکوت بازیکن", "mute"),
            ("🔊 حذف سکوت", "unmute"),
        ]
        items.append(("⬅️ بازگشت به لابی" if status == "lobby" else "⬅️ بازگشت", "back_lobby"))
        kb = InlineKeyboardMarkup(row_width=3)
        for i in range(0, len(items), 3):
            kb.row(*(InlineKeyboardButton(t, callback_data=f"mgmt:{int(game_id)}:{a}") for t, a in items[i:i + 3]))
        return kb
    management.panel = panel
    app._management_surface_final = True
    logging.info("FINAL MANAGEMENT PANEL fallback active")


def _finalize(app: Any) -> None:
    global _INSTALLED
    if app is None or getattr(app, "_production_cutover_final", False):
        return
    app._production_cutover_final = True
    _normalize_scenario_ids(app)
    _install_canonical_management_surface(app)
    from runtime.final_identity_authority import install as install_identity
    install_identity(app)
    from runtime.speaker_order_authority import install as install_speaker
    install_speaker(app)
    from runtime.production_consistency_loader import install as install_consistency
    install_consistency(app)
    from runtime.dual_winner_support import install as install_dual_winner
    install_dual_winner(app)
    _install_lobby_attendance_fix(app)
    _install_speaker_order_guard(app)
    from runtime.lobby_seat_authority import install as install_lobby_seat
    install_lobby_seat(app)
    from runtime.command_authority_final import install as install_command_authority
    install_command_authority(app)
    if not getattr(app, "_management_surface_final", False):
        _install_management_fallback_panel(app)
    logging.info("PRODUCTION CUTOVER FINAL active: single-management=1 uuid-scenario=1 attendance=ready_players speaker-order=persisted")
    _INSTALLED = True


def install() -> None:
    if _production_app() is None:
        return
    _protect_legacy_management_assignment()
    app = _production_app()
    if app is not None and not getattr(app, "_production_cutover_final", False):
        _finalize(app)
