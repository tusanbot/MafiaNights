from types import SimpleNamespace

from runtime.day_cutover import install_legacy_day_cutover, persist_day_transition


class FakeRuntime:
    def __init__(self):
        self.calls = []

    def start_new_day(self, group_id, **kwargs):
        self.calls.append(("day", group_id, kwargs))
        return {"day": 3, "phase": "day"}

    def start_night(self, group_id, **kwargs):
        self.calls.append(("night", group_id, kwargs))
        return {"day": 3, "phase": "night"}

    def day_snapshot(self, group_id):
        return {"day": 3, "phase": "day"}


def test_persist_day_transition_uses_shared_runtime():
    runtime = FakeRuntime()
    legacy = SimpleNamespace(group_chat_id=10, persistent_runtime=runtime, day_number=0, day_phase=None,
                             current_turn_index=5, turn_order=[2])
    result = persist_day_transition(legacy, phase="day")
    assert result["day"] == 3
    assert runtime.calls[0][0] == "day"
    assert legacy.day_number == 3
    assert legacy.current_turn_index == 0
    assert legacy.turn_order == []


def test_install_wraps_available_day_callbacks():
    events = []

    async def start_new_day(*args, **kwargs):
        events.append("day")

    async def start_night(*args, **kwargs):
        events.append("night")

    runtime = FakeRuntime()
    legacy = SimpleNamespace(
        dp=None,
        persistent_runtime=runtime,
        group_chat_id=10,
        day_number=0,
        day_phase=None,
        current_turn_index=0,
        turn_order=[],
        start_new_day=start_new_day,
        start_night=start_night,
        reset_round_data=lambda: None,
    )
    result = install_legacy_day_cutover(legacy, runtime)
    assert result["cutover"]["start_new_day"] is True
    assert result["cutover"]["start_night"] is True
