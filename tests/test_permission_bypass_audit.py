"""Regression contracts for the final moderator permission boundary."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_sensitive_text_commands_do_not_fallback_to_group_admins():
    source = read("commands.py")
    start = source.index("async def _simple_phase")
    end = source.index("async def _attendance_text")
    block = source[start:end]
    assert "await _manager(app, message, game)" not in block
    assert "_authorized(app, message)" in block


def test_finish_and_cancel_text_surfaces_are_moderator_only():
    source = read("runtime/end_game_control.py")
    assert 'allowed = uid == int(game.get("moderator_id") or 0)' in source
    assert 'get_chat_member(gid, uid)' not in source[source.index("async def finish_command"):source.index("async def _allowed")]

    source = read("runtime/cancel_command.py")
    assert 'uid != moderator' in source
    assert 'get_chat_member(gid, uid)' not in source


def test_legacy_callback_authorization_marks_sensitive_controls_moderator_only():
    source = read("runtime/callback_authorization.py")
    block = source[source.index("_MODERATOR_ONLY_EXACT"):source.index("_MODERATOR_ONLY_PREFIXES")]
    for name in ("choose_head", "challenge_toggle", "speaker_auto", "speaker_manual"):
        assert f'"{name}"' in block


def test_command_surface_v3_requires_moderator_for_sensitive_commands():
    source = read("runtime/command_surface_v3.py")
    assert 'if c in {"vote","end","chief","start"} and not await moderator(m,g):' in source
    assert 'str(g.get("status") or "") != "lobby" and not await moderator(m,g)' in source
