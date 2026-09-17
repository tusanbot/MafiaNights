"""Final production-runtime cutover for the Vercel Telegram entrypoint.

The Vercel webhook uses ``player_runtime_entry`` (main1), while the polling
entrypoint uses ``main.py``.  Keep the production webhook on the same final
runtime authorities without duplicating another UI implementation.
"""
from __future__ import annotations

import logging
import sys
from typing import Any, Callable


_INSTALLED = False


def _production_app() -> Any | None:
    module = sys.modules.get("player_runtime_entry")
    return getattr(module, "main", None) if module is not None else None


def _protect_legacy_management_assignment() -> None:
    """Do not let player_runtime_entry replace the final management panel.

    Its old compatibility surface is still executed for other handlers, but
    once the canonical final surface is installed, its later ``panel = ...``
    assignment must be ignored.
    """
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


def _finalize(app: Any) -> None:
    global _INSTALLED
    if app is None:
        return
    if getattr(app, "_production_cutover_final", False):
        return
    app._production_cutover_final = True

    # The role selector must persist the moderator's human-readable identity.
    from runtime.final_identity_authority import install as install_identity
    install_identity(app)

    # Manual head/speaker selection is the sole source of the normal turn order.
    from runtime.speaker_order_authority import install as install_speaker
    install_speaker(app)

    # Final result/history/events callbacks and moderator hydration must be the
    # highest-priority handlers in the Vercel runtime as well.
    from runtime.production_consistency_loader import install as install_consistency
    install_consistency(app)

    # Keep the final winner/scoring compatibility layer active on this entrypoint.
    from runtime.dual_winner_support import install as install_dual_winner
    install_dual_winner(app)

    logging.info("PRODUCTION CUTOVER FINAL active: speaker=canonical management=canonical result=canonical")
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
    """Install hooks early; execute the final cutover after the last UI installer."""
    if _production_app() is None:
        return

    _protect_legacy_management_assignment()

    # game_info_security_v2 is the last production runtime installer before
    # player_runtime_entry's legacy management compatibility block.
    _wrap_final_installer("runtime.game_info_security_v2")

    # Ensure the final cutover also happens if that installer is skipped in a
    # future production composition.
    app = _production_app()
    if app is not None and not getattr(app, "_production_cutover_final", False):
        logging.info("PRODUCTION CUTOVER FINAL hooks armed")
