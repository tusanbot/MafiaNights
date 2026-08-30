from runtime.lobby_migration import LobbyMigration


class FakeRuntime:
    def __init__(self):
        self.calls = []

    def ensure(self, *args, **kwargs):
        self.calls.append(("ensure", args, kwargs))
        return {"id": "game-1"}

    def join(self, **kwargs):
        self.calls.append(("join", kwargs))
        return {"game_id": "game-1", "player_id": kwargs["player_id"], "seat": kwargs["seat"]}

    def set_moderator(self, group_id, moderator_id):
        self.calls.append(("moderator", group_id, moderator_id))
        return True

    def set_scenario(self, group_id, scenario_id):
        self.calls.append(("scenario", group_id, scenario_id))
        return True

    def snapshot(self, group_id):
        self.calls.append(("snapshot", group_id))
        return {"game": {"id": "game-1"}, "players": []}

    def persist_legacy_state(self, group_id, **kwargs):
        self.calls.append(("persist", group_id, kwargs))
        return True


def test_lobby_migration_delegates_without_duplicate_state():
    runtime = FakeRuntime()
    migration = LobbyMigration(runtime)

    assert migration.open(100, moderator_id=7)["id"] == "game-1"
    assert migration.join(100, 42, seat=3)["player_id"] == 42
    assert migration.set_moderator(100, 9) is True
    assert migration.set_scenario(100, "classic") is True
    assert migration.snapshot(100)["game"]["id"] == "game-1"
    assert migration.persist_legacy(100, legacy_state={"lobby_active": True}) is True

    assert [c[0] for c in runtime.calls] == [
        "ensure", "join", "moderator", "scenario", "snapshot", "persist"
    ]
