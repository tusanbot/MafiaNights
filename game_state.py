from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set


@dataclass
class GameState:
    """Runtime state container for one Mafia game.

    This is intentionally an in-memory compatibility layer for the current
    main.py. It does not change persistence yet; the next migration can map
    these fields to Supabase without changing handlers again.
    """
    group_chat_id: Optional[int] = None
    moderator_id: Optional[int] = None
    selected_scenario: Optional[str] = None
    game_message_id: Optional[int] = None
    lobby_message_id: Optional[int] = None
    game_running: bool = False
    lobby_active: bool = False
    players: Dict[int, str] = field(default_factory=dict)
    player_slots: Dict[int, int] = field(default_factory=dict)
    turn_order: List[int] = field(default_factory=list)
    current_turn_index: int = 0
    current_turn_message_id: Optional[int] = None
    challenge_requests: Dict[Any, Any] = field(default_factory=dict)
    pending_challenges: Dict[Any, Any] = field(default_factory=dict)
    active_challenger_seats: Set[int] = field(default_factory=set)
    challenge_mode: bool = False
    paused_main_player: Optional[int] = None
    paused_main_duration: Optional[int] = None
    challenges: Dict[Any, Any] = field(default_factory=dict)
    challenge_active: bool = True
    post_challenge_advance: bool = False
    substitute_list: Dict[Any, Any] = field(default_factory=dict)
    players_in_game: Dict[Any, Any] = field(default_factory=dict)
    removed_players: Dict[Any, Any] = field(default_factory=dict)
    waiting_message_id: Optional[int] = None
    waiting_list: List[Dict[str, Any]] = field(default_factory=list)
    extra_turns: List[int] = field(default_factory=list)
    last_next_time: float = 0.0
    next_by_players_enabled: bool = True
    next_by_moderator_enabled: bool = True
    last_role_map: Dict[int, str] = field(default_factory=dict)

    def reset_round(self) -> None:
        self.current_turn_index = 0
        self.turn_order.clear()
        self.challenge_requests.clear()
        self.active_challenger_seats.clear()
        self.paused_main_player = None
        self.paused_main_duration = None
        self.post_challenge_advance = False
        self.pending_challenges.clear()


# Single default state for the current single-group runtime.
# It will later be replaced by a repository-backed per-game state store.
game_state = GameState()
