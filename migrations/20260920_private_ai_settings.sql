alter table public.mafia_ai_settings
  add column if not exists private_enabled boolean not null default false,
  add column if not exists private_provider text not null default 'gemini',
  add column if not exists private_model text,
  add column if not exists private_api_key_ciphertext bytea,
  add column if not exists private_web_search_enabled boolean not null default true,
  add column if not exists private_updated_at timestamptz;
