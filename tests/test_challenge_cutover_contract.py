from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_challenge_runtime_supports_request_activation_and_resolution():
    source = read("runtime/challenge_runtime.py")
    assert "def request(" in source
    assert "def activate(" in source
    assert "def resolve(" in source
    assert "self.challenges.update_mode" in source


def test_challenge_persistence_supports_mode_updates():
    source = read("repositories/challenge_repository.py")
    service = read("services/challenge_service.py")
    assert "def update_mode(" in source
    assert "set mode = :mode" in source
    assert "def update_mode(" in service


def test_legacy_challenge_callbacks_are_bridged():
    source = read("runtime/challenge_cutover.py")
    assert "bridged_challenge_request" in source
    assert "bridged_challenge_response" in source
    assert "install_legacy_challenge_cutover" in source
    assert "runtime.request" in source
    assert "runtime.activate" in source


def test_turn_cutover_installs_challenge_and_resolves_challenge_turns():
    source = read("runtime/turn_cutover.py")
    assert "install_legacy_challenge_cutover" in source
    assert 'current.get("turn_type") == "challenge"' in source
    assert 'challenge_runtime.resolve' in source
