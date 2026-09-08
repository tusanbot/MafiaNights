"""Feature-parity v4.

Lobby ownership is intentionally absent here. The production lobby is owned
exclusively by ``runtime.production_lobby``; this layer only extends the
non-lobby feature parity surface from v3.
"""
from __future__ import annotations

from runtime.feature_parity_v3 import FeatureParityV3


class FeatureParityV4(FeatureParityV3):
    """Final feature-parity layer without legacy lobby registrations."""

    def register(self):
        super().register()
