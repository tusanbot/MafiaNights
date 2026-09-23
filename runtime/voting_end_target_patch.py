"""Durable end-of-target transition for serverless voting."""
from __future__ import annotations

import html

from runtime import voting_runtime
from runtime.voting_runtime import _resolve_name, _row_map


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
        records = voting_runtime._vote_records(v, target)
        voted = {int(x["user_id"]) for x in records}
        rows = _row_map(app)
        target_name = await _resolve_name(app, target, rows.get(target, {}).get("seat"))
        voter_text = voting_runtime._voter_lines(app, v, target)

        # Advance the durable cursor BEFORE Telegram calls. If Vercel/Telegram
        # interrupts the request, the scheduler tick can resume safely.
        last = idx + 1 >= len(targets)
        v["target_index"] = idx + 1
        v["started_at"] = None
        v["deadline"] = None
        v["phase"] = "round_finished_pending" if last else "next_target_pending"
        voting_runtime._put(app, v)

        message_id = v.get("vote_message_id")
        if message_id:
            try:
                await app.bot.edit_message_reply_markup(
                    chat_id=voting_runtime._gid(app),
                    message_id=int(message_id),
                    reply_markup=voting_runtime._disabled_vote_kb(),
                )
            except Exception:
                pass

        try:
            await app.bot.send_message(
                voting_runtime._gid(app),
                f"📊 <b>نتیجه رأی‌گیری برای {html.escape(target_name)}</b>\n\n"
                f"🗳 تعداد رأی: <b>{len(voted)}</b>\n"
                f"👥 رأی‌دهندگان:\n{voter_text}",
                parse_mode="HTML",
            )
        except Exception:
            # The persistent cursor above is already advanced; tick will finish
            # the next state on the next scheduler invocation.
            pass

        if last:
            await voting_runtime._finish_round(app)
        else:
            await voting_runtime._start_target(app)


    voting_runtime._end_target = end_target
    main._voting_end_target_patch_installed = True
    return True
