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

Important: `current_turn_index`, `turn_order`, and active turn timing are authoritative game state and must not remain authoritative globals after cut-over. Telegram message IDs and asyncio timer tasks may remain ephemeral.

## Day / Night

Legacy responsibilities:
- `start_new_day`
- `start_night`
- `reset_round_data`
- day/phase updates associated with the turn transition

Target boundary: `runtime/day_cutover.py` -> `PersistentDayRuntime`.

Cut-over status: **installed**. Day/night callbacks persist the phase and day number before legacy Telegram UI continues. The persisted turn pointer is reset at the boundary and any active persisted turn is safely finished before the transition. Legacy day variables remain compatibility/UI state only.

## Challenge

Legacy responsibilities:
- `challenge_request`
- challenge accept/reject callbacks
- before/after challenge selection
- challenge pause/resume handling

Target boundary: `handlers/challenge.py` -> `PersistentChallengeRuntime`.

`challenge_requests`, `pending_challenges`, `challenge_mode`, and pause metadata must not remain the source of truth in process memory after cut-over.

## Recovery

Startup/restart behavior belongs to `RecoveryCoordinator` / `RecoveryWorker`, not to legacy timer globals.

## Cut-over rule

Do not delete legacy code until the corresponding target handler has equivalent authorization, state transitions, persistence, and Telegram UX coverage. During migration, legacy globals may be read for compatibility but must not be the authoritative persistence layer.

## Current cut-over status

- Lobby: **persistence cut-over installed** through `runtime/lobby_cutover.py` and activated by the production bridge.
- Turn: persistent runtime and compatibility bridge exist; full removal of legacy turn state is pending.
- Challenge: persistent runtime and compatibility bridge exist; full removal of legacy challenge state is pending.
- Day/Night: **persistence cut-over installed** through `runtime/day_cutover.py` and activated by the production bridge.
