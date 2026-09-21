-- Registration schema guard for Mafia Nights.
-- Safe to run repeatedly on existing production databases.
alter table if exists public.mafia_players
    add column if not exists registered_at timestamptz;

create index if not exists mafia_players_registered_at_idx
    on public.mafia_players (registered_at);
