create table if not exists public.mafia_runtime_schema_meta (
  component text primary key,
  version integer not null,
  updated_at timestamptz not null default now()
);

insert into public.mafia_runtime_schema_meta(component, version)
values ('progress_schema_compat', 2)
on conflict (component) do update
set version = greatest(public.mafia_runtime_schema_meta.version, excluded.version),
    updated_at = now();
