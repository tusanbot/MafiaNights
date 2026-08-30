# Legacy handler migration map

This map is the cut-over boundary for `main.py`. It intentionally separates Telegram UI concerns from authoritative game state.

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
- `start_night`
- `start_new_day`

Target boundary: `handlers/turn.py` -> `PersistentTurnRuntime`.

Important: `current_turn_index`, `turn_order`, and active turn timing are authoritative game state and must not remain authoritative globals after cut-over. Telegram message IDs and asyncio timer tasks may remain ephemeral.

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

The persistent Turn and Challenge facades exist, but the Telegram callback registrations in `main.py` are still legacy-owned. Do not claim Turn/Challenge cut-over complete until those registrations delegate to the persistent runtime and their legacy state mutations are removed.
