"""Final production-runtime cutover for the Vercel Telegram entrypoint."""
from __future__ import annotations

import html
import logging
import sys
from typing import Any, Callable

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
            if app is not None and getattr(app, "_management_surface_final", False) and getattr(app, "_canonical_management_surface", False):
                logging.info("PRODUCTION CUTOVER: ignored legacy management.panel replacement")
                return
        original_setattr(self, name, value)
    GameManagement.__setattr__ = guarded_setattr
    GameManagement._production_panel_assignment_guard = True


def _handler(item: Any) -> Any:
    """Return the dispatcher callback without assuming aiogram's field name."""
    value = getattr(item, "callback", None)
    if value is not None:
        return value
    return getattr(item, "handler", None)


def _install_lobby_attendance_fix(app: Any) -> None:
    """Install a first-priority fl_ready handler and replace the old binding correctly.

    The previous patch wrote ``target.handler`` even when aiogram's Handler object
    stored the executable callback in ``target.callback``. In that case the old
    ``ready`` function continued to execute. We now replace the actual executable
    field and also install a first-priority fallback when no old handler can be
    identified.
    """
    if getattr(app, "_production_attendance_fix", False):
        return
    registry = getattr(getattr(app.dp, "callback_query_handlers", None), "handlers", None)
    if registry is None:
        logging.warning("PRODUCTION ATTENDANCE FIX: callback registry unavailable")
        return

    target = None
    for item in list(registry):
        fn = _handler(item)
        if fn is None:
            continue
        if getattr(fn, "__module__", "") == "runtime.lobby_ui_final" and getattr(fn, "__name__", "") == "ready":
            target = item
            break

    def game(gid: int):
        return app.runtime.state.active_game(int(gid))

    def players(g: dict[str, Any]):
        return app.runtime.state.games.list_players(g["id"]) if g else []

    def pname(p: dict[str, Any]) -> str:
        return str(p.get("nickname") or p.get("first_name") or p.get("username") or p.get("player_id") or "👤")

    def mention(uid: int, fallback: str | None = None) -> str:
        try:
            name = app.display_name(int(uid), fallback or app.players.get(int(uid)))
        except Exception:
            name = fallback or app.players.get(int(uid)) or str(uid)
        return f'<a href="tg://user?id={int(uid)}"><b>{html.escape(str(name))}</b></a>'

    async def fixed_ready(callback):
        gid = int(callback.message.chat.id)
        uid = int(callback.from_user.id)
        g = game(gid)
        ps = players(g) if g else []
        player = next((p for p in ps if int(p.get("player_id") or 0) == uid), None)
        if not g or not player or player.get("seat") is None or str(player.get("status") or "active") in {"removed", "dead", "finished", "kicked"}:
            await callback.answer("⛔ فقط بازیکنان داخل بازی می‌توانند آماده شوند.", show_alert=True)
            raise CancelHandler()

        current = dict((g or {}).get("state") or {})
        ready_players: set[int] = set()
        for value in current.get("ready_players") or []:
            try:
                ready_players.add(int(value))
            except (TypeError, ValueError):
                continue
        ready_players.add(uid)
        current["ready_players"] = sorted(ready_players)
        g["state"] = current

        # Persist and render the exact same state. Do not call attendance(),
        # because that function performs another active_game lookup.
        app.runtime.state.games.update_game(g["id"], state=current)
        active = [p for p in ps if p.get("seat") is not None and str(p.get("status") or "active") not in {"removed", "dead", "finished", "kicked"}]
        active.sort(key=lambda p: int(p.get("seat") or 999))
        lines = ["📢 <b>تگ لیست / حاضری</b>", ""]
        for p in active:
            pid = int(p["player_id"])
            mark = "🟢" if pid in ready_players else "⚪️"
            lines.append(f"{mark} {int(p['seat']):02d}. {mention(pid, pname(p))}")
        lines.extend(["", " ".join(mention(int(p["player_id"]), pname(p)) for p in active)])
        kb = InlineKeyboardMarkup(row_width=1).add(
            InlineKeyboardButton("🙋‍♂️ آماده‌ام", callback_data="fl_ready"),
            InlineKeyboardButton("⬅️ بازگشت به لابی", callback_data="fl_back"),
        )
        try:
            await callback.message.edit_text("\n".join(lines), parse_mode="HTML", reply_markup=kb)
        except Exception:
            logging.exception("PRODUCTION ATTENDANCE FIX: message render failed game=%s", g.get("id"))
            await callback.answer("❌ بروزرسانی حاضری انجام نشد.", show_alert=True)
            raise CancelHandler()
        await callback.answer("✅ آماده‌ام ثبت شد")
        raise CancelHandler()

    fixed_ready._production_attendance_fix = True

    if target is not None:
        # IMPORTANT: aiogram Handler uses .callback in the installed dispatcher.
        # Replace that actual field; assigning .handler alone is ineffective.
        if hasattr(target, "callback"):
            target.callback = fixed_ready
        else:
            target.handler = fixed_ready
        try:
            registry.remove(target)
        except ValueError:
            pass
        registry.insert(0, target)
        logging.info("PRODUCTION ATTENDANCE FIX replaced existing callback binding")
    else:
        # Defensive fallback: register a fresh handler and put it before every
        # legacy handler, so a metadata/wrapper change cannot revive the old one.
        app.dp.register_callback_query_handler(fixed_ready, lambda c: str(c.data or "") == "fl_ready", state="*")
        fresh = None
        for item in reversed(registry):
            if _handler(item) is fixed_ready:
                fresh = item
                break
        if fresh is not None:
            try:
                registry.remove(fresh)
            except ValueError:
                pass
            registry.insert(0, fresh)
        logging.warning("PRODUCTION ATTENDANCE FIX installed fallback callback; old ready handler was not discoverable")

    app._production_attendance_fix = True
    logging.info("PRODUCTION ATTENDANCE FIX active: callback binding=%s", "replaced" if target is not None else "fallback")


def _finalize(app: Any) -> None:
    global _INSTALLED
    if app is None or getattr(app, "_production_cutover_final", False):
        return
    app._production_cutover_final = True
    from runtime.final_identity_authority import install as install_identity
    install_identity(app)
    from runtime.speaker_order_authority import install as install_speaker
    install_speaker(app)
    from runtime.production_consistency_loader import install as install_consistency
    install_consistency(app)
    from runtime.dual_winner_support import install as install_dual_winner
    install_dual_winner(app)
    _install_lobby_attendance_fix(app)
    logging.info("PRODUCTION CUTOVER FINAL active: speaker=canonical management=canonical result=canonical attendance=canonical")
    _INSTALLED = True


def _wrap_final_installer(module_name: str, function_name: str = "install") -> None:
    module = __import__(module_name, fromlist=[function_name])
    original: Callable[..., Any] = getattr(module, function_name)
    marker = f"_production_cutover_wrapped_{function_name}"
    if getattr(module, marker, False):
        return
    def wrapped(app: Any, *args: Any, **kwargs: Any):
        result = original(app, *args, **kwargs)
        _finalize(app)
        return result
    wrapped.__name__ = getattr(original, "__name__", function_name)
    wrapped.__doc__ = getattr(original, "__doc__", None)
    setattr(module, function_name, wrapped)
    setattr(module, marker, True)


def install() -> None:
    if _production_app() is None:
        return
    _protect_legacy_management_assignment()
    _wrap_final_installer("runtime.game_info_security_v2")
    app = _production_app()
    if app is not None and not getattr(app, "_production_cutover_final", False):
        _finalize(app)
