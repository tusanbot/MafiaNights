from player_repository import PlayerRepository


class PlayerService:
    """لایه واحد مدیریت پروفایل و نام نمایشی بازیکن.

    Repository به‌صورت lazy ساخته می‌شود تا نبود موقت DATABASE_URL یا
    قطعی دیتابیس باعث Crash شدن کل Bot در startup نشود.
    """

    def __init__(self, repository=None):
        self.repo = repository
        self._repository_initialized = repository is not None

    def _get_repo(self):
        if not self._repository_initialized:
            try:
                self.repo = PlayerRepository()
            except Exception:
                self.repo = None
            self._repository_initialized = True
        return self.repo

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
            return repo.get(user_id)
        except Exception:
            return None

    @staticmethod
    def _real_name(row):
        if not row:
            return None
        first = (row.get("first_name") or "").strip()
        last = (row.get("last_name") or "").strip()
        return " ".join(p for p in (first, last) if p).strip() or None

    def display_name(self, user_id, fallback="❓"):
        """نام نمایشی: Nickname، سپس نام واقعی، سپس username و در نهایت fallback."""
        repo = self._get_repo()
        if repo is None:
            return fallback
        try:
            row = repo.get(user_id)
        except Exception:
            return fallback

        if not row:
            return fallback

        nickname = (row.get("nickname") or "").strip()
        if nickname:
            return nickname

        real_name = self._real_name(row)
        if real_name:
            return real_name

        username = (row.get("username") or "").strip()
        return username or fallback

    def set_nickname(self, user_id, nickname):
        repo = self._get_repo()
        if repo is None:
            return False
        try:
            return repo.set_nickname(user_id, nickname)
        except Exception:
            return False

    def delete_nickname(self, user_id):
        repo = self._get_repo()
        if repo is None:
            return False
        try:
            return repo.delete_nickname(user_id)
        except Exception:
            return False

    def all_nicknames(self):
        repo = self._get_repo()
        if repo is None:
            return {}
        try:
            return repo.all_nicknames()
        except Exception:
            return {}


player_service = PlayerService()


def display_name(user_id, fallback="❓"):
    return player_service.display_name(user_id, fallback)


def ensure_player(user):
    return player_service.ensure_player(user)


def ensure_player_data(user_id, full_name=None, username=None):
    return player_service.ensure_player_data(user_id, full_name, username)
