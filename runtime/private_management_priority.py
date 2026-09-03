"""Make the private management controller authoritative in aiogram 2.x.

aiogram 2.x stores callback handlers as Handler objects whose callable is in
``handler`` (not ``callback``). Legacy management handlers are therefore
moved behind the v4 controller by inspecting the actual registered callable.
"""


def install(app):
    container = getattr(getattr(app, "dp", None), "callback_query_handlers", None)
    handlers = getattr(container, "handlers", None)
    if not handlers:
        return False

    owned = []
    other = []
    for h in list(handlers):
        cb = getattr(h, "handler", None)
        module = getattr(cb, "__module__", "")
        if module == "runtime.private_game_management_v4":
            owned.append(h)
        else:
            other.append(h)

    if not owned:
        return False

    handlers[:] = owned + other
    app._private_game_management_priority = True
    return True
