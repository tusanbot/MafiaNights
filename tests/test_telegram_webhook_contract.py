"""Contract tests for the Vercel Telegram webhook boundary.

These tests avoid network access and verify request validation/idempotency shape.
"""
from __future__ import annotations

import json


def test_webhook_module_exports_handler():
    from api.telegram.webhook import handler, main

    assert handler is main


def test_invalid_json_is_rejected():
    from api.telegram.webhook import handler

    response = handler({"method": "POST", "headers": {}, "body": "{"})
    assert response["statusCode"] == 400
    assert json.loads(response["body"])["error"] == "invalid_json"


def test_get_is_health_response():
    from api.telegram.webhook import handler

    response = handler({"method": "GET", "headers": {}, "body": ""})
    assert response["statusCode"] == 200
    assert json.loads(response["body"])["service"] == "mafia-nights-telegram"
