from types import SimpleNamespace

from runtime.legacy_global_audit import inspect_module, assert_not_authoritative


def test_legacy_containers_are_never_authoritative():
    main = SimpleNamespace(
        players={},
        player_slots={},
        turn_order=[],
        pending_challenges={},
    )

    report = inspect_module(main)

    assert report["source_of_truth"] == "persistent_runtime"
    assert report["authoritative"] is False
    assert set(report["legacy_container_names_present"]) == {
        "players",
        "player_slots",
        "turn_order",
        "pending_challenges",
    }

    assert_not_authoritative(main)
    assert main.LEGACY_GLOBAL_AUDIT["authoritative"] is False


def test_explicit_authoritative_flag_is_rejected():
    main = SimpleNamespace(LEGACY_GLOBALS_ARE_AUTHORITATIVE=True)

    try:
        assert_not_authoritative(main)
    except AssertionError as exc:
        assert "must not be marked authoritative" in str(exc)
    else:
        raise AssertionError("legacy authoritative flag was not rejected")
