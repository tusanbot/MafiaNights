from player_repository import PlayerRepository


class PlayerService:
    """لایه سرویس بازیکن؛ منطق نمایش نام و ثبت پروفایل را یکجا نگه می‌دارد."""

    def __init__(self, repository=None):
        self.repo = repository or PlayerRepository()

    def ensure_player(self, user):
        self.repo.upsert(
            user_id=user.id,
            full_name=getattr(user, "full_name", None),
            username=getattr(user, "username", None),
        )
        return self.repo.get(user.id)

    def ensure_player_data(self, user_id, full_name=None, username=None):
        self.repo.upsert(user_id, full_name, username)
        return self.repo.get(user_id)

    def display_name(self, user_id, fallback="❓"):
        row = self.repo.get(user_id)
        if not row:
            return fallback
        return row.get("nickname") or fallback

    def set_nickname(self, user_id, nickname):
        return self.repo.set_nickname(user_id, nickname)

    def delete_nickname(self, user_id):
        return self.repo.delete_nickname(user_id)

    def all_nicknames(self):
        return self.repo.all_nicknames()
