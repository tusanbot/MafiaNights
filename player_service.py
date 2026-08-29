from player_repository import PlayerRepository


class PlayerService:
    """لایه سرویس بازیکن؛ ثبت پروفایل و نام نمایشی را یکجا مدیریت می‌کند."""

    def __init__(self, repository=None):
        self.repo = repository or PlayerRepository()

    def ensure_player(self, user):
        """اطلاعات کاربر را در DB ثبت/به‌روزرسانی و رکورد نهایی را برمی‌گرداند."""
        return self.ensure_player_data(
            user_id=user.id,
            full_name=getattr(user, "full_name", None),
            username=getattr(user, "username", None),
        )

    def ensure_player_data(self, user_id, full_name=None, username=None):
        self.repo.upsert(user_id, full_name, username)
        return self.repo.get(user_id)

    def display_name(self, user_id, fallback="❓"):
        """نام نمایشی: Nickname، سپس نام واقعی ذخیره‌شده در پروفایل، سپس fallback."""
        row = self.repo.get(user_id)
        if not row:
            return fallback

        nickname = (row.get("nickname") or "").strip()
        if nickname:
            return nickname

        first_name = (row.get("first_name") or "").strip()
        last_name = (row.get("last_name") or "").strip()
        real_name = " ".join(p for p in (first_name, last_name) if p)
        return real_name or fallback

    def set_nickname(self, user_id, nickname):
        return self.repo.set_nickname(user_id, nickname)

    def delete_nickname(self, user_id):
        return self.repo.delete_nickname(user_id)

    def all_nicknames(self):
        return self.repo.all_nicknames()


# یک نمونه متمرکز برای استفاده در کل ربات
player_service = PlayerService()


def display_name(user_id, fallback="❓"):
    return player_service.display_name(user_id, fallback)


def ensure_player(user):
    return player_service.ensure_player(user)


def ensure_player_data(user_id, full_name=None, username=None):
    return player_service.ensure_player_data(user_id, full_name, username)
