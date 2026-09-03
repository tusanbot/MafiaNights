"""Hard guard: extra turns never accept challenge requests."""
from aiogram.dispatcher.handler import CancelHandler


def install(main):
    dp = main.dp
    registry = getattr(getattr(dp, "callback_query_handlers", None), "handlers", None)
    if registry is None:
        return False

    async def block_extra_challenge(callback):
        if getattr(main, "_gm_extra_turn_active", False):
            await callback.answer("⛔ ترن اضافه امکان چالش ندارد.", show_alert=True)
            raise CancelHandler()

    block_extra_challenge.__name__ = "extra_turn_challenge_guard"
    dp.register_callback_query_handler(
        block_extra_challenge,
        lambda c: str(getattr(c, "data", "") or "").startswith("challenge_request_"),
        state="*",
    )

    # This must be before every legacy challenge-request handler so a forged
    # callback cannot bypass the UI restriction.
    handlers = getattr(dp.callback_query_handlers, "handlers", [])
    for i, item in enumerate(handlers):
        if getattr(getattr(item, "handler", None), "__name__", "") == "extra_turn_challenge_guard":
            handlers.insert(0, handlers.pop(i))
            break
    return True
