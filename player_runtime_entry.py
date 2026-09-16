"""Production entry point for the persistent MafiaNights runtime."""
import logging
from types import SimpleNamespace
import main1 as main
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.dispatcher.handler import CancelHandler
from runtime.production_bridge import install as install_persistent_bridge, startup as persistent_startup
from player_service import player_service
from runtime.webhook_safety import install_latency, install_safe_callback_answer
install_safe_callback_answer(); _bridge=install_persistent_bridge(main); main.player_service=player_service; install_latency(main.dp)
logging.info("PERSISTENCE_OPTIMIZATION_ACTIVE pool=serverless-safe identity-cache=60s active-game-cache=0.75s")
logging.info("PRODUCTION_FAST_PATH active=1 legacy-lobby-middleware=off legacy-state-middleware=off identity-bridge=off")
from runtime.postgres_fsm_storage import install as install_postgres_fsm_storage
install_postgres_fsm_storage(main)
from runtime.scenario_persistence_patch import install as install_scenario_persistence_patch
install_scenario_persistence_patch(main)
from runtime.game_ui_bugfixes import install as install_game_ui_bugfixes
install_game_ui_bugfixes(main)
from runtime.production_fastpath import install as install_production_fastpath
install_production_fastpath(main)
from runtime.lobby_ui_final import install as install_final_lobby
install_final_lobby(main)
from runtime.game_management import GameManagement
main.game_management = GameManagement(main)
main.game_management.install()
from runtime.end_game_control import install as install_manual_end_game
install_manual_end_game(main)
# role_distribution expects the legacy gameplay bridge object to exist. Keep the
# compatibility object without replacing any desktop/runtime UI implementation.
if not hasattr(main, "ui") or main.ui is None:
    main.ui = SimpleNamespace()
from runtime.role_distribution import install as install_role_distribution
install_role_distribution(main)
main._canonical_distribute_roles = main._role_distribution_handler
if getattr(main, "_render_final_lobby", None):
    main._render_production_lobby = main._render_final_lobby
from runtime.game_flow_ui_v2 import install as install_game_flow_ui_v2
install_game_flow_ui_v2(main)
from runtime.game_flow_authority import install as install_game_flow_authority
game_flow_authority=install_game_flow_authority(main)
from runtime.challenge_authority import install as install_challenge_authority
install_challenge_authority(main)
from runtime.callback_authorization import install as install_callback_authorization
install_callback_authorization(main)
from runtime.final_runtime_guard import install as install_final_runtime_guard
install_final_runtime_guard(main)
from runtime.seat_emoji_patch import install as install_seat_emoji_patch
install_seat_emoji_patch(main)
from runtime.user_panel import install as install_user_panel
user_panel=install_user_panel(main)
from runtime.start_profile_patch import install as install_start_profile_patch
install_start_profile_patch(main)
from runtime.user_panel_back_patch import install as install_user_panel_back_patch
install_user_panel_back_patch(main,user_panel)
from runtime.profile_schema_compat import install as install_profile_schema_compat
install_profile_schema_compat(main)
from runtime.profile_enhancements_fixed import install as install_profile_enhancements
profile_enhancements=install_profile_enhancements(main,user_panel); main.profile_enhancements=profile_enhancements
from runtime.profile_db_compat import install as install_profile_db_compat
install_profile_db_compat(profile_enhancements)
from commands import register_commands as register_text_commands
register_text_commands(main)
from runtime.command_surface_v2 import install as install_command_surface_v2
install_command_surface_v2(main)
from runtime.addons_persistence_patch import install as install_addons_persistence_patch
install_addons_persistence_patch(main)
from runtime.addons_menu_v2 import install as install_addons_menu_v2
install_addons_menu_v2(main)
from runtime.private_scenario_crud import install as install_private_scenario_crud
install_private_scenario_crud(main)
from runtime.stable_round_engine import install as install_stable_round_engine
from runtime.live_controls_v2 import install as install_live_controls_v2
from runtime.lobby_challenge_v2 import install as install_lobby_challenge_v2
from runtime.stable_round_policy import install as install_stable_round_policy
from runtime.stable_challenge_button_guard import install as install_stable_challenge_button_guard
from runtime.transition_ui_dedup import install as install_transition_ui_dedup
from runtime.voting_runtime import install as install_voting_runtime
install_stable_round_engine(main); install_live_controls_v2(main); install_lobby_challenge_v2(main); install_stable_round_policy(main); install_stable_challenge_button_guard(main); install_transition_ui_dedup(main); install_voting_runtime(main)
from runtime.game_info_security_v2 import install as install_game_info_security_v2
install_game_info_security_v2(main)


