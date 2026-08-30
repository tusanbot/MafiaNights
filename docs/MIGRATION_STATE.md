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

## Current cut-over boundary

The Telegram entry point in `main.py` remains legacy. The persistent runtimes are intentionally not activated by replacing `main.py` until the complete legacy handler inventory has been mapped.

## Legacy state inventory

Known game state still held by the legacy entry point includes lobby, turn and challenge process state. The migration must not delete these variables blindly because some are UI/message handles rather than authoritative game state.

The intended rule is:

1. Database state is authoritative for game/player/turn/challenge state.
2. Telegram message IDs and asyncio task handles remain ephemeral process state.
3. Runtime recovery reconstructs ephemeral workers from persisted deadlines/state.
4. Handlers call `PersistentGameRuntime`; they do not mutate authoritative state directly.

## Cut-over checklist

- [x] Persistent lobby foundation
- [x] Persistent turn foundation
- [x] Persistent challenge foundation
- [x] Unified runtime facade
- [x] State-machine boundary
- [ ] Replace legacy lobby callbacks
- [ ] Replace legacy turn callbacks
- [ ] Replace legacy challenge callbacks
- [ ] Remove authoritative lobby globals
- [ ] Remove authoritative turn globals
- [ ] Remove authoritative challenge globals
- [ ] Rebuild ephemeral Telegram timers/messages from recovery
- [ ] Run integration tests

## Safety

Until integration testing is available, keep migration work on `refactor/state-migration` and do not merge it into production.
