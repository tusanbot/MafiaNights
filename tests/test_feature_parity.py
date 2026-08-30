from __future__ import annotations

from runtime.feature_parity import FeatureParity


class FakeGames:
    def __init__(self):
        self.updated = []

    def update_game(self, game_id, **kwargs):
        self.updated.append((game_id, kwargs))


class FakeState:
    def __init__(self):
        self.games = FakeGames()
        self._game = {
            "id": "g1",
            "status": "running",
            "moderator_id": 10,
            "state": {
                "next_settings": {
                    "allow_players_next": True,
                    "allow_moderator_next": True,
                    "anti_spam": True,
                },
                "substitutes": {},
                "removed_players": {},
            },
        }

    def active_game(self, group_id):
        return self._game


class FakeRuntime:
    def __init__(self):
        self.state = FakeState()


class FakeApp:
    def __init__(self):
        self.runtime = FakeRuntime()


def test_feature_parity_keeps_settings_in_persistent_game_state():
    app = FakeApp()
    parity = FeatureParity(app)
    settings = parity._next_settings(123)
    settings["allow_players_next"] = False
    assert parity._save_state(123, next_settings=settings)
    saved = app.runtime.state.games.updated[-1][1]["state"]
    assert saved["next_settings"]["allow_players_next"] is False


def test_feature_parity_substitute_state_is_not_module_global():
    app = FakeApp()
    parity = FeatureParity(app)
    assert parity._substitutes(123) == {}
    parity._save_state(123, substitutes={"22": {"id": 22, "name": "test"}})
    assert parity._substitutes(123)["22"]["id"] == 22


def test_feature_parity_removed_players_are_persisted():
    app = FakeApp()
    parity = FeatureParity(app)
    parity._save_state(123, removed_players={"3": {"id": 33, "name": "removed"}})
    assert parity._removed(123)["3"]["id"] == 33
