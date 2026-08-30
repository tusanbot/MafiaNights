# MafiaNights migration state

## Architecture

The migration branch contains persistent infrastructure for:

- Player/profile persistence
- Scenario persistence
- Lobby repository/service/runtime/handler
- Turn repository/service/runtime with active-turn uniqueness
- Challenge repository/service/runtime with pause/resume metadata
- Day/night repository boundary through persisted game state
- Unified `PersistentGameRuntime`
- `GameStateMachine`
- Production bootstrap bridge
- Restart recovery and legacy-state hydration
- Lobby cut-over middleware
- Day/night cut-over compatibility bridge

## Current cut-over boundary

`main.py` remains the legacy Telegram implementation, while `player_runtime_entry.py` is the migration production entry point. It installs the player/profile bridge, attaches one shared `PersistentGameRuntime`, installs Turn/Challenge/Lobby/Day compatibility cut-overs, and runs persistent startup recovery before polling.

The cut-over layers deliberately preserve the existing Telegram UX. Legacy callbacks continue to render and validate the UI, while authoritative game state is written to persistence before/around the legacy transition. This avoids a risky bulk rewrite of the 138KB legacy handler module while making restart recovery possible.

## Runtime rules

1. Database state is authoritative for game/player/turn/challenge/lobby/day state.
2. Telegram message IDs and asyncio timer tasks are ephemeral process state.
3. Startup recovery reconstructs the persisted snapshot and safely finishes expired turns.
4. Lobby hydration reconstructs seats, waiting list, moderator and scenario before the next group handler.
5. Lobby persistence mirrors seat assignments, waiting-list membership, moderator, scenario and lobby metadata after legacy handlers mutate them.
6. Turn and challenge callbacks use compatibility bridges so persistence is updated before legacy Telegram UI continues.
7. Day/night transitions persist the phase and day number and reset the persisted turn pointer before the legacy callback executes.
8. Do not reconcile lobby membership after the game has entered the running state; active game participants are protected from incomplete legacy lobby globals.

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
- [x] Lobby persistence cut-over boundary installed
- [x] Lobby seat/waiting-list synchronization
- [x] Lobby moderator/scenario synchronization
- [x] Lobby restart hydration
- [x] Duplicate-seat protection at repository boundary
- [x] Legacy day/night transition compatibility bridge
- [x] Persisted day number and phase hydration
- [x] Persisted turn pointer reset at day/night boundary
- [ ] Remove authoritative lobby globals
- [ ] Remove authoritative turn globals
- [ ] Remove authoritative challenge globals
- [ ] Remove authoritative day globals
- [ ] Rebuild all ephemeral Telegram timers/messages from recovery
- [ ] End-to-end integration tests against the real bot/DB

## Safety

Keep migration work on `refactor/state-migration` until the bot can be exercised end-to-end. Do not merge this branch into production solely because the persistence layer is complete.
