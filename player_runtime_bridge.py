"""Runtime compatibility layer for player identity/display names.

Keeps legacy main.py state structures usable while routing visible player names
through PlayerService. This is intentionally isolated from the large legacy
main.py so identity changes can be made safely and incrementally.
"""

import copy

from player_service import player_service, display_name, ensure_player


class DisplayPlayers(dict):
    """Legacy {uid: name} mapping with DB-backed display names."""

    def __setitem__(self, user_id, value):
        user_id = int(user_id)
        raw_name = value or "❓"
        player_service.ensure_player_data(user_id, full_name=raw_name)
        super().__setitem__(user_id, raw_name)

    def get(self, user_id, default=None):
        try:
            user_id = int(user_id)
        except (TypeError, ValueError):
            return default
        if user_id not in self:
            return default
        return display_name(user_id, default if default is not None else "❓")

    def __getitem__(self, user_id):
        user_id = int(user_id)
        value = super().__getitem__(user_id)
        return display_name(user_id, value)

    def items(self):
        for user_id in super().keys():
            yield user_id, display_name(user_id, super().__getitem__(user_id))

    def values(self):
        for user_id in super().keys():
            yield display_name(user_id, super().__getitem__(user_id))


class DisplayWaitingList(list):
    """Legacy waiting list whose names are resolved dynamically."""

    @staticmethod
    def _decorate(item):
        if not isinstance(item, dict):
            return item
        result = dict(item)
        uid = result.get("id")
        if uid is not None:
            result["name"] = display_name(uid, result.get("name", "❓"))
        return result

    def append(self, item):
        if isinstance(item, dict) and item.get("id") is not None:
            uid = int(item["id"])
            raw_name = item.get("name") or "❓"
            player_service.ensure_player_data(uid, full_name=raw_name)
            item = dict(item)
            item["id"] = uid
        super().append(item)

    def __getitem__(self, index):
        value = super().__getitem__(index)
        if isinstance(index, slice):
            return [self._decorate(item) for item in value]
        return self._decorate(value)

    def __iter__(self):
        for item in super().__iter__():
            yield self._decorate(item)


class DisplayGroupEntries(dict):
    """A group-level mapping whose player names are resolved by UID.

    Used for legacy substitute_list / removed_players structures where the
    stored record contains {"id": uid, "name": raw_name}.
    """

    def _decorate(self, value):
        if not isinstance(value, dict):
            return value
        result = dict(value)
        uid = result.get("id")
        if uid is not None:
            result["name"] = display_name(uid, result.get("name", "❓"))
        return result

    def __getitem__(self, key):
        value = super().__getitem__(key)
        if isinstance(value, dict) and not isinstance(value, DisplayGroupEntries):
            wrapped = DisplayGroupEntries(value)
            super().__setitem__(key, wrapped)
            value = wrapped
        return value

    def get(self, key, default=None):
        if key not in self:
            return default
        return self[key]

    def items(self):
        for key, value in super().items():
            if isinstance(value, dict) and not isinstance(value, DisplayGroupEntries):
                value = DisplayGroupEntries(value)
                super().__setitem__(key, value)
            yield key, value


class DisplaySubstituteGroups(dict):
    """Group -> substitute entries with DB-backed display names."""

    def __setitem__(self, group_id, value):
        if isinstance(value, dict) and not isinstance(value, DisplayGroupEntries):
            value = DisplayGroupEntries(value)
        super().__setitem__(group_id, value)

    def __getitem__(self, group_id):
        value = super().__getitem__(group_id)
        if isinstance(value, dict) and not isinstance(value, DisplayGroupEntries):
            value = DisplayGroupEntries(value)
            super().__setitem__(group_id, value)
        return value

    def get(self, group_id, default=None):
        if group_id not in self:
            return default
        return self[group_id]


async def _display_chat_member(original, group_id, user_id):
    """Return a ChatMember copy whose visible user name uses PlayerService."""
    member = await original(group_id, user_id)
    try:
        uid = member.user.id
        visible_name = display_name(uid, member.user.full_name or str(uid))
        member = copy.copy(member)
        member.user = copy.copy(member.user)
        member.user.full_name = visible_name
    except Exception:
        pass
    return member


async def _display_chat_administrators(original, group_id):
    """Resolve display names for every administrator returned by Telegram."""
    members = await original(group_id)
    result = []
    for member in members:
        try:
            uid = member.user.id
            visible_name = display_name(uid, member.user.full_name or str(uid))
            member = copy.copy(member)
            member.user = copy.copy(member.user)
            member.user.full_name = visible_name
        except Exception:
            pass
        result.append(member)
    return result


def install(main_module):
    """Install the compatibility layer into the already-imported main module."""
    main_module.display_name = display_name
    main_module.ensure_player = ensure_player

    # Core player mapping.
    raw_players = main_module.players
    main_module.players = DisplayPlayers(raw_players)

    # Waiting/reserve list.
    main_module.waiting_list = DisplayWaitingList(main_module.waiting_list)

    # Replacement/removed-player records.
    if hasattr(main_module, "substitute_list"):
        main_module.substitute_list = DisplaySubstituteGroups(main_module.substitute_list)
    if hasattr(main_module, "removed_players"):
        main_module.removed_players = DisplaySubstituteGroups(main_module.removed_players)

    # Persist players that existed before installation.
    for uid, raw_name in raw_players.items():
        player_service.ensure_player_data(uid, full_name=raw_name)

    # Legacy main.py frequently uses bot.get_chat_member(...).user.full_name
    # for moderator/admin labels. Wrap these reads so they also respect the
    # central nickname/profile service without modifying the huge main.py.
    bot = getattr(main_module, "bot", None)
    if bot is not None and not getattr(bot, "_mafia_identity_bridge_installed", False):
        original_get_chat_member = bot.get_chat_member
        original_get_chat_administrators = bot.get_chat_administrators

        async def get_chat_member(group_id, user_id):
            return await _display_chat_member(original_get_chat_member, group_id, user_id)

        async def get_chat_administrators(group_id):
            return await _display_chat_administrators(original_get_chat_administrators, group_id)

        bot.get_chat_member = get_chat_member
        bot.get_chat_administrators = get_chat_administrators
        bot._mafia_identity_bridge_installed = True

    return main_module
