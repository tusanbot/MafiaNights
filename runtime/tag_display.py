"""Central Custom Emoji presentation helpers."""
from __future__ import annotations

import html
import re
from typing import Any, Mapping

# Known Telegram custom-emoji IDs already validated for the bot's emoji set.
# Unsupported symbols intentionally fall back to their normal Unicode form.
CUSTOM_EMOJI_IDS = {
    "🔥": "5420315771991497307",
    "👑": "5467406098367521267",
    "🏆": "5409008750893734809",
    "⚔️": "5408935401442267103",
}

TAG_CUSTOM_EMOJI_IDS = CUSTOM_EMOJI_IDS

_CUSTOM_EMOJI_PATTERN = re.compile(
    "|".join(
        re.escape(x)
        for x in sorted(CUSTOM_EMOJI_IDS, key=len, reverse=True)
    )
) if CUSTOM_EMOJI_IDS else None


def render_custom_emoji_text(text: str, *, enabled: bool = True) -> str:
    """Convert supported Unicode emoji in already-HTML text to tg-emoji tags."""
    if not enabled or not text or _CUSTOM_EMOJI_PATTERN is None:
        return text

    # Never touch an already-rendered custom emoji block.
    parts = re.split(r"(<tg-emoji\\b[^>]*>.*?</tg-emoji>)", text, flags=re.DOTALL)
    for i in range(0, len(parts), 2):
        parts[i] = _CUSTOM_EMOJI_PATTERN.sub(
            lambda m: f'<tg-emoji emoji-id="{CUSTOM_EMOJI_IDS[m.group(0)]}">{html.escape(m.group(0))}</tg-emoji>',
            parts[i],
        )
    return "".join(parts)


def tag_prefix_html(tag: Mapping[str, Any] | None, *, custom_emoji_enabled: bool = True) -> str:
    if not tag:
        return ""
    emoji = str(tag.get("emoji") or "").strip()
    if not emoji:
        return ""
    if not custom_emoji_enabled:
        return f"{html.escape(emoji)} "
    custom_id = CUSTOM_EMOJI_IDS.get(emoji)
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


def custom_emoji_enabled_for_chat(app: Any, chat_id: int | None) -> bool:
    try:
        addons = getattr(app, "addons", None)
        if addons is None:
            return True
        gid = chat_id or getattr(addons, "group_id", None) or getattr(app, "group_chat_id", None) or getattr(app, "ALLOWED_GROUP_ID", None)
        if gid:
            settings = addons.get_group_settings(int(gid)) or {}
            return bool(settings.get("visual", {}).get("achievement_custom_emoji", True))
    except Exception:
        # Presentation must never break the game if settings are unavailable.
        return False
    return True


def custom_emoji_enabled_for_app(app: Any) -> bool:
    return custom_emoji_enabled_for_chat(app, None)
