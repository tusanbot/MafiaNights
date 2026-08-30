from __future__ import annotations

from typing import Any


class ChallengeService:
    """Application boundary for persistent challenge state."""

    ALLOWED_MODES = {"before", "after"}
    ALLOWED_STATUSES = {"pending", "accepted", "rejected", "resolved", "cancelled"}

    def __init__(self, challenge_repository):
        self.repo = challenge_repository

    def create(self, *, game_id: str, challenger_id: int, target_id: int,
               mode: str, status: str = "pending"):
        if not game_id:
            raise ValueError("game_id الزامی است")
        if int(challenger_id) == int(target_id):
            raise ValueError("بازیکن نمی‌تواند خودش را به چالش بکشد")
        if mode not in self.ALLOWED_MODES:
            raise ValueError(f"حالت Challenge نامعتبر است: {mode}")
        if status not in self.ALLOWED_STATUSES:
            raise ValueError(f"وضعیت Challenge نامعتبر است: {status}")
        return self.repo.create_challenge(
            game_id=game_id,
            challenger_id=int(challenger_id),
            target_id=int(target_id),
            mode=mode,
            status=status,
        )

    def resolve(self, challenge_id: str, status: str) -> bool:
        if status not in {"accepted", "rejected", "resolved", "cancelled"}:
            raise ValueError(f"وضعیت نهایی Challenge نامعتبر است: {status}")
        return bool(self.repo.resolve_challenge(challenge_id, status))

    def for_game(self, game_id: str) -> list[dict[str, Any]]:
        return self.repo.list_challenges(game_id)

    def pending(self, game_id: str) -> list[dict[str, Any]]:
        return [row for row in self.for_game(game_id) if row.get("status") == "pending"]
