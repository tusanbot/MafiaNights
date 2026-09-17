-- MafiaNights progress, achievements, events and game incidents.
-- These tables are server-owned; RLS is enabled and client roles have no privileges.

create table if not exists public.mafia_achievements (
    id text primary key,
    name text not null,
    description text not null,
    metric text not null,
    target numeric not null check (target > 0),
    reward_points integer not null default 0 check (reward_points >= 0),
    tag_name text,
    tag_emoji text,
    requires_games integer not null default 0 check (requires_games >= 0),
    is_active boolean not null default true,
    created_at timestamptz not null default now()
);

create table if not exists public.mafia_player_achievements (
    id bigint generated always as identity primary key,
    player_id bigint not null references public.mafia_players(id) on delete cascade,
    achievement_id text not null references public.mafia_achievements(id) on delete cascade,
    completed_at timestamptz not null default now(),
    unique(player_id, achievement_id)
);

create table if not exists public.mafia_achievement_rewards (
    id bigint generated always as identity primary key,
    player_id bigint not null references public.mafia_players(id) on delete cascade,
    achievement_id text not null references public.mafia_achievements(id) on delete cascade,
    reward_points integer not null check (reward_points > 0),
    created_at timestamptz not null default now(),
    unique(player_id, achievement_id)
);

create table if not exists public.mafia_player_tags (
    id bigint generated always as identity primary key,
    player_id bigint not null references public.mafia_players(id) on delete cascade,
    achievement_id text not null references public.mafia_achievements(id) on delete cascade,
    name text not null,
    emoji text not null,
    is_active boolean not null default false,
    created_at timestamptz not null default now(),
    unique(player_id, achievement_id)
);

create table if not exists public.mafia_events (
    id bigint generated always as identity primary key,
    name text not null,
    description text,
    starts_at timestamp,
    status text not null default 'active' check (status in ('draft','active','finished','cancelled')),
    grouping_mode text not null default 'manual' check (grouping_mode in ('manual','auto')),
    created_by bigint references public.mafia_players(id) on delete set null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.mafia_event_stages (
    id bigint generated always as identity primary key,
    event_id bigint not null references public.mafia_events(id) on delete cascade,
    name text not null,
    stage_type text not null check (stage_type in ('preliminary','final')),
    stage_order integer not null default 1,
    status text not null default 'pending' check (status in ('pending','active','finished','cancelled')),
    created_at timestamptz not null default now(),
    unique(event_id, stage_type)
);

create table if not exists public.mafia_event_players (
    id bigint generated always as identity primary key,
    event_id bigint not null references public.mafia_events(id) on delete cascade,
    player_id bigint not null references public.mafia_players(id) on delete cascade,
    status text not null default 'registered' check (status in ('registered','replaced','withdrawn')),
    replaced_player_id bigint references public.mafia_players(id) on delete set null,
    registered_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique(event_id, player_id)
);

create table if not exists public.mafia_event_stage_players (
    id bigint generated always as identity primary key,
    stage_id bigint not null references public.mafia_event_stages(id) on delete cascade,
    player_id bigint not null references public.mafia_players(id) on delete cascade,
    group_no integer,
    score integer,
    status text not null default 'active' check (status in ('active','finished','replaced')),
    updated_at timestamptz not null default now(),
    unique(stage_id, player_id)
);

create index if not exists idx_mafia_event_players_event on public.mafia_event_players(event_id);
create index if not exists idx_mafia_event_stage_players_stage on public.mafia_event_stage_players(stage_id);
create index if not exists idx_mafia_event_stage_players_player on public.mafia_event_stage_players(player_id);

create table if not exists public.mafia_game_incidents (
    id bigint generated always as identity primary key,
    game_id uuid not null unique references public.mafia_games(id) on delete cascade,
    content jsonb not null default '[]'::jsonb,
    version integer not null default 1,
    finalized boolean not null default false,
    created_by bigint references public.mafia_players(id) on delete set null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.mafia_game_incident_history (
    id bigint generated always as identity primary key,
    incident_id bigint not null references public.mafia_game_incidents(id) on delete cascade,
    version integer not null,
    content jsonb not null default '[]'::jsonb,
    action text not null check (action in ('create','edit')),
    actor_id bigint references public.mafia_players(id) on delete set null,
    created_at timestamptz not null default now()
);

create index if not exists idx_mafia_event_players_event on public.mafia_event_players(event_id);
create index if not exists idx_mafia_event_stage_players_stage on public.mafia_event_stage_players(stage_id);
create index if not exists idx_mafia_event_stage_players_player on public.mafia_event_stage_players(player_id);

alter table public.mafia_achievements enable row level security;
alter table public.mafia_player_achievements enable row level security;
alter table public.mafia_achievement_rewards enable row level security;
alter table public.mafia_player_tags enable row level security;
alter table public.mafia_events enable row level security;
alter table public.mafia_event_stages enable row level security;
alter table public.mafia_event_players enable row level security;
alter table public.mafia_event_stage_players enable row level security;
alter table public.mafia_game_incidents enable row level security;
alter table public.mafia_game_incident_history enable row level security;

revoke all on table public.mafia_achievements, public.mafia_player_achievements, public.mafia_achievement_rewards, public.mafia_player_tags, public.mafia_events, public.mafia_event_stages, public.mafia_event_players, public.mafia_event_stage_players, public.mafia_game_incidents, public.mafia_game_incident_history from anon, authenticated;

grant usage, select on all sequences in schema public to service_role;

insert into public.mafia_achievements (id,name,description,metric,target,reward_points,tag_name,tag_emoji,requires_games) values
('games_1','اولین بازی','اولین بازی ثبت‌شده','games',1,25,null,null,0),
('games_10','بازیکن فعال','۱۰ بازی انجام بده','games',10,75,'بازیکن فعال','🔥',0),
('games_25','بازیکن باتجربه','۲۵ بازی انجام بده','games',25,150,null,null,0),
('games_50','بازیکن حرفه‌ای','۵۰ بازی انجام بده','games',50,300,'بازیکن حرفه‌ای','🎖',0),
('games_100','افسانه مافیا','۱۰۰ بازی انجام بده','games',100,700,'افسانه مافیا','👑',0),
('wins_10','برنده‌ساز','۱۰ برد ثبت کن','wins',10,200,'برنده‌ساز','🏆',0),
('challenges_10','چالشگر','۱۰ چالش ثبت‌شده داشته باش','challenges',10,150,'چالشگر','⚔️',0),
('clean_10','منضبط','۱۰ بازی بدون دریافت تذکر','clean_games',10,175,'منضبط','🛡️',0),
('win_streak_5','سریال برد','۵ برد پیاپی','best_win_streak',5,250,'سریال برد','🔥',0),
('positive_50','مثبت پنجاه','۵۰ امتیاز مثبت از بازی‌ها کسب کن','delta',50,125,null,null,0),
('avg_70','ثبات درخشان','با حداقل ۱۰ بازی میانگین امتیاز بازی ۷۰ یا بیشتر داشته باش','avg_game_score',70,300,'ثبات درخشان','💎',10)
on conflict (id) do update set name=excluded.name,description=excluded.description,metric=excluded.metric,target=excluded.target,reward_points=excluded.reward_points,tag_name=excluded.tag_name,tag_emoji=excluded.tag_emoji,requires_games=excluded.requires_games,is_active=true;
