"""Achievement-tag display helpers.

Keeps tag presentation separate from gameplay, scoring, and tag state.
Telegram custom emoji are rendered through the HTML tg-emoji tag; when a
custom emoji ID is unavailable or cannot be used, the native emoji remains
as the fallback.
"""
from __future__ import annotations

import html
from typing import Mapping, Any

# Verified IDs from the RestrictedEmoji mapping already used for Mafia Nights.
# Do not invent IDs: unsupported tag emojis deliberately fall back to Unicode.
TAG_CUSTOM_EMOJI_IDS = {
    "🔥": "5420315771991497307",
    "👑": "5467406098367521267",
    "🏆": "5409008750893734809",
    "⚔️": "5408935401442267103",
}


def tag_prefix_html(tag: Mapping[str, Any] | None, *, custom_emoji_enabled: bool = True) -> str:
    if not tag:
        return ""
    emoji = str(tag.get("emoji") or "").strip()
    if not emoji:
        return ""
    if not custom_emoji_enabled:
        return f"{html.escape(emoji)} "
    custom_id = TAG_CUSTOM_EMOJI_IDS.get(emoji)
    if custom_id:
        return f'<tg-emoji emoji-id="{custom_id}">{html.escape(emoji)}</tg-emoji> '
    return f"{html.escape(emoji)} "


def tagged_name_html(
    name: str,
    tag: Mapping[str, Any] | None,
    *,
    custom_emoji_enabled: bool = True,
) -> str:
    return f"{tag_prefix_html(tag, custom_emoji_enabled=custom_emoji_enabled)}{html.escape(str(name))}"


def custom_emoji_enabled_for_app(app: Any) -> bool:
    """Read the persistent add-ons flag without creating a new dependency."""
    try:
        addons = getattr(app, "addons", None)
        gid = (
            getattr(addons, "group_id", None)
            or getattr(app, "group_chat_id", None)
            or getattr(app, "ALLOWED_GROUP_ID", None)
        )
        if addons is not None and gid:
            settings = addons.get_group_settings(int(gid)) or {}
            return bool(settings.get("visual", {}).get("achievement_custom_emoji", True))
    except Exception:
        return True
    return True
