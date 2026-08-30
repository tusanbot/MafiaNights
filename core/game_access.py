from dataclasses import dataclass
from enum import Enum


class GameRole(str, Enum):
    MODERATOR = "moderator"
    PLAYER = "player"
    SPECTATOR = "spectator"


@dataclass(frozen=True)
class GameAccess:
    user_id: int
    game_id: int
    role: GameRole

    def can_manage_game(self) -> bool:
        return self.role is GameRole.MODERATOR

    def can_read_private_state(self) -> bool:
        # Private role/state must never be exposed to ordinary players.
        return self.role is GameRole.MODERATOR

    def can_read_public_state(self) -> bool:
        return self.role in (GameRole.MODERATOR, GameRole.PLAYER, GameRole.SPECTATOR)
