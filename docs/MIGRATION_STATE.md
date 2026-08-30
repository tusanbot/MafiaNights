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
- Legacy-state authority boundary

## Current cut-over boundary

`main.py` remains the legacy Telegram implementation, while `player_runtime_entry.py` is the migration production entry point. It installs the player/profile bridge, attaches one shared `PersistentGameRuntime`, installs Turn/Challenge/Lobby/Day compatibility cut-overs plus the legacy-state authority boundary, and runs persistent startup recovery before polling.

The cut-over layers deliberately preserve the existing Telegram UX. Legacy callbacks continue to render and validate the UI, while authoritative game state is written to persistence before/around the legacy transition. This avoids a risky bulk rewrite of the 138KB legacy handler module while making restart recovery possible.

## State authority contract

The database/persistent runtime is the source of truth. Legacy globals are classified as follows:

### Persisted authoritative state

- `player_slots`
- `turn_order`
- `current_turn_index`
- `current_turn_seat`
- `players_in_game`
- `extra_turns`

These values are persisted under the active game's state/current-turn columns and are rehydrated before subsequent group updates. Legacy mutations are treated as compatibility commands and captured back into persistence; they are not durable state by themselves.

### Derived compatibility state

- `waiting_list`
- `pending_challenges`
- `challenge_requests`
- `active_challenger_seats`
- `challenge_mode`
- `paused_main_player`
- `paused_main_duration`
- `post_challenge_advance`
- `day_number`
- `day_phase`
- `game_running`
- `lobby_active`
- `moderator_id`
- `selected_scenario`

These are rebuilt from the persistent snapshot/runtime and must not be used as independent durable truth.

### Ephemeral process/UI state

- Telegram message IDs (`game_message_id`, `lobby_message_id`, `current_turn_message_id`, `waiting_message_id`)
- asyncio timer task handles (`turn_timer_task`)
- local anti-spam timestamp (`last_next_time`)

They may exist in memory but are intentionally not persisted as game truth.

## Runtime rules

1. Database state is authoritative for game/player/turn/challenge/lobby/day state.
2. Telegram message IDs and asyncio timer tasks are ephemeral process state.
3. Startup recovery reconstructs the persisted snapshot and safely finishes expired turns.
4. Lobby hydration reconstructs seats, waiting list, moderator and scenario before the next group handler.
5. Lobby persistence mirrors seat assignments, waiting-list membership, moderator, scenario and lobby metadata after legacy handlers mutate them.
6. Turn and challenge callbacks use compatibility bridges so persistence is updated before legacy Telegram UI continues.
7. Day/night transitions persist the phase and day number and reset the persisted turn pointer before the legacy callback executes.
8. The state-authority middleware hydrates the compatibility view before group updates and captures only the supported compatibility state after handlers; dedicated lifecycle cut-overs remain responsible for transactional lobby/turn/challenge/day operations.
9. Do not reconcile lobby membership after the game has entered the running state; active game participants are protected from incomplete legacy lobby globals.

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
- [x] Legacy global state authority boundary installed
- [x] Authoritative/derived/ephemeral global classification documented
- [x] Compatibility state hydration before group updates
- [x] Compatibility mutations captured into persistent state
- [ ] Remove legacy global containers from `main.py` entirely
- [ ] Rebuild all ephemeral Telegram timers/messages from recovery
- [ ] End-to-end integration tests against the real bot/DB

## Safety

Keep migration work on `refactor/state-migration` until the bot can be exercised end-to-end. Do not merge this branch into production solely because the persistence layer is complete.
