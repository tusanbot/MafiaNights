import logging
from player_repository import PlayerRepository


class NicknameManager:
    """مدیریت نام مستعار روی جدول اصلی mafia_players."""

    def __init__(self, repository=None):
        self.repo = repository or PlayerRepository()
        logging.info("✅ NicknameManager متصل به mafia_players شد.")

    def set(self, user_id, nickname):
        return self.set_nick(user_id, nickname)

    def set_nick(self, user_id, nickname):
        # بازیکن باید ابتدا در پروفایل ثبت شده باشد.
        player = self.repo.get(user_id)
        if not player:
            self.repo.upsert(user_id)
        return self.repo.set_nickname(user_id, nickname)

    def get(self, user_id):
        return self.get_nick(user_id)

    def get_nick(self, user_id):
        player = self.repo.get(user_id)
        return player.get("nickname") if player else None

    def delete(self, user_id):
        return self.repo.delete_nickname(user_id)

    def all(self):
        return self.repo.all_nicknames()


# سازگاری با کدهای قبلی پروژه
FinalNicknameManager = NicknameManager
