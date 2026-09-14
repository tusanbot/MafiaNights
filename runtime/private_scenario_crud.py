"""Private scenario CRUD bridge using the canonical scenario repository/form flow."""
from __future__ import annotations

from runtime.scenario_management_v3 import ScenarioManagementV3, ScenarioForm


def _handler(item):
    return getattr(item, "handler", None) or getattr(item, "callback", None)


async def _private_admin(self, obj):
    message = getattr(obj, "message", None)
    chat = getattr(message, "chat", None) if message else getattr(obj, "chat", None)
    if not chat or chat.type != "private":
        return False
    uid = int(obj.from_user.id)
    if uid == int(getattr(self.app, "moderator_id", 0) or 0):
        return True
    cached = set()
    for source in (self.app, getattr(self.app, "addons", None)):
        for attr in ("admins", "group_admins"):
            for item in getattr(source, attr, None) or []:
                try:
                    cached.add(int(getattr(getattr(item, "user", None), "id", item)))
                except (TypeError, ValueError):
                    pass
    if uid in cached:
        return True
    gid = getattr(self.app, "ALLOWED_GROUP_ID", None) or getattr(self.app, "GROUP_ID", None) or getattr(self.app, "group_chat_id", None)
    if gid:
        try:
            admins = await self.app.bot.get_chat_administrators(int(gid))
            ids = {int(a.user.id) for a in admins}
            self.app.admins = ids
            self.app.group_admins = list(ids)
            return uid in ids
        except Exception:
            return False
    return False


def _promote_scenario_handlers(dp, manager):
    """Give scenario callbacks/FSM handlers priority over broad text handlers."""
    cq = getattr(dp.callback_query_handlers, "handlers", None)
    mh = getattr(dp.message_handlers, "handlers", None)
    callback_methods = {
        "menu", "view", "start_add", "start_edit", "delete_menu", "delete",
        "delete_confirm", "challenge_mode",
    }
    state_methods = {
        "name", "description", "min_players", "max_players", "roles",
        "role_sides", "challenge_limit", "settings",
    }
    if cq is not None:
        owned = [h for h in list(cq) if getattr(_handler(h), "__self__", None) is manager and getattr(_handler(h), "__name__", "") in callback_methods]
        if owned:
            cq[:] = owned + [h for h in list(cq) if h not in owned]
    if mh is not None:
        owned = [h for h in list(mh) if getattr(_handler(h), "__self__", None) is manager and getattr(_handler(h), "__name__", "") in state_methods]
        if owned:
            mh[:] = owned + [h for h in list(mh) if h not in owned]


def install(app):
    if getattr(app, "_private_scenario_crud_installed", False):
        return False
    manager = ScenarioManagementV3(app)
    manager._admin = _private_admin.__get__(manager, ScenarioManagementV3)
    manager.register(app.dp)
    _promote_scenario_handlers(app.dp, manager)
    app._private_scenario_manager = manager
    app._private_scenario_crud_installed = True
    return manager
