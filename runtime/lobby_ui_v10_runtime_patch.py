from __future__ import annotations

import logging


def install(main):
    """Bridge v10 lobby settings into existing live-control runtime."""
    if getattr(main, "_lobby_ui_v10_runtime_patch", False):
        return False
    main._lobby_ui_v10_runtime_patch = True

    try:
        if not hasattr(main, "challenge_enabled"):
            main.challenge_enabled = {}
        original = getattr(getattr(main, "scenario_runtime", None), "current", None)
        if original and not getattr(original, "_v10_mode_bridge", False):
            def current(group_id, _original=original):
                row = _original(group_id)
                try:
                    game = main.runtime.state.active_game(int(group_id))
                    settings = dict((game or {}).get("state", {}).get("challenge_settings") or {})
                    if row and "mode" in settings:
                        row = dict(row)
                        row["challenge_mode"] = settings["mode"]
                except Exception:
                    pass
                return row
            current._v10_mode_bridge = True
            main.scenario_runtime.current = current
    except Exception:
        logging.exception("failed to bridge v10 challenge mode")

    return True
