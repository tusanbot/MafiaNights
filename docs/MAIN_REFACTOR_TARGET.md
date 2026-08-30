# Main refactor target

`main_refactored.py` is the clean replacement target for the legacy `main.py` during the migration.

## Safety

- The existing `main.py` is intentionally untouched and remains the rollback/reference implementation.
- The new target keeps mutable game state inside `MafiaApplication` and `TelegramRuntime`; it does not declare module-level game containers such as `players`, `player_slots`, `turn_order`, `waiting_list`, or `pending_challenges`.
- Durable lobby, turn, challenge and day/night state is delegated to `PersistentGameRuntime` and its repository-backed runtimes.
- Telegram message IDs, asyncio timer tasks and local anti-spam timestamps are process-local UI/runtime state only.
- Startup uses `EphemeralRecoveryManager` so active persisted turn deadlines can be reconstructed after a restart.

## Covered core flow

The target contains clean implementations for lobby creation, scenario selection, joining/leaving, role distribution, head-speaker selection, round/turn start, persisted countdowns, next-turn advancement, challenge creation/resolution, night/day transitions, cancellation, help and startup/shutdown recovery.

## Activation rule

Do not replace `main.py` with this file yet. The target must first pass syntax/import checks, focused migration tests, and real Telegram + Supabase end-to-end tests. Advanced legacy-only features that are not represented by the persistent runtime should be ported into dedicated handlers/services before activation rather than reintroducing global state.
