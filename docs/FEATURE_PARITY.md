# Feature parity — clean migration target

The legacy `main.py` remains untouched. `main_refactored_v2.py` is the clean target and attaches `runtime/feature_parity.py`.

## Covered

| Legacy capability | Clean target |
|---|---|
| Private management panel | `FeatureParity.open_panel` |
| Player list | `list_players` |
| Resend roles | `resend_roles` |
| Remove player | `remove_player` / `remove_confirm` |
| Restore removed player | `revive_player` / `revive_confirm` |
| Substitute registration | `add_substitute_message` |
| Player replacement | `replace_player` / `choose_replace_seat` / `replace_confirm` |
| My seat | `seat_command` |
| Seat list | `seats_command` |
| My role in private chat | `role_command` |
| Game status | `status_command` |
| Admin-only player list | `players_command` |
| Tag active players | `tag_list` |
| Tag group admins | `tag_admins` |
| Challenge request | `challenge_request` |
| Challenge accept/reject | `challenge_response` |
| Moderator management | `moderator_menu` / `set_moderator` |
| Player Next permission | persistent `next_settings.allow_players_next` |
| Moderator Next permission | persistent `next_settings.allow_moderator_next` |
| Next anti-spam | persistent `next_settings.anti_spam` |
| Scenario add/remove | FSM + `scenario_menu` |
| Game cancellation | `cancel` |

## State rule

All game-affecting compatibility data is stored under the active game's persisted `state`. No new module-level mutable game containers are introduced.

## Intentionally deferred

Some historical legacy handlers contain broken/undefined references or duplicate registrations. They are not copied verbatim. The clean target keeps the intended user-facing behavior and routes it through the persistent runtime instead.

Real Telegram + Supabase end-to-end verification remains a separate final gate.
