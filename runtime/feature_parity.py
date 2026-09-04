"""Persistent feature-state adapter for the clean Mafia runtime."""
from __future__ import annotations

from aiogram.dispatcher.filters.state import State, StatesGroup


class AddScenarioParity(StatesGroup):
    waiting_for_name = State()
    waiting_for_roles = State()
    waiting_for_min_players = State()


class FeatureParity:
    def __init__(self, app):
        self.app = app

    def _game(self, group_id):
        return self.app.runtime.state.active_game(group_id) or {}

    def _state(self, group_id):
        game = self._game(group_id)
        state = game.get("state") or {}
        return dict(state) if isinstance(state, dict) else {}

    def _next_settings(self, group_id):
        return dict(self._state(group_id).get("next_settings") or {})

    def _substitutes(self, group_id):
        return dict(self._state(group_id).get("substitutes") or {})

    def _removed(self, group_id):
        return dict(self._state(group_id).get("removed_players") or {})

    def _save_state(self, group_id, *, next_settings=None, substitutes=None, removed_players=None, **extra):
        current = self._state(group_id)
        if next_settings is not None:
            current["next_settings"] = dict(next_settings)
        if substitutes is not None:
            current["substitutes"] = dict(substitutes)
        if removed_players is not None:
            current["removed_players"] = dict(removed_players)
        current.update(extra)
        self.app.runtime.state.games.update_game(group_id, state=current)
        return True
