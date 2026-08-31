# Telegram + Vercel test deployment

Telegram is the primary platform. Rubika and Bale are future adapters and must not leak into the game core.

## Environment variables

- `TELEGRAM_BOT_TOKEN` — Telegram BotFather token. `API_TOKEN` is accepted for backward compatibility.
- `TELEGRAM_WEBHOOK_SECRET` — optional Telegram webhook secret token. When set, requests without the matching `X-Telegram-Bot-Api-Secret-Token` header are rejected.
- `ALLOWED_GROUP_ID` — optional group restriction used by the current application.

## Endpoint

`POST /api/telegram/webhook`

The endpoint returns `200` for accepted updates and acknowledges duplicate `update_id` values without dispatching them twice. `GET` is a lightweight health response.

## Important limitation

Vercel Functions are request-driven. Do not use Telegram long polling or rely on a process-local `asyncio.sleep()` for durable turn timers. Persistent deadlines belong in the game state; a scheduled/worker mechanism should advance expired turns in production.

## Test sequence

1. Deploy the `refactor/state-migration` branch to a separate Vercel project.
2. Configure the environment variables above.
3. Configure Telegram's webhook to the deployed `/api/telegram/webhook` endpoint.
4. Verify `GET /api/telegram/webhook` returns the service health payload.
5. Send `/start` and exercise lobby creation/join/leave.
6. Verify Supabase state changes.
7. Exercise role distribution, turns, challenges, replacement, day/night and recovery.
8. Repeat an update and confirm idempotent acknowledgement.

Do not point the production bot at this deployment until the complete test matrix passes.
