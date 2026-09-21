-- Player-game rating rows use mafia_ratings for historical compatibility.
-- The production table previously enforced the legacy voter/target 1..5 schema,
-- which rejected the per-game score delta model and caused all final scoring
-- inserts to fail silently at the application layer.
alter table public.mafia_ratings alter column event_number drop not null;
alter table public.mafia_ratings alter column voter_id drop not null;
alter table public.mafia_ratings alter column target_id drop not null;

alter table public.mafia_ratings drop constraint if exists mafia_ratings_check;
alter table public.mafia_ratings drop constraint if exists mafia_ratings_score_check;
alter table public.mafia_ratings drop constraint if exists mafia_ratings_changes_check;

create unique index if not exists mafia_ratings_user_game_unique
  on public.mafia_ratings (user_id, game_id)
  where user_id is not null and game_id is not null;
