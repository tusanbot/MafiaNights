# Feature parity finalization

## Target

`main_refactored_v4.py` is the current clean migration target. It leaves `main.py` untouched as the rollback/reference implementation.

Architecture:

`main_refactored.py` → `FeatureParityV4` → persistent runtime/state authority → ephemeral Telegram runtime.

## Migrated user-facing surface

- `/start` and help
- new game/lobby
- scenario selection and scenario CRUD
- moderator selection/change
- join/leave and seat selection
- full-seat waiting/substitute list and cancellation
- role distribution and role resend
- private role lookup
- seat lookup and seat list
- player list and admin-only player list
- game status
- tag active players / group admins
- turn start, next, countdown and restart recovery
- challenge request, before/after decision, reject, challenge status
- remove player
- restore removed player
- replace player from substitute list
- next permissions for players/moderator
- next anti-spam setting
- game cancellation
- addon compatibility remains available through the clean application's addon object

## Legacy callback aliases

The target accepts the principal legacy callback names (`join_game`, `leave_game`, `slot_*`, `join_waiting`, `reserve_waiting`, `leave_waiting`, `cancel_waiting`, `challenge_toggle`, `accept_before_*`, `accept_after_*`, `reject_*`, etc.) through the parity layer.

## State policy

No new module-level mutable game containers were introduced. Substitute lists, removed players, challenge requests, pending challenges, paused-turn metadata and Next settings are stored in the active game's persisted `state` document. Telegram message IDs and asyncio Tasks remain process-local.

## Known boundary

The legacy source contains duplicate handlers and some historical undefined references. Those broken implementation details are not copied. The target implements their intended user-visible capabilities through the persistent runtime.

Real Telegram + Supabase E2E execution remains the final validation gate before production cut-over.
