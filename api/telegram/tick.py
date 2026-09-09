"""Persistent scheduler tick for MafiaNights voting deadlines."""
from __future__ import annotations
import json, os, time, asyncio

def _response(body, status="200 OK"):
    raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
    return status, [("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(raw)))], raw

def app(environ, start_response):
    secret = os.getenv("CRON_SECRET")
    if secret and environ.get("HTTP_AUTHORIZATION") != f"Bearer {secret}":
        status, headers, body = _response({"ok": False, "error": "unauthorized"}, "401 Unauthorized")
        start_response(status, headers); return [body]
    try:
        import main
        from runtime.voting_runtime import _start_target, _end_target
        gid = int(os.getenv("ALLOWED_GROUP_ID", "-1002356353761"))
        app_obj = main.app
        app_obj.group_chat_id = gid
        app_obj.ui.group_chat_id = gid
        game = app_obj.runtime.state.active_game(gid)
        voting = dict((game or {}).get("state", {}).get("voting") or {})
        deadline = voting.get("deadline")
        phase = str(voting.get("phase") or "")
        if deadline and float(deadline) <= time.time() and phase == "waiting":
            asyncio.run(_start_target(app_obj))
            result = {"ok": True, "processed": True, "phase": phase}
        elif deadline and float(deadline) <= time.time() and phase == "voting":
            asyncio.run(_end_target(app_obj))
            result = {"ok": True, "processed": True, "phase": phase}
        else:
            result = {"ok": True, "processed": False, "phase": phase}
    except Exception as exc:
        result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    status, headers, body = _response(result)
    start_response(status, headers); return [body]

handler = app
