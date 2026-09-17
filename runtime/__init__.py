from .game_state import GameState

# Do not initialize production cutover here. runtime/__init__.py is executed
# while player_runtime_entry is still being imported, before that module has
# created its `main` object and before its final installers have run. The old
# eager hook therefore saw no production app and became a permanent no-op.
# The production entrypoint explicitly arms the cutover after all installers.

__all__ = ["GameState"]
