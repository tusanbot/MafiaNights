"""Compatibility shim for the canonical voting engine.

The old timer patch contained a second voting implementation and long-lived
async sleeps. Voting is now owned entirely by runtime.voting_runtime.
"""
from runtime import voting_runtime


def install(main):
    if getattr(main, "_voting_timer_patch_installed", False):
        return False
    main._voting_timer_patch_installed = True
    # Keep the startup contract intact. The real callback router is installed
    # by voting_runtime.install(), immediately before this compatibility shim.
    return True
