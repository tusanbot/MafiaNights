from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_production_entrypoint_uses_single_lobby_and_management_owner():
    source = (ROOT / "player_runtime_entry.py").read_text(encoding="utf-8")
    assert "runtime.lobby_ui_final" in source
    assert "runtime.management_surface_final" in source
    assert "canonical_lobby_management" not in source
    assert "lobby_final_patch" not in source
    assert "lobby_management_fix" not in source
    assert "management_navigation" not in source


def test_production_cutover_contains_no_lobby_or_management_ui():
    source = (ROOT / "runtime" / "production_cutover_final.py").read_text(encoding="utf-8")
    assert "management_surface_final" not in source
    assert "lobby_ui_final" not in source
    assert "cancel_confirm" not in source
    assert "_install_management_cancel_bridge" not in source


def test_management_surface_owns_panel_navigation_and_cancel_confirmation():
    source = (ROOT / "runtime" / "management_surface_final.py").read_text(encoding="utf-8")
    for token in ("def panel", "cancel_confirm", "cancel_back", "back_lobby"):
        assert token in source
    assert "بازسازی لابی" not in source
    assert "✖️ بستن" not in source


def test_final_lobby_owns_lobby_callbacks_and_ready_state():
    source = (ROOT / "runtime" / "lobby_ui_final.py").read_text(encoding="utf-8")
    for token in ("fl_new", "fl_toggle", "fl_reserve", "fl_manage", "fl_cancel", "ready_players"):
        assert token in source


def test_deleted_duplicate_modules_are_not_imported():
    for path in (
        "runtime/canonical_lobby_management.py",
        "runtime/lobby_final_patch.py",
        "runtime/lobby_management_fix.py",
        "runtime/lobby_migration.py",
        "runtime/management_navigation.py",
    ):
        assert not (ROOT / path).exists()
