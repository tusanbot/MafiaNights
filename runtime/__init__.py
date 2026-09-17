from .game_state import GameState

# The Vercel Telegram webhook uses player_runtime_entry/main1 rather than the
# polling main.py entrypoint. Arm the same final production authorities there.
try:
    from . import production_cutover_final
    production_cutover_final.install()
except Exception:
    import logging
    logging.exception("Failed to arm production cutover hooks")

__all__ = ["GameState"]
