import pytest

from handlers.runtime_adapter import RuntimeAdapter
from runtime.game_state_machine import GameStateMachine, Phase


class DummyRuntime:
    def snapshot(self, game_id):
        return {"game_id": game_id}

    def recover(self, game_id):
        return {"game_id": game_id}


def test_adapter_does_not_await_sync_runtime():
    async def run():
        adapter = RuntimeAdapter(DummyRuntime())
        assert await adapter.snapshot(12) == {"game_id": 12}
        assert await adapter.recover(12) == {"game_id": 12}

    import asyncio
    asyncio.run(run())


def test_paused_is_first_class_phase():
    assert Phase.PAUSED.value == "paused"


def test_paused_transition_contract():
    class Games:
        def update_game(self, *args, **kwargs):
            return None

    class State:
        games = Games()

        def active_game(self, group_chat_id):
            return {"id": "game-1", "status": "paused"}

    machine = GameStateMachine(State())
    result = machine.transition(1, Phase.TURN)
    assert result.previous_phase is Phase.PAUSED
    assert result.phase is Phase.TURN


def test_invalid_transition_from_finished():
    class Games:
        def update_game(self, *args, **kwargs):
            return None

    class State:
        games = Games()

        def active_game(self, group_chat_id):
            return {"id": "game-1", "status": "finished"}

    machine = GameStateMachine(State())
    with pytest.raises(ValueError):
        machine.transition(1, Phase.TURN)
