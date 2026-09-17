from __future__ import annotations

import logging


def _handler(item):
    return getattr(item, "handler", None) or getattr(item, "callback", None)


def _registry(dp):
    return getattr(getattr(dp, "callback_query_handlers", None), "handlers", [])


def _active_order(main):
    occupied = set()
    for seat, uid in (getattr(main, "player_slots", {}) or {}).items():
        try:
            if uid:
                occupied.add(int(seat))
        except Exception:
            pass
    if not occupied:
        return []
    selected = getattr(main, "current_speaker", None)
    if selected is None:
        selected = getattr(main, "_canonical_speaker_seat", None)
    try:
        selected = int(selected) if selected is not None else None
    except Exception:
        selected = None
    seats = sorted(occupied)
    if selected not in occupied:
        return seats
    i = seats.index(selected)
    return seats[i:] + seats[:i]


def _persist(main, seat):
    try:
        gid = int(getattr(main, "group_chat_id", 0) or 0)
        game = main.runtime.state.active_game(gid)
        if not game:
            return
        state = dict(game.get("state") or {})
        state["speaker_seat"] = int(seat)
        main.runtime.state.games.update_game(game["id"], state=state)
    except Exception:
        logging.exception("speaker order persistence failed")


def install(main):
    if getattr(main, "_speaker_order_authority", False):
        return False
    reg = _registry(main.dp)
    main._speaker_order_authority = True

    # Legacy speaker selectors remain intact (including desktop changes), but
    # their result becomes the canonical turn-order source for the stable engine.
    for item in list(reg):
        fn = _handler(item)
        name = getattr(fn, "__name__", "")
        if name not in {"speaker_auto", "head_set_handler"} or getattr(fn, "_speaker_authority_wrapped", False):
            continue
        original = fn
        async def wrapped(callback, _original=original):
            result = await _original(callback)
            seat = getattr(main, "current_speaker", None)
            if seat is None:
                data = str(callback.data or "")
                if data.startswith("head_set_"):
                    try: seat = int(data.rsplit("_", 1)[1])
                    except Exception: seat = None
            if seat is not None:
                try:
                    seat = int(seat)
                    main._canonical_speaker_seat = seat
                    order = _active_order(main)
                    if order:
                        main.turn_order = order
                        main.current_turn_index = 0
                    _persist(main, seat)
                except Exception:
                    logging.exception("failed to apply selected speaker order")
            return result
        wrapped.__name__ = name
        wrapped._speaker_authority_wrapped = True
        try: item.handler = wrapped
        except Exception: item.callback = wrapped

    # Start-round handlers are wrapped last so every route uses the selected
    # speaker, even when an older start-turn handler is the first match.
    for item in list(reg):
        fn = _handler(item)
        name = getattr(fn, "__name__", "")
        if name not in {"start_round", "start_round_clean", "handle_start_turn"} or getattr(fn, "_speaker_start_wrapped", False):
            continue
        original = fn
        async def start_wrapped(callback, _original=original):
            order = _active_order(main)
            if order:
                main.turn_order = order
                main.current_turn_index = 0
                main._stable_normal_order = list(order)
                main._gm_normal_order = list(order)
            return await _original(callback)
        start_wrapped.__name__ = name
        start_wrapped._speaker_start_wrapped = True
        try: item.handler = start_wrapped
        except Exception: item.callback = start_wrapped

    logging.info("SPEAKER ORDER AUTHORITY active")
    return True
