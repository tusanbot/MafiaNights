from __future__ import annotations

from typing import Optional

from player_service import player_service
from sqlalchemy import text

from runtime.profile_enhancements import ProfileEnhancements


class FixedProfileEnhancements(ProfileEnhancements):
    def transfer_account(self, source: int, target: int, actor: int, group_id: Optional[int]):
        source, target, actor = int(source), int(target), int(actor)
        if source == target:
            return False, "❌ حساب مبدأ و مقصد یکسان است."
        if group_id is not None and not self._is_manager(actor, group_id):
            return False, "❌ فقط مدیر گروه می‌تواند انتقال حساب انجام دهد."
        try:
            with self._session() as s:
                source_row = s.execute(text("select * from public.mafia_players where id=:id for update"), {"id": source}).mappings().first()
                if not source_row:
                    return False, "❌ حساب مبدأ پیدا نشد."
                if s.execute(text("select 1 from public.mafia_game_players where player_id=:id limit 1"), {"id": target}).first():
                    return False, "❌ حساب مقصد قبلاً سابقه بازی دارد؛ مقصد باید حساب تازه باشد."
                if s.execute(text("select 1 from public.mafia_game_players gp join public.mafia_games g on g.id=gp.game_id where gp.player_id=:id and g.status in ('lobby','running','paused') limit 1"), {"id": source}).first():
                    return False, "❌ انتقال در زمان حضور در بازی فعال مجاز نیست."
                s.execute(text("""insert into public.mafia_players
                    (id,username,first_name,last_name,nickname,gender,created_at,updated_at)
                    values (:target,:username,:first_name,:last_name,:nickname,:gender,now(),now())
                    on conflict (id) do update set
                    username=coalesce(excluded.username,public.mafia_players.username),
                    first_name=coalesce(excluded.first_name,public.mafia_players.first_name),
                    last_name=coalesce(excluded.last_name,public.mafia_players.last_name),
                    nickname=coalesce(excluded.nickname,public.mafia_players.nickname),
                    gender=coalesce(excluded.gender,public.mafia_players.gender),
                    updated_at=now()"""), {
                    "target": target, "username": source_row.get("username"), "first_name": source_row.get("first_name"),
                    "last_name": source_row.get("last_name"), "nickname": source_row.get("nickname"), "gender": source_row.get("gender")})
                for table, column in (("mafia_game_players","player_id"),("mafia_game_turns","player_id"),("mafia_challenges","challenger_id"),("mafia_challenges","target_id"),("mafia_ratings","voter_id"),("mafia_ratings","target_id"),("mafia_ratings","user_id")):
                    s.execute(text(f"update public.{table} set {column}=:target where {column}=:source"), {"source": source, "target": target})
                s.execute(text("insert into public.mafia_account_transfers(source_user_id,target_user_id,actor_user_id,group_chat_id) values (:source,:target,:actor,:group_id)"), {"source": source, "target": target, "actor": actor, "group_id": group_id})
                s.execute(text("delete from public.mafia_players where id=:id"), {"id": source})
                s.commit()
            self._invalidate(source); self._invalidate(target)
            return True, "✅ انتقال حساب انجام شد."
        except Exception:
            return False, "❌ انتقال حساب انجام نشد. داده مقصد یا سابقه بازی با انتقال سازگار نیست."


def install(app, user_panel=None):
    enhancement = FixedProfileEnhancements(app, user_panel)
    original = player_service.display_name

    def display_name_with_gender(user_id, fallback="❓"):
        uid = int(user_id)
        name = original(uid, fallback)
        if uid not in enhancement.gender_cache:
            row = enhancement._profile(uid)
            enhancement.gender_cache[uid] = (row or {}).get("gender") or ""
        emoji = enhancement._gender_emoji(enhancement.gender_cache.get(uid))
        return f"{emoji} {name}".strip() if emoji else name

    player_service.display_name = display_name_with_gender
    enhancement.register()
    return enhancement
