"""Single Vercel entrypoint for the Telegram bot.

Routes both public Telegram webhook traffic and the temporary authenticated
setup endpoint through one explicit WSGI entrypoint. The legacy route modules
remain available as backups and are imported lazily so setup requests do not
load the full game application.
"""
from __future__ import annotations

from typing import Any


def app(environ: dict[str, Any], start_response: Any) -> list[bytes]:
    path = str(environ.get("PATH_INFO") or environ.get("REQUEST_URI") or "")
    if path.rstrip("/").endswith("/setup"):
        from api.telegram.setup import app as setup_app

        return setup_app(environ, start_response)

    from api.telegram.webhook import app as webhook_app

    return webhook_app(environ, start_response)


handler = app
