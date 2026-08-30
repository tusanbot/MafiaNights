# Legacy handler migration map

This map is the cut-over boundary for `main.py`. It separates Telegram UI concerns from authoritative game state.

## Lobby

Legacy responsibilities in `main.py`:
- `new_game`
- `choose_scenario`
- `scenario_selected`
- `choose_moderator`
- `moderator_selected`
- `join_game`
- `leave_game`
- seat/waiting-list mutations

Target boundary: `handlers/lobby.py` -> `PersistentLobbyRuntime`.

Cut-over status: **installed**. `LobbyPersistenceMiddleware` hydrates the persisted lobby before group updates and mirrors legacy lobby mutations after group handlers. The existing Telegram UI remains intact while persistence becomes the durable source of truth.

## Turn

Legacy responsibilities:
- `start_play`
- `choose_head`
- `speaker_auto`
- `speaker_manual`
- `head_set_handler`
- `start_turn`
- `countdown`
- `next_turn`

Target boundary: `handlers/turn.py` -> `PersistentTurnRuntime`.

Cut-over status: **persistence bridge installed**. `current_turn_index`, `current_turn_seat`, `turn_order`, active turn timing and related persistent fields are stored through the runtime. Legacy variables are compatibility caches and are hydrated before updates.

## Day / Night

Legacy responsibilities:
- `start_new_day`
- `start_night`
- `reset_round_data`
- day/phase updates associated with the turn transition

Target boundary: `runtime/day_cutover.py` -> `PersistentDayRuntime`.

Cut-over status: **installed**. Day/night callbacks persist the phase and day number before legacy Telegram UI continues. The persisted turn pointer is reset at the boundary and any active persisted turn is safely finished before the transition. Legacy day variables are derived compatibility state only.

## Challenge

Legacy responsibilities:
- `challenge_request`
- challenge accept/reject callbacks
- before/after challenge selection
- challenge pause/resume handling

Target boundary: `handlers/challenge.py` -> `PersistentChallengeRuntime`.

Cut-over status: **persistence bridge installed**. Pending/active challenge state and pause metadata are persisted; legacy challenge flags are derived compatibility state only.

## Global state authority

`runtime/state_authority.py` is now the common compatibility boundary for legacy globals.

### Authoritative persistent state

- `player_slots`
- `turn_order`
- `current_turn_index`
- `current_turn_seat`
- `players_in_game`
- `extra_turns`

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

### Ephemeral process/UI state

- Telegram message IDs
- asyncio timer task handles
- local anti-spam timestamps

The state-authority middleware hydrates the legacy compatibility view before group updates and captures supported compatibility mutations into persistence after handlers. Dedicated cut-over modules remain responsible for transactional lifecycle operations.

## Recovery

Startup/restart behavior belongs to `RecoveryCoordinator` / `RecoveryWorker`, with `EphemeralRecoveryManager` owning the process-local timer registry and optional Telegram UI reconstruction hooks.

### Restart guarantees

- Active turn deadlines are reconstructed from persisted `started_at + duration_seconds`.
- One asyncio task is scheduled per persisted active turn.
- A timer re-checks the persisted turn ID before dispatch, so stale workers cannot advance a newer turn.
- Expiry handling is serialized and duplicate dispatches are suppressed for the same turn.
- Stale Telegram message IDs, timer handles and local anti-spam timestamps are cleared on restart.
- Pending challenges are re-exposed to the compatibility layer after restart.
- Optional `rebuild_recovered_lobby`, `rebuild_recovered_turn` and `rebuild_recovered_challenges` hooks may recreate Telegram messages without persisting message IDs as game truth.

## Cut-over rule

Do not delete legacy code until the corresponding target handler has equivalent authorization, state transitions, persistence, and Telegram UX coverage. During migration, legacy globals may be read or mutated for compatibility, but they are not the durable source of truth; persistence is.

## Current cut-over status

- Lobby: **persistence cut-over installed** through `runtime/lobby_cutover.py` and activated by the production bridge.
- Turn: **persistent bridge installed**; legacy containers remain only for compatibility/UI.
- Challenge: **persistent bridge installed**; legacy challenge containers remain only for compatibility/UI.
- Day/Night: **persistence cut-over installed** through `runtime/day_cutover.py` and activated by the production bridge.
- Global state authority: **installed** through `runtime/state_authority.py` and activated by the production bridge.
- Restart ephemeral recovery: **installed** through `runtime/ephemeral_recovery.py` and activated by the production bridge.
