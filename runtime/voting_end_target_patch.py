"""Durable end-of-target transition for serverless voting."""
from __future__ import annotations

import html

from runtime import voting_runtime
from runtime.voting_timer_patch import _resolve_name, _row_map


def install(main):
    if getattr(main, "_voting_end_target_patch_installed", False):
        return False

    async def end_target(app):
        v = voting_runtime._v(app)
        targets = [int(x) for x in (v.get("targets") or [])]
        idx = int(v.get("target_index") or 0)
        if idx >= len(targets):
            return await voting_runtime._finish_round(app)

        target = targets[idx]
        voted = {int(x) for x in (v.get("votes") or {}).get(str(target), [])}
        rows = _row_map(app)
        target_name = await _resolve_name(app, target, rows.get(target, {}).get("seat"))
        voter_names = []
        for uid in sorted(voted):
            voter_names.append(await _resolve_name(app, uid, rows.get(uid, {}).get("seat")))
        voter_text = "\n".join(f"• {html.escape(name)}" for name in voter_names) or "• هیچ‌کس"

        # Consume the current deadline BEFORE making another Telegram request.
        # The next scheduler tick is then responsible for the next transition.
        next_index = idx + 1
        v["target_index"] = next_index
        v["started_at"] = None
        v["deadline"] = None
        if next_index >= len(targets):
            v["phase"] = "round_finished_pending"
        else:
            v["phase"] = "waiting"
            v["started_at"] = None
            v["deadline"] = None
        voting_runtime._put(app, v)

        await app.bot.send_message(
            voting_runtime._gid(app),
            f"📊 <b>نتیجه رأی‌گیری برای {html.escape(target_name)}</b>\n\n"
            f"🗳 تعداد رأی: <b>{len(voted)}</b>\n"
            f"👥 رأی‌دهندگان:\n{voter_text}",
            parse_mode="HTML",
        )

        # Do not chain another Telegram send from the same scheduler request.
        # The next 10-second tick advances either to the next target or to the
        # round-finished UI.

    voting_runtime._end_target = end_target
    main._voting_end_target_patch_installed = True
    return True
