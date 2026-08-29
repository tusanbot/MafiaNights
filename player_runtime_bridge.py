"""Compatibility bridge for central player profiles and display names.

This module keeps the legacy main.py state shape intact while routing player-name
reads/writes through PlayerService. It is intentionally isolated so the large
legacy main.py does not need a risky full-file rewrite.
"""

from player_service import player_service, display_name, ensure_player


class DisplayPlayers(dict):
    """Legacy {uid: name} mapping with DB-backed display names."""

    def __setitem__(self, user_id, value):
        user_id = int(user_id)
        player_service.ensure_player_data(user_id, full_name=value)
        super().__setitem__(user_id, value)

    def get(self, user_id, default=None):
        user_id = int(user_id)
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


def install(main_module):
    """Install the compatibility layer into the already-imported main module."""
    main_module.display_name = display_name
    main_module.ensure_player = ensure_player

    # Keep the original state objects' contents, but expose DB-backed names.
    raw_players = main_module.players
    main_module.players = DisplayPlayers(raw_players)
    main_module.waiting_list = DisplayWaitingList(main_module.waiting_list)

    # Persist any players that already existed before the bridge was installed,
    # without passing a nickname-resolved display value back as their real name.
    for uid, raw_name in raw_players.items():
        player_service.ensure_player_data(uid, full_name=raw_name)

    return main_module
