"""Compatibility patch for scenario persistence on serverless runtimes.

The deployed scenarios.json is part of the read-only application bundle. This
patch keeps the existing scenario API intact while preventing an OSError from
breaking the add/edit/delete flows. Durable persistence should eventually move
to the project's database; this module is intentionally small and compatible
with the current main1 handlers.
"""
from __future__ import annotations

import logging


def install(app):
    if getattr(app, "_scenario_persistence_patch_installed", False):
        return False

    original = getattr(app, "save_scenarios", None)
    if original is None:
        logging.warning("scenario persistence patch: save_scenarios is not available")
        return False

    def safe_save_scenarios():
        try:
            result = original()
            return True if result is None else result
        except OSError as exc:
            logging.warning(
                "Scenario persistence skipped because the runtime filesystem is read-only: %s",
                exc,
            )
            return False

    app.save_scenarios = safe_save_scenarios
    app._scenario_persistence_patch_installed = True
    logging.info("Scenario persistence compatibility patch installed")
    return True
