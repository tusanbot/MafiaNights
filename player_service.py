import time

from player_repository import PlayerRepository


class PlayerService:
    """لایه واحد مدیریت پروفایل و نام نمایشی بازیکن با cache کوتاه‌مدت."""

    CACHE_TTL = 60.0

    def __init__(self, repository=None):
        self.repo = repository
        self._repository_initialized = repository is not None
        self._display_cache: dict[int, tuple[float, str]] = {}

    def _get_repo(self):
        if not self._repository_initialized:
            try:
                self.repo = PlayerRepository()
            except Exception:
                self.repo = None
            self._repository_initialized = True
        return self.repo

    @staticmethod
    def _real_name(row):
        if not row:
            return None
        first = (row.get("first_name") or "").strip()
        last = (row.get("last_name") or "").strip()
        return " ".join(p for p in (first, last) if p).strip() or None

    @classmethod
    def _row_name(cls, row, fallback="❓"):
        if not row:
            return fallback
        nickname = (row.get("nickname") or "").strip()
        if nickname:
            return nickname
        return cls._real_name(row) or (row.get("username") or fallback)

    def _cache(self, user_id, value):
        if value:
            self._display_cache[int(user_id)] = (time.monotonic(), str(value))
        return value

    def invalidate(self, user_id):
        self._display_cache.pop(int(user_id), None)

    def ensure_player(self, user):
        return self.ensure_player_data(
            user_id=user.id,
            full_name=getattr(user, "full_name", None),
            username=getattr(user, "username", None),
        )

    def ensure_player_data(self, user_id, full_name=None, username=None):
        repo = self._get_repo()
        if repo is None:
            return None
        try:
            repo.upsert(user_id, full_name, username)
            # Avoid an immediate second SELECT: Telegram already supplied the
            # current display name. Nickname, when present, remains cached from
            # an earlier lookup and is never overwritten by this fallback.
            cached = self._display_cache.get(int(user_id))
            if not cached or time.monotonic() - cached[0] >= self.CACHE_TTL:
                self._cache(user_id, full_name or username or "❓")
            return {"id": int(user_id), "username": username, "first_name": (full_name or "").split(None, 1)[0] or None}
        except Exception:
            return None

    def display_name(self, user_id, fallback="❓"):
        uid = int(user_id)
        cached = self._display_cache.get(uid)
        if cached and time.monotonic() - cached[0] < self.CACHE_TTL:
            return cached[1]
        repo = self._get_repo()
        if repo is None:
            return fallback
        try:
            row = repo.get(uid)
        except Exception:
            return fallback
        value = self._row_name(row, fallback)
        return self._cache(uid, value) or fallback

    def set_nickname(self, user_id, nickname):
        repo = self._get_repo()
        if repo is None:
            return False
        try:
            result = repo.set_nickname(user_id, nickname)
            if result:
                self.invalidate(user_id)
                self._cache(user_id, nickname)
            return result
        except Exception:
            return False

    def delete_nickname(self, user_id):
        repo = self._get_repo()
        if repo is None:
            return False
        try:
            result = repo.delete_nickname(user_id)
            if result:
                self.invalidate(user_id)
            return result
        except Exception:
            return False

    def all_nicknames(self):
        repo = self._get_repo()
        if repo is None:
            return {}
        try:
            values = repo.all_nicknames()
            for uid, nickname in values.items():
                self._cache(uid, nickname)
            return values
        except Exception:
            return {}


player_service = PlayerService()


def display_name(user_id, fallback="❓"):
    return player_service.display_name(user_id, fallback)


def ensure_player(user):
    return player_service.ensure_player(user)


def ensure_player_data(user_id, full_name=None, username=None):
    return player_service.ensure_player_data(user_id, full_name, username)
