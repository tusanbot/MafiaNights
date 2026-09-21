"""Persistent scheduler tick for MafiaNights voting deadlines."""
from __future__ import annotations

import asyncio
import json
import os
import time
from urllib.request import Request, urlopen


_PRODUCTION_WEBHOOK_HOST = "mafia-nights-tusanbots-projects.vercel.app"
_WEBHOOK_REPAIR_INTERVAL = 60.0
_last_webhook_check = 0.0


def _response(body, status="200 OK"):
    raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
    return status, [("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(raw)))], raw


def _telegram_request(token: str, method: str, payload: dict | None = None) -> dict:
    request = Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=json.dumps(payload or {}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _repair_webhook_if_needed() -> dict:
    """Keep Telegram pointed at the stable production alias, not an old deployment URL."""
    global _last_webhook_check
    now = time.time()
    if now - _last_webhook_check < _WEBHOOK_REPAIR_INTERVAL:
        return {"checked": False}
    _last_webhook_check = now

    token = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("API_TOKEN")
    if not token:
        return {"checked": False, "reason": "telegram_token_missing"}

    target = f"https://{_PRODUCTION_WEBHOOK_HOST}/api/telegram/webhook"
    info = _telegram_request(token, "getWebhookInfo")
    current = str((info.get("result") or {}).get("url") or "")
    if current == target:
        return {"checked": True, "changed": False}

    result = _telegram_request(token, "setWebhook", {"url": target, **({"secret_token": os.getenv("TELEGRAM_WEBHOOK_SECRET")} if os.getenv("TELEGRAM_WEBHOOK_SECRET") else {})})
    return {"checked": True, "changed": bool(result.get("ok")), "target": target}


def app(environ, start_response):
    # Supabase pg_cron invokes this endpoint every minute. Use the patched
    # runtime helpers installed by main.py and keep each transition idempotent.
    result = {}
    try:
        result["webhook_repair"] = _repair_webhook_if_needed()
    except Exception as exc:
        result["webhook_repair"] = {"checked": False, "error": f"{type(exc).__name__}: {exc}"}

    try:
        import player_runtime_entry as main
        from runtime import voting_runtime

        gid = int(os.getenv("ALLOWED_GROUP_ID", "-1002356353761"))
        app_obj = main.app
        app_obj.group_chat_id = gid
        app_obj.ui.group_chat_id = gid
        game = app_obj.runtime.state.active_game(gid)
        voting = dict((game or {}).get("state", {}).get("voting") or {})
        deadline = voting.get("deadline")
        phase = str(voting.get("phase") or "")
        now = time.time()

        # Process every already-due persistent transition in this invocation.
        # A serverless request must not stop after the first target; after ending
        # one target, immediately continue while the persisted state is still due.
        processed = []
        for _ in range(32):
            game = app_obj.runtime.state.active_game(gid)
            voting = dict((game or {}).get("state", {}).get("voting") or {})
            deadline = voting.get("deadline")
            phase = str(voting.get("phase") or "")
            now = time.time()
            if deadline and float(deadline) <= now and phase == "waiting":
                asyncio.run(voting_runtime._start_target(app_obj))
                processed.append("start_target")
                continue
            if deadline and float(deadline) <= now and phase == "voting":
                asyncio.run(voting_runtime._end_target(app_obj))
                processed.append("end_target")
                continue
            if phase == "next_target_pending":
                asyncio.run(voting_runtime._start_target(app_obj))
                processed.append("next_target")
                continue
            if phase == "round_finished_pending":
                asyncio.run(voting_runtime._finish_round(app_obj))
                processed.append("finish_round")
                continue
            break
        result.update({"ok": True, "processed": bool(processed), "actions": processed, "phase": phase})
        if processed:
            result["target_index"] = int(voting.get("target_index") or 0)
        
        else:
            result.update({"ok": True, "processed": False, "phase": phase})
    except Exception as exc:
        result.update({"ok": False, "error": f"{type(exc).__name__}: {exc}"})

    status, headers, body = _response(result)
    start_response(status, headers)
    return [body]


handler = app
