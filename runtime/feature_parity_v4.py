"""Feature-parity v4.

Lobby ownership is intentionally absent here. The production lobby is owned
exclusively by ``runtime.production_lobby``; this layer extends the
non-lobby feature parity surface and applies scenario-specific challenge
quotas.
"""
from __future__ import annotations

from runtime.feature_parity_v3 import FeatureParityV3
from runtime.scenario_challenge_policy import ScenarioChallengePolicy


class FeatureParityV4(FeatureParityV3):
    """Final feature-parity layer with scenario-aware challenge quotas."""

    def __init__(self, app):
        super().__init__(app)
        self.challenge_policy = ScenarioChallengePolicy(app)

    async def challenge_request(self, callback):
        group_id = int(callback.message.chat.id)
        challenger = int(callback.from_user.id)

        allowed, reason, key = self.challenge_policy.check(group_id, challenger)
        if not allowed:
            await callback.answer(reason, show_alert=True)
            return

        # The base handler performs the existing target/pending/enable checks
        # and creates the challenge request. Mark the quota only after those
        # validations have passed so a malformed request does not consume it.
        await super().challenge_request(callback)
        mode = self.challenge_policy.mode(group_id)
        self.challenge_policy.mark(group_id, challenger, key, mode)

    def register(self):
        super().register()
