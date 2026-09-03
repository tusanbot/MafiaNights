"""Small persistence adapter for runtime feature state.

Feature-specific runtime flags belong to the persistent active-game state,
not to module-level globals. This adapter provides the legacy helpers used by
contract tests and by integrations that still need them.
"""
from __future__ import annotations


class FeatureParity:
    def __init__(self, app):
        self.app = app

    def _game(self, group_id):
        return self.app.runtime.state.active_game(group_id) or {}

    def _state(self, group_id):
        game = self._game(group_id)
        state = game.get("state") or {}
        if not isinstance(state, dict):
            state = {}
        return state

    def _next_settings(self, group_id):
        value = self._state(group_id).get("next_settings") or {}
        return dict(value)

    def _substitutes(self, group_id):
        value = self._state(group_id).get("substitutes") or {}
        return dict(value)

    def _removed(self, group_id):
        value = self._state(group_id).get("removed_players") or {}
        return dict(value)

    def _save_state(self, group_id, *, next_settings=None, substitutes=None, removed_players=None):
        current = self._state(group_id)
        if next_settings is not None:
            current["next_settings"] = dict(next_settings)
        if substitutes is not None:
            current["substitutes"] = dict(substitutes)
        if removed_players is not None:
            current["removed_players"] = dict(removed_players)
        self.app.runtime.state.games.update_game(group_id, state=current)
        return True
