from __future__ import annotations

# NOTE: This module is retained as the canonical implementation for the profile
# enhancement patch.  The runtime imports ProfileEnhancements through
# profile_enhancements_fixed.py.

from typing import Optional

from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.exceptions import CancelHandler
from sqlalchemy import text

from repositories.player_repository import PlayerRepository


class ProfileStates:
    waiting_transfer_confirm = "profile_waiting_transfer_confirm"


class ProfileEnhancements:
    """Profile/account-transfer implementation used by the runtime patch.

    The account-transfer path is intentionally conservative: it copies the
    source profile to a fresh target account, migrates historical references,
    writes an audit record, and removes the source profile.
    """

    def __init__(self, *args, **kwargs):
        self.pending_transfers = {}
        self.player_repo = kwargs.get("player_repo") or PlayerRepository()

    def _session(self):
        return self.player_repo.SessionLocal()

    def _invalidate(self, user_id: int):
        return None

    def _is_manager(self, actor: int, group_id: int) -> bool:
        return False

    def transfer_account(self, source: int, target: int, actor: int, group_id: Optional[int]):
        source, target, actor = int(source), int(target), int(actor)
        if source == target:
            return False, "❌ حساب مبدأ و مقصد یکسان است."
        if group_id is not None and not self._is_manager(actor, group_id):
            return False, "❌ فقط مدیر گروه می‌تواند انتقال حساب انجام دهد."
        try:
            with self._session() as s:
                source_row = s.execute(
                    text("select * from public.mafia_players where id=:id for update"),
                    {"id": source},
                ).mappings().first()
                if not source_row:
                    return False, "❌ حساب مبدأ پیدا نشد."

                if s.execute(
                    text("select 1 from public.mafia_game_players where player_id=:id limit 1"),
                    {"id": target},
                ).first():
                    return False, "❌ حساب مقصد قبلاً سابقه بازی دارد؛ برای جلوگیری از ادغام اشتباه، مقصد باید حساب تازه باشد."

                if s.execute(
                    text("select 1 from public.mafia_game_players gp join public.mafia_games g on g.id=gp.game_id where gp.player_id=:id and g.status in ('lobby','running','paused') limit 1"),
                    {"id": source},
                ).first():
                    return False, "❌ انتقال در زمان حضور در بازی فعال مجاز نیست."

                s.execute(
                    text("insert into public.mafia_players(id,username,first_name,last_name,nickname,gender,created_at,updated_at) values (:target,:username,:first_name,:last_name,:nickname,:gender,now(),now()) on conflict (id) do update set username=coalesce(excluded.username,public.mafia_players.username),first_name=coalesce(excluded.first_name,public.mafia_players.first_name),last_name=coalesce(excluded.last_name,public.mafia_players.last_name),nickname=coalesce(excluded.nickname,public.mafia_players.nickname),gender=coalesce(excluded.gender,public.mafia_players.gender),updated_at=now())"),
                    {
                        "target": target,
                        "username": source_row.get("username"),
                        "first_name": source_row.get("first_name"),
                        "last_name": source_row.get("last_name"),
                        "nickname": source_row.get("nickname"),
                        "gender": source_row.get("gender"),
                    },
                )

                # Only migrate columns/tables that are part of the account
                # history contract.  The actual repository schema may not have
                # every optional rating column, so keep this list conservative.
                for table, column in (
                    ("mafia_game_players", "player_id"),
                    ("mafia_game_turns", "player_id"),
                    ("mafia_challenges", "challenger_id"),
                    ("mafia_challenges", "target_id"),
                    ("mafia_ratings", "user_id"),
                ):
                    s.execute(
                        text(f"update public.{table} set {column}=:target where {column}=:source"),
                        {"source": source, "target": target},
                    )

                s.execute(
                    text("insert into public.mafia_account_transfers(source_user_id,target_user_id,actor_user_id,group_chat_id) values (:source,:target,:actor,:group_id)"),
                    {"source": source, "target": target, "actor": actor, "group_id": group_id},
                )
                s.execute(
                    text("delete from public.mafia_players where id=:id"),
                    {"id": source},
                )
                s.commit()

            self._invalidate(source)
            self._invalidate(target)
            return True, "✅ انتقال حساب انجام شد."
        except Exception:
            return False, "❌ انتقال حساب انجام نشد. داده مقصد یا ساختار سابقه بازی با انتقال سازگار نیست."
