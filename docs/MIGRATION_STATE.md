# MafiaNights migration state

## Architecture

The migration branch now contains persistent infrastructure for:

- Player/profile persistence
- Scenario persistence
- Lobby repository/service/runtime/handler
- Turn repository/service/runtime with active-turn uniqueness
- Challenge repository/service/runtime with pause/resume metadata
- Unified `PersistentGameRuntime`
- `GameStateMachine`
- Production bootstrap bridge
- Restart recovery and legacy-state hydration

## Current cut-over boundary

`main.py` remains the legacy Telegram implementation, but the production entry point is now `player_runtime_entry.py`. It installs the player/profile bridge, attaches one shared `PersistentGameRuntime`, installs the existing turn/challenge cut-over wrappers, then runs persistent startup recovery before polling.

The migration intentionally avoids deleting legacy globals in bulk. Telegram message IDs and asyncio task handles remain ephemeral, while game/player/turn/challenge state is persisted.

## Runtime rules

1. Database state is authoritative for game/player/turn/challenge state.
2. Telegram message IDs and asyncio task handles are ephemeral process state.
3. Startup recovery reconstructs the persistent snapshot and marks expired turns safely.
4. The production entry point hydrates legacy UI/session globals from the persisted game after restart.
5. Turn and challenge callbacks use compatibility bridges so persistence is updated before legacy Telegram UI continues.
6. Lobby handler replacement is still a separate cut-over step; the existing lobby UI has not been blindly replaced.

## Cut-over checklist

- [x] Persistent lobby foundation
- [x] Persistent turn foundation
- [x] Persistent challenge foundation
- [x] Unified runtime facade
- [x] State-machine boundary
- [x] Production entry point activates persistent runtime
- [x] Startup recovery hook
- [x] Restart hydration of legacy UI/session state
- [x] Turn/timer compatibility bridge installed by production entry point
- [x] Challenge compatibility bridge installed by production entry point
- [x] Day persistence runtime
- [ ] Replace legacy lobby callbacks
- [ ] Replace remaining legacy day callback with persistent day transition
- [ ] Remove authoritative lobby globals
- [ ] Remove authoritative turn globals
- [ ] Remove authoritative challenge globals
- [ ] Rebuild all ephemeral Telegram timers/messages from recovery
- [ ] End-to-end integration tests against the real bot/DB

## Safety

Keep migration work on `refactor/state-migration` until the bot can be exercised end-to-end. Do not merge this branch into production solely because the persistence layer is complete.