def _install_canonical_management_surface():
    """Keep one group-management surface and remove dead/duplicate entries."""
    management = getattr(main, "game_management", None)
    if management is None or getattr(main, "_canonical_management_surface", False):
        return
    main._canonical_management_surface = True
    original_panel = management.panel

    def panel(game_id):
        original = original_panel(game_id)
        # Rebuild from the existing functional controls, deliberately dropping
        # the dead refresh/close actions. No lobby implementation is duplicated.
        keep = []
        seen_callbacks = set()
        blocked_text = {"🔄 بازسازی لابی", "✖️ بستن", "بازی های گذشته", "📚 بازی های گذشته", "ثبت اتفاقات", "📝 ثبت اتفاقات"}
        for row in getattr(original, "inline_keyboard", []):
            out = []
            for button in row:
                text = str(getattr(button, "text", ""))
                data = getattr(button, "callback_data", None)
                if text in blocked_text:
                    continue
                if data in seen_callbacks:
                    continue
                seen_callbacks.add(data)
                out.append(button)
            if out:
                keep.append(out)

        # Add the controls requested for the canonical management panel.
        def add(text, action):
            keep.append([InlineKeyboardButton(text, callback_data=f"mgmt:{int(game_id)}:{action}")])

        add("ℹ️ اطلاعات بازی", "info")
        add("🦵 کیک از بازی", "kick")
        add("⚠️ تذکر بازیکن", "warning")
        add("⬅️ بازگشت به لابی", "back_lobby")
        return InlineKeyboardMarkup(inline_keyboard=keep)

    management.panel = panel

    async def info(callback):
        gid = int(callback.message.chat.id)
        game = management._game(gid)
        if not game or not await management._allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید یا بازی فعال نیست.", show_alert=True); return
        rows = management._rows(game)
        state = management._state(game)
        await callback.message.edit_text(
            f"ℹ️ <b>اطلاعات بازی {int(game.get('event_number') or 1)}</b>\n\n"
            f"📌 وضعیت: <b>{str(game.get('status') or '---')}</b>\n"
            f"👥 بازیکنان: <b>{sum(1 for r in rows if r.get('seat') is not None)}</b>\n"
            f"🎩 گرداننده: <b>{int(game.get('moderator_id') or 0)}</b>\n"
            f"📅 روز: <b>{int(game.get('current_day') or 0)}</b>\n"
            f"🌙 دور: <b>{int(game.get('current_round') or 0)}</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("⬅️ مدیریت بازی", callback_data=f"mgmt:{int(game['id'])}:open")),
        )
        await callback.answer()

    async def player_picker(callback, action, title):
        gid = int(callback.message.chat.id); game = management._game(gid)
        if not game or not await management._allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید یا بازی فعال نیست.", show_alert=True); return
        rows = [r for r in management._rows(game) if r.get("seat") is not None and str(r.get("status") or "") not in {"removed", "dead", "finished"}]
        kb = InlineKeyboardMarkup(row_width=2)
        for row in rows:
            uid = int(row["player_id"]); seat = int(row.get("seat") or 0)
            name = management._name(row)
            kb.insert(InlineKeyboardButton(f"{seat:02d}. {name}", callback_data=f"mgmt:{int(game['id'])}:{action}_pick:{uid}"))
        kb.row(InlineKeyboardButton("⬅️ مدیریت", callback_data=f"mgmt:{int(game['id'])}:open"))
        await callback.message.edit_text(title, parse_mode="HTML", reply_markup=kb)
        await callback.answer()

    async def kick(callback):
        await player_picker(callback, "kick", "🦵 <b>کیک از بازی</b>\n\nبازیکن موردنظر را انتخاب کنید:")

    async def kick_pick(callback):
        parts = str(callback.data or "").split(":")
        if len(parts) != 4: return
        gid = int(callback.message.chat.id); uid = int(parts[3]); game = management._game(gid)
        if not game or not await management._allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        row = next((r for r in management._rows(game) if int(r["player_id"]) == uid), None)
        if not row or row.get("seat") is None:
            await callback.answer("❌ بازیکن پیدا نشد.", show_alert=True); return
        management.app.runtime.state.games.set_player_seat(game["id"], uid, None)
        management.app.runtime.state.games.set_player_status(game["id"], uid, "kicked")
        alive = getattr(management.app.runtime.state.games, "set_player_alive", None)
        if alive: alive(game["id"], uid, False)
        state = management._state(game); kicks = dict(state.get("kicks") or {}); kicks[str(uid)] = int(kicks.get(str(uid), 0)) + 1
        management._save(game, kicks=kicks, warnings=dict(state.get("warnings") or {}))
        await callback.message.edit_text(f"🦵 <b>{management._name(row)}</b> از بازی کیک شد.\n📉 امتیاز منفی کیک در پایان بازی ثبت می‌شود.", parse_mode="HTML", reply_markup=management.panel(game["id"]))
        await callback.answer("🦵 بازیکن از بازی کیک شد.")

    async def warning(callback):
        await player_picker(callback, "warning", "⚠️ <b>تذکر بازیکن</b>\n\nبازیکنی را برای ثبت تذکر انتخاب کنید:")

    async def warning_pick(callback):
        parts = str(callback.data or "").split(":")
        if len(parts) != 4: return
        gid = int(callback.message.chat.id); uid = int(parts[3]); game = management._game(gid)
        if not game or not await management._allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        row = next((r for r in management._rows(game) if int(r["player_id"]) == uid), None)
        if not row:
            await callback.answer("❌ بازیکن پیدا نشد.", show_alert=True); return
        state = management._state(game); warnings = dict(state.get("warnings") or {}); key = str(uid); count = int(warnings.get(key, 0)) + 1; warnings[key] = count
        management._save(game, warnings=warnings)
        penalty = min(count, 5)
        await callback.message.edit_text(f"⚠️ <b>تذکر ثبت شد.</b>\n\n{management._name(row)}\n🔢 تعداد تذکر: <b>{count}</b>\n📉 جریمه این تذکر: <b>-{penalty}</b>", parse_mode="HTML", reply_markup=management.panel(game["id"]))
        await callback.answer("⚠️ تذکر ثبت شد.")

    async def back_lobby(callback):
        gid = int(callback.message.chat.id); game = management._game(gid)
        if not game or not await management._allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید یا بازی فعال نیست.", show_alert=True); return
        renderer = getattr(main, "_render_final_lobby", None)
        if renderer and str(game.get("status") or "") == "lobby":
            try:
                await renderer(callback)
                await callback.answer("⬅️ به لابی برگشتید.")
                return
            except Exception:
                logging.exception("canonical management back-to-lobby failed")
        await callback.answer("ℹ️ بازی در حال اجراست؛ لابی فعال نیست.", show_alert=True)

    async def ready(callback):
        """Authoritative readiness handler; answer Telegram before any DB/edit work."""
        parts = str(callback.data or "").split(":")
        if len(parts) != 3 or parts[0] != "mgmt" or parts[2] != "attendance_ready":
            return
        gid = int(callback.message.chat.id); uid = int(callback.from_user.id); game = management._game(gid)
        if not game:
            await callback.answer("❌ بازی فعالی وجود ندارد.", show_alert=True); raise CancelHandler()
        rows = management._rows(game)
        player = next((r for r in rows if int(r["player_id"]) == uid), None)
        if not player or player.get("seat") is None or str(player.get("status") or "") in {"removed", "dead", "finished", "kicked"}:
            await callback.answer("⛔ فقط بازیکنان حاضر در بازی می‌توانند اعلام آمادگی کنند.", show_alert=True); raise CancelHandler()
        await callback.answer("✅ آمادگی شما ثبت شد")
        state = management._state(game); attendance = dict(state.get("attendance") or {}); attendance[str(uid)] = True
        management._save(game, attendance=attendance, attendance_announced=False)
        message_id = state.get("attendance_message_id") or callback.message.message_id
        active = [r for r in rows if r.get("seat") is not None and str(r.get("status") or "") not in {"removed", "dead", "finished", "kicked"}]
        lines = ["🟢 <b>بازیکنان حاضر در لیست</b>", ""]
        for row in sorted(active, key=lambda r: int(r.get("seat") or 999)):
            mark = "✅" if bool(attendance.get(str(int(row["player_id"])), False)) else "⚪️"
            lines.append(f"{mark} {int(row['seat']):02d}. <a href=\"tg://user?id={int(row['player_id'])}\"><b>{html.escape(management._name(row))}</b></a>")
        kb = InlineKeyboardMarkup(row_width=1).add(InlineKeyboardButton("آماده‌ام ✅", callback_data=f"mgmt:{int(game['id'])}:attendance_ready"))
        try:
            await main.bot.edit_message_text("\n".join(lines) + "\n\nلطفاً برای اعلام حاضری، «آماده‌ام» را بزنید.", gid, int(message_id), parse_mode="HTML", reply_markup=kb)
        except Exception:
            logging.exception("canonical readiness render failed game=%s", game.get("id"))
        raise CancelHandler()

    dp = main.dp
    dp.register_callback_query_handler(info, lambda c: str(c.data or "").startswith("mgmt:") and str(c.data or "").split(":")[2:3] == ["info"], state="*")
    dp.register_callback_query_handler(kick, lambda c: str(c.data or "").startswith("mgmt:") and str(c.data or "").split(":")[2:3] == ["kick"], state="*")
    dp.register_callback_query_handler(kick_pick, lambda c: str(c.data or "").startswith("mgmt:") and str(c.data or "").split(":")[2:3] == ["kick_pick"], state="*")
    dp.register_callback_query_handler(warning, lambda c: str(c.data or "").startswith("mgmt:") and str(c.data or "").split(":")[2:3] == ["warning"], state="*")
    dp.register_callback_query_handler(warning_pick, lambda c: str(c.data or "").startswith("mgmt:") and str(c.data or "").split(":")[2:3] == ["warning_pick"], state="*")
    dp.register_callback_query_handler(back_lobby, lambda c: str(c.data or "").startswith("mgmt:") and str(c.data or "").split(":")[2:3] == ["back_lobby"], state="*")
    dp.register_callback_query_handler(ready, lambda c: str(c.data or "").startswith("mgmt:") and str(c.data or "").endswith(":attendance_ready"), state="*")
    # Put the canonical handlers ahead of legacy management/navigation handlers.
    registry = getattr(getattr(dp, "callback_query_handlers", None), "handlers", [])
    names = {"info", "kick", "kick_pick", "warning", "warning_pick", "back_lobby", "ready"}
    selected = [x for x in registry if getattr(getattr(x, "handler", None) or getattr(x, "callback", None), "__name__", "") in names]
    for item in reversed(selected):
        try:
            registry.remove(item); registry.insert(0, item)
        except ValueError:
            pass

