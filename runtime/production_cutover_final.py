"""Final production runtime authorities.

This module is deliberately not a lobby or management implementation.
Lobby UI is owned by runtime.lobby_ui_final; management business logic by
runtime.game_management; management UI by runtime.management_surface_final.
"""
from __future__ import annotations

import logging
import sys
from typing import Any

_INSTALLED = False


def _production_app() -> Any | None:
    module = sys.modules.get("player_runtime_entry")
    return getattr(module, "main", None) if module is not None else None


def _finalize(app: Any) -> None:
    global _INSTALLED
    if app is None or getattr(app, "_production_cutover_final", False):
        return
    app._production_cutover_final = True

    # These are orthogonal runtime authorities. None of them installs a
    # competing lobby/management surface.
    from runtime.final_identity_authority import install as install_identity
    from runtime.speaker_order_authority import install as install_speaker
    from runtime.production_consistency_loader import install as install_consistency
    from runtime.dual_winner_support import install as install_dual_winner
    from runtime.lobby_seat_authority import install as install_lobby_seat
    from runtime.command_authority_final import install as install_command_authority

    install_identity(app)
    install_speaker(app)
    install_consistency(app)
    install_dual_winner(app)
    install_lobby_seat(app)
    install_command_authority(app)

    logging.info("PRODUCTION AUTHORITIES active: lobby=single management=single")
    _INSTALLED = True


def install() -> None:
    app = _production_app()
    if app is not None and not getattr(app, "_production_cutover_final", False):
        _finalize(app)
