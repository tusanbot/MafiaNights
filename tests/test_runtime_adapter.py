from handlers.runtime_adapter import RuntimeAdapter


class FakeRuntime:
    async def snapshot(self, game_id): return {"game_id": game_id}
    async def recover(self, game_id): return {"game_id": game_id, "recovered": True}
    async def join(self, game_id, player_id, **player): return (game_id, player_id, player)
    async def leave(self, game_id, player_id): return (game_id, player_id)
    async def start_turn(self, game_id, seat, duration_seconds): return (game_id, seat, duration_seconds)
    async def finish_turn(self, game_id, turn_id): return (game_id, turn_id)
    async def create_challenge(self, game_id, challenger_id, target_id, mode): return (game_id, challenger_id, target_id, mode)
    async def resolve_challenge(self, game_id, challenge_id, status): return (game_id, challenge_id, status)


def test_adapter_exposes_persistent_runtime_contract():
    adapter = RuntimeAdapter(FakeRuntime())
    assert adapter.runtime is not None
    assert callable(adapter.snapshot)
    assert callable(adapter.recover)
    assert callable(adapter.join)
    assert callable(adapter.leave)
    assert callable(adapter.start_turn)
    assert callable(adapter.finish_turn)
    assert callable(adapter.create_challenge)
    assert callable(adapter.resolve_challenge)