_install_canonical_management_surface()

def _finalize_lobby_routes():
    dp = main.dp
    def handler_of(item):
        return getattr(item, "handler", None) or getattr(item, "callback", None)
    old_callback_names = {"start_game", "choose_scenario", "scenario_selected", "choose_moderator", "moderator_selected", "handle_slot"}
    cr = getattr(getattr(dp, "callback_query_handlers", None), "handlers", [])
    cr[:] = [x for x in cr if getattr(handler_of(x), "__name__", "") not in old_callback_names]
    mr = getattr(getattr(dp, "message_handlers", None), "handlers", [])
    mr[:] = [x for x in mr if getattr(handler_of(x), "__name__", "") != "start_cmd"]
    start_item = next((x for x in mr if getattr(handler_of(x), "__name__", "") == "start_command"), None)
    if start_item is not None:
        mr.remove(start_item)
        mr.insert(0, start_item)
    logging.info("FINAL_LOBBY_ROUTE_CUTOVER applied after all installers")

_finalize_lobby_routes()

_original_startup=main.on_startup
async def on_startup(dp):
    # Startup recovery is auxiliary. A recovery/database failure must never
    # abort Telegram update dispatch on a request-driven Vercel webhook.
    try:
        results=await persistent_startup(main,_original_startup)
        logging.info("Persistent runtime startup recovery completed: %s",results)
    except Exception:
        logging.exception("Persistent runtime startup recovery failed; continuing webhook startup")
    try:
        configured_gid=getattr(main,"ALLOWED_GROUP_ID",None)
        if configured_gid:
            main.group_chat_id=int(configured_gid); admins=await main.bot.get_chat_administrators(main.group_chat_id); main.admins={a.user.id for a in admins}; main.group_admins=list(main.admins)
    except Exception: logging.exception("Failed to initialize private UI group/admin authorization")
    from runtime.final_private_ui import install as install_final_private_ui
    await install_final_private_ui(main)
    from runtime.private_pv_authority_v2 import install as install_canonical_private_pv
    await install_canonical_private_pv(main)
    from runtime.pv_route_priority_v2 import install as install_pv_route_priority
    await install_pv_route_priority(main)
    from runtime.private_ui_recovery_v3 import install as install_private_ui_recovery_v3
    await install_private_ui_recovery_v3(main)
    from runtime.private_ui_recovery_v5 import install as install_private_ui_recovery_v5
    await install_private_ui_recovery_v5(main)
    from runtime.private_ui_recovery_v6 import install as install_private_ui_recovery_v6
    await install_private_ui_recovery_v6(main)
    from runtime.private_ui_recovery_v7 import install as install_private_ui_recovery_v7
    await install_private_ui_recovery_v7(main)
    from runtime.private_ui_recovery_v8 import install as install_private_ui_recovery_v8
    await install_private_ui_recovery_v8(main)
main.on_startup=on_startup