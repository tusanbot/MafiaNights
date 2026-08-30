from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_turn_cutover_module_exists():
    path = ROOT / "runtime" / "turn_cutover.py"
    text = path.read_text(encoding="utf-8")
    assert "install_legacy_turn_cutover" in text
    assert "persistent_countdown" in text
    assert "bridged_next_turn" in text


def test_migration_adapter_finishes_current_turn():
    text = (ROOT / "runtime" / "migration_adapter.py").read_text(encoding="utf-8")
    assert "def finish_current_turn" in text
    assert "finish_reason" in text


def test_addons_installs_turn_cutover():
    text = (ROOT / "mafia_addons.py").read_text(encoding="utf-8")
    assert "_install_turn_cutover" in text
    assert "install_legacy_turn_cutover" in text


def test_no_second_turn_runtime_is_created():
    text = (ROOT / "mafia_addons.py").read_text(encoding="utf-8")
    assert "PersistentTurnRuntime(" not in text
