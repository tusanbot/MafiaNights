from player_service import player_service


def get_player_name(user_id, fallback="❓"):
    """Return the canonical display name: nickname, real name, username, fallback."""
    return player_service.display_name(user_id, fallback)
