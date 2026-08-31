"""Temporary, authenticated Telegram webhook setup endpoint for Vercel.

Enable only while configuring the bot by setting TELEGRAM_SETUP_SECRET.
After the webhook is confirmed, remove this endpoint and its route.
"""
from __future__ import annotations

import hmac
import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs
from urllib.request import Request, urlopen


def _response(body: dict, status: str = "200 OK") -> tuple[str, list[tuple[str, str]], bytes]:
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    return status, [
        ("Content-Type", "application/json; charset=utf-8"),
        ("Content-Length", str(len(payload))),
        ("Cache-Control", "no-store"),
    ], payload


def _query(environ: dict) -> dict[str, list[str]]:
    return parse_qs(str(environ.get("QUERY_STRING") or ""), keep_blank_values=True)


def _authorized(environ: dict) -> bool:
    expected = os.getenv("TELEGRAM_SETUP_SECRET")
    if not expected:
        return False
    supplied = _query(environ).get("secret", [""])[0]
    return bool(supplied) and hmac.compare_digest(supplied, expected)


def _telegram_request(token: str, method: str, payload: dict | None = None) -> dict:
    body = json.dumps(payload or {}).encode("utf-8")
    request = Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def app(environ: dict, start_response) -> list[bytes]:
    if str(environ.get("REQUEST_METHOD", "GET")).upper() != "GET":
        status, headers, body = _response({"ok": False, "error": "method_not_allowed"}, "405 Method Not Allowed")
        start_response(status, headers)
        return [body]

    if not _authorized(environ):
        status, headers, body = _response({"ok": False, "error": "unauthorized"}, "401 Unauthorized")
        start_response(status, headers)
        return [body]

    token = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("API_TOKEN")
    webhook_url = os.getenv("TELEGRAM_WEBHOOK_URL")
    if not token:
        status, headers, body = _response({"ok": False, "error": "TELEGRAM_BOT_TOKEN is not configured"}, "500 Internal Server Error")
        start_response(status, headers)
        return [body]
    if not webhook_url:
        status, headers, body = _response({"ok": False, "error": "TELEGRAM_WEBHOOK_URL is not configured"}, "500 Internal Server Error")
        start_response(status, headers)
        return [body]

    webhook_secret = os.getenv("TELEGRAM_WEBHOOK_SECRET")
    payload = {"url": webhook_url}
    if webhook_secret:
        payload["secret_token"] = webhook_secret

    try:
        set_result = _telegram_request(token, "setWebhook", payload)
        info_result = _telegram_request(token, "getWebhookInfo")
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        status, headers, body = _response(
            {"ok": False, "error": "telegram_api_request_failed", "detail": str(exc)},
            "502 Bad Gateway",
        )
        start_response(status, headers)
        return [body]

    result = {
        "ok": bool(set_result.get("ok")),
        "webhook": {
            "url": info_result.get("result", {}).get("url", ""),
            "pending_update_count": info_result.get("result", {}).get("pending_update_count", 0),
            "last_error_date": info_result.get("result", {}).get("last_error_date"),
            "last_error_message": info_result.get("result", {}).get("last_error_message"),
        },
        "set_webhook_ok": bool(set_result.get("ok")),
    }
    status, headers, body = _response(result, "200 OK" if result["ok"] else "502 Bad Gateway")
    start_response(status, headers)
    return [body]


handler = app
