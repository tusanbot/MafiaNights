"""Runtime compatibility schema for progress/profile features.

The production bot historically used integer game IDs, while the newer Supabase
schema uses UUID game IDs. The feature tables are therefore created without
hard foreign-key assumptions when they are missing. Existing canonical tables
are left untouched.
"""
from __future__ import annotations

import logging
from sqlalchemy import text

from repositories.base import DatabaseRepository


ACHIEVEMENTS = [
    ("games_1", "اولین بازی", "اولین بازی ثبت‌شده", "games", 1, 25, None, None, 0),
    ("games_10", "بازیکن فعال", "۱۰ بازی انجام بده", "games", 10, 75, "بازیکن فعال", "🔥", 0),
    ("games_25", "بازیکن باتجربه", "۲۵ بازی انجام بده", "games", 25, 150, None, None, 0),
    ("games_50", "بازیکن حرفه‌ای", "۵۰ بازی انجام بده", "games", 50, 300, "بازیکن حرفه‌ای", "🎖", 0),
    ("games_100", "افسانه مافیا", "۱۰۰ بازی انجام بده", "games", 100, 700, "افسانه مافیا", "👑", 0),
    ("wins_10", "برنده‌ساز", "۱۰ برد ثبت کن", "wins", 10, 200, "برنده‌ساز", "🏆", 0),
    ("challenges_10", "چالشگر", "۱۰ چالش ثبت‌شده داشته باش", "challenges", 10, 150, "چالشگر", "⚔️", 0),
    ("clean_10", "منضبط", "۱۰ بازی بدون دریافت تذکر", "clean_games", 10, 175, "منضبط", "🛡️", 0),
    ("win_streak_5", "سریال برد", "۵ برد پیاپی", "best_win_streak", 5, 250, "سریال برد", "🔥", 0),
    ("positive_50", "مثبت پنجاه", "۵۰ امتیاز مثبت از بازی‌ها کسب کن", "delta", 50, 125, None, None, 0),
    ("avg_70", "ثبات درخشان", "با حداقل ۱۰ بازی میانگین امتیاز بازی ۷۰ یا بیشتر داشته باش", "avg_game_score", 70, 300, "ثبات درخشان", "💎", 10),
]


def install(app=None) -> bool:
    repo = DatabaseRepository()
    try:
        with repo.SessionLocal() as s:
            # Profile privacy settings.
            s.execute(text("""
                create table if not exists public.mafia_profile_settings (
                    user_id bigint primary key,
                    visibility text not null default 'public'
                        check (visibility in ('public','basic','private')),
                    show_gender boolean not null default true,
                    show_nickname boolean not null default true,
                    show_stats boolean not null default true,
                    show_history boolean not null default false,
                    show_roles boolean not null default false,
                    show_group_stats boolean not null default false,
                    updated_at timestamptz not null default now()
                )
            """))

            # Achievement catalog and player progress.
            s.execute(text("""
                create table if not exists public.mafia_achievements (
                    id text primary key,
                    name text not null,
                    description text not null,
                    metric text not null,
                    target numeric not null,
                    reward_points integer not null default 0,
                    tag_name text,
                    tag_emoji text,
                    requires_games integer not null default 0,
                    is_active boolean not null default true,
                    created_at timestamptz not null default now()
                )
            """))
            s.execute(text("""
                create table if not exists public.mafia_player_achievements (
                    id bigserial primary key,
                    player_id bigint not null,
                    achievement_id text not null,
                    completed_at timestamptz not null default now(),
                    unique(player_id, achievement_id)
                )
            """))
            s.execute(text("""
                create table if not exists public.mafia_achievement_rewards (
                    id bigserial primary key,
                    player_id bigint not null,
                    achievement_id text not null,
                    reward_points integer not null,
                    created_at timestamptz not null default now(),
                    unique(player_id, achievement_id)
                )
            """))
            s.execute(text("""
                create table if not exists public.mafia_player_tags (
                    id bigserial primary key,
                    player_id bigint not null,
                    achievement_id text not null,
                    name text not null,
                    emoji text not null,
                    is_active boolean not null default false,
                    created_at timestamptz not null default now(),
                    unique(player_id, achievement_id)
                )
            """))

            # Game incidents use BIGINT game IDs for the legacy production DB.
            s.execute(text("""
                create table if not exists public.mafia_game_incidents (
                    id bigserial primary key,
                    game_id bigint not null unique,
                    content jsonb not null default '[]'::jsonb,
                    version integer not null default 1,
                    finalized boolean not null default false,
                    created_by bigint,
                    created_at timestamptz not null default now(),
                    updated_at timestamptz not null default now()
                )
            """))
            s.execute(text("""
                create table if not exists public.mafia_game_incident_history (
                    id bigserial primary key,
                    incident_id bigint not null,
                    version integer not null,
                    content jsonb not null default '[]'::jsonb,
                    action text not null check (action in ('create','edit')),
                    actor_id bigint,
                    created_at timestamptz not null default now()
                )
            """))

            for row in ACHIEVEMENTS:
                s.execute(text("""
                    insert into public.mafia_achievements
                        (id,name,description,metric,target,reward_points,tag_name,tag_emoji,requires_games,is_active)
                    values
                        (:id,:name,:description,:metric,:target,:reward,:tag_name,:tag_emoji,:requires_games,true)
                    on conflict (id) do update set
                        name=excluded.name,
                        description=excluded.description,
                        metric=excluded.metric,
                        target=excluded.target,
                        reward_points=excluded.reward_points,
                        tag_name=excluded.tag_name,
                        tag_emoji=excluded.tag_emoji,
                        requires_games=excluded.requires_games,
                        is_active=true
                """), {
                    "id": row[0], "name": row[1], "description": row[2], "metric": row[3],
                    "target": row[4], "reward": row[5], "tag_name": row[6], "tag_emoji": row[7],
                    "requires_games": row[8],
                })

            # These tables are server-owned. Direct runtime connections use the
            # database owner/service role, while public API roles get no access.
            for table in (
                "mafia_profile_settings",
                "mafia_achievements",
                "mafia_player_achievements",
                "mafia_achievement_rewards",
                "mafia_player_tags",
                "mafia_game_incidents",
                "mafia_game_incident_history",
            ):
                s.execute(text(f"alter table public.{table} enable row level security"))
                s.execute(text(f"revoke all on table public.{table} from anon, authenticated"))

            s.commit()

        logging.info("PROGRESS SCHEMA COMPATIBILITY ACTIVE")
        return True
    except Exception:
        logging.exception("PROGRESS SCHEMA COMPATIBILITY FAILED")
        try:
            repo.SessionLocal().rollback()
        except Exception:
            pass
        return False
