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
    if getattr(GameManagement, "_production_panel_assignment_guard", False): return
    original_setattr = GameManagement.__setattr__
    def guarded_setattr(self, name: str, value: Any) -> None:
        if name == "panel":
            app = getattr(self, "app", None)
            if app is not None and getattr(app, "_management_surface_final", False) and getattr(app, "_canonical_management_surface", False):
                logging.info("PRODUCTION CUTOVER: ignored legacy management.panel replacement"); return
        original_setattr(self, name, value)
    GameManagement.__setattr__ = guarded_setattr
    GameManagement._production_panel_assignment_guard = True


def _handler(item: Any) -> Any:
    return getattr(item, "callback", None) or getattr(item, "handler", None)


def _install_lobby_attendance_fix(app: Any) -> None:
    if getattr(app, "_production_attendance_fix", False): return
    registry = getattr(getattr(app.dp, "callback_query_handlers", None), "handlers", None)
    if registry is None: return
    target = None
    for item in list(registry):
        fn = _handler(item)
        if getattr(fn, "__module__", "") == "runtime.lobby_ui_final" and getattr(fn, "__name__", "") == "ready": target = item; break
    def game(gid): return app.runtime.state.active_game(int(gid))
    def players(g): return app.runtime.state.games.list_players(g["id"]) if g else []
    def pname(p): return str(p.get("nickname") or p.get("first_name") or p.get("username") or p.get("player_id") or "👤")
    def mention(uid, fallback=None):
        try: name=app.display_name(int(uid),fallback or app.players.get(int(uid)))
        except Exception: name=fallback or app.players.get(int(uid)) or str(uid)
        return f'<a href="tg://user?id={int(uid)}"><b>{html.escape(str(name))}</b></a>'
    async def fixed_ready(callback):
        gid=int(callback.message.chat.id); uid=int(callback.from_user.id); g=game(gid); ps=players(g) if g else []
        player=next((p for p in ps if int(p.get("player_id") or 0)==uid),None)
        if not g or not player or player.get("seat") is None or str(player.get("status") or "active") in {"removed","dead","finished","kicked"}:
            await callback.answer("⛔ فقط بازیکنان داخل بازی می‌توانند آماده شوند.",show_alert=True); raise CancelHandler()
        current=dict((g or {}).get("state") or {}); ready=set()
        for value in current.get("ready_players") or []:
            try: ready.add(int(value))
            except (TypeError,ValueError): pass
        ready.add(uid); current["ready_players"]=sorted(ready)
        app.runtime.state.games.update_game(g["id"],state=current)
        fresh=app.runtime.state.games.get_game(g["id"]); ps=players(fresh); active=sorted([p for p in ps if p.get("seat") is not None and str(p.get("status") or "active") not in {"removed","dead","finished","kicked"}],key=lambda p:int(p.get("seat") or 999))
        lines=["📢 <b>تگ لیست / حاضری</b>",""]+[f"{'🟢' if int(p['player_id']) in ready else '⚪️'} {int(p['seat']):02d}. {mention(int(p['player_id']),pname(p))}" for p in active]
        kb=InlineKeyboardMarkup(row_width=1).add(InlineKeyboardButton("🙋‍♂️ آماده‌ام",callback_data="fl_ready"),InlineKeyboardButton("⬅️ بازگشت به لابی",callback_data="fl_back"))
        await callback.message.edit_text("\n".join(lines),parse_mode="HTML",reply_markup=kb); await callback.answer("✅ آماده‌ام ثبت شد"); raise CancelHandler()
    fixed_ready._production_attendance_fix=True
    if target is not None:
        if hasattr(target,"callback"): target.callback=fixed_ready
        else: target.handler=fixed_ready
        try: registry.remove(target)
        except ValueError: pass
        registry.insert(0,target)
    else:
        app.dp.register_callback_query_handler(fixed_ready,lambda c:str(c.data or "")=="fl_ready",state="*")
        fresh=next((x for x in registry if _handler(x) is fixed_ready),None)
        if fresh:
            registry.remove(fresh); registry.insert(0,fresh)
    app._production_attendance_fix=True
    logging.info("PRODUCTION ATTENDANCE FIX active")


def _finalize(app: Any) -> None:
    global _INSTALLED
    if app is None or getattr(app, "_production_cutover_final", False): return
    app._production_cutover_final=True
    from runtime.final_identity_authority import install as install_identity; install_identity(app)
    from runtime.speaker_order_authority import install as install_speaker; install_speaker(app)
    from runtime.production_consistency_loader import install as install_consistency; install_consistency(app)
    from runtime.dual_winner_support import install as install_dual_winner; install_dual_winner(app)
    _install_lobby_attendance_fix(app)
    from runtime.lobby_seat_authority import install as install_lobby_seat
    install_lobby_seat(app)
    from runtime.command_authority_final import install as install_command_authority
    install_command_authority(app)
    logging.info("PRODUCTION CUTOVER FINAL active: speaker=canonical management=canonical result=canonical attendance=canonical seats=canonical commands=canonical")
    _INSTALLED=True


def _wrap_final_installer(module_name: str, function_name: str = "install") -> None:
    module=__import__(module_name,fromlist=[function_name]); original=getattr(module,function_name); marker=f"_production_cutover_wrapped_{function_name}"
    if getattr(module,marker,False): return
    def wrapped(app,*args,**kwargs):
        result=original(app,*args,**kwargs); _finalize(app); return result
    wrapped.__name__=getattr(original,"__name__",function_name); wrapped.__doc__=getattr(original,"__doc__",None)
    setattr(module,function_name,wrapped); setattr(module,marker,True)


def install() -> None:
    if _production_app() is None: return
    _protect_legacy_management_assignment(); _wrap_final_installer("runtime.game_info_security_v2")
    app=_production_app()
    if app is not None and not getattr(app,"_production_cutover_final",False): _finalize(app)
