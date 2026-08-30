from handlers.turn import TurnHandler
from handlers.challenge import ChallengeHandler
from handlers.lobby import LobbyHandler


class StubTurnRuntime:
    def start(self, *args, **kwargs): return (args, kwargs)
    def finish(self, *args, **kwargs): return (args, kwargs)
    def current(self, *args, **kwargs): return (args, kwargs)
    def history(self, *args, **kwargs): return (args, kwargs)
    def recover(self, *args, **kwargs): return (args, kwargs)


class StubChallengeRuntime:
    def create(self, *args, **kwargs): return (args, kwargs)
    def resolve(self, *args, **kwargs): return (args, kwargs)
    def pending(self, *args, **kwargs): return (args, kwargs)
    def history(self, *args, **kwargs): return (args, kwargs)


def test_turn_handler_forwards_without_own_state():
    runtime = StubTurnRuntime()
    handler = TurnHandler(runtime)
    result = handler.start(10, 1, seat=2, player_id=99, duration_seconds=120)
    assert result[0] == (10, 1)
    assert result[1]["seat"] == 2
    assert result[1]["duration_seconds"] == 120


def test_challenge_handler_forwards_pause_contract():
    runtime = StubChallengeRuntime()
    handler = ChallengeHandler(runtime)
    result = handler.create(10, 11, 12, "before", pause_main_turn=True,
                            pause_state={"remaining": 90})
    assert result[0] == (10, 11, 12, "before")
    assert result[1]["pause_main_turn"] is True
    assert result[1]["pause_state"]["remaining"] == 90


def test_lobby_handler_exists_as_persistent_boundary():
    assert LobbyHandler is not None
