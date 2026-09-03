"""Make the private management controller authoritative in aiogram 2.x.

The dispatcher stores callback handlers in registration order.  Some legacy
modules register broad callbacks such as ``manage_game`` before the clean
private controller is installed.  This module deliberately moves only the
private controller's handlers to the front; it does not invoke or import any
lobby/group handler.
"""


def install(app):
    container = getattr(getattr(app, "dp", None), "callback_query_handlers", None)
    handlers = getattr(container, "handlers", None)
    if not handlers:
        return False

    owned = []
    other = []
    for h in list(handlers):
        cb = getattr(h, "callback", None)
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
