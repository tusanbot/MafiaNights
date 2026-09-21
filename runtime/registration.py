"""Canonical player registration flow for Mafia Nights.

Registration is separate from game membership: a Telegram user must have a
Persian nickname and a registered_at timestamp before using bot features.
"""
from __future__ import annotations

import html
import logging
import re
from typing import Any

from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from player_repository import PlayerRepository


_PERSIAN_LETTERS = set("ءآابپتثجچحخدذرزژسشصضطظعغفقکگلمنوهیئؤ")
_PERSIAN_NORMALIZE = str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک", "ة": "ه"})


class RegistrationStates(StatesGroup):
    waiting_name = State()


def normalize_name(value: str | None) -> str:
    value = (value or "").strip().translate(_PERSIAN_NORMALIZE)
    return " ".join(value.split())


def valid_persian_name(value: str | None) -> bool:
    value = normalize_name(value)
    if not value or len(value) > 32:
        return False
    parts = value.split(" ")
    if any(not part for part in parts):
        return False
    return all(char in _PERSIAN_LETTERS for part in parts for char in part)


def is_registered(user_id: int) -> bool:
    try:
        with PlayerRepository().SessionLocal() as session:
            row = session.execute(
                __import__("sqlalchemy").text(
                    "select registered_at from public.mafia_players where id=:id limit 1"
                ),
                {"id": int(user_id)},
            ).scalar()
            return row is not None
    except Exception:
        logging.exception("registration: failed to check registration for %s", user_id)
        return False


def registration_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(row_width=1).add(
        InlineKeyboardButton("📝 ثبت‌نام", callback_data="registration:start")
    )


async def private_registration_link(app: Any) -> str:
    username = getattr(app, "_registration_bot_username", None)
    if not username:
        me = await app.bot.get_me()
        username = str(me.username or "").lstrip("@")
        app._registration_bot_username = username
    if not username:
        raise RuntimeError("Bot username is unavailable")
    return f"https://t.me/{username}?start=register"


async def group_registration_keyboard(app: Any) -> InlineKeyboardMarkup:
    try:
        url = await private_registration_link(app)
        return InlineKeyboardMarkup(row_width=1).add(
            InlineKeyboardButton("📝 ثبت‌نام در پیوی ربات", url=url)
        )
    except Exception:
        logging.exception("registration: failed to build private deep link")
        return registration_keyboard()


async def prompt_registration(message: types.Message, app: Any, *, group: bool = False) -> None:
    if group:
        markup = await group_registration_keyboard(app)
        text = (
            "🔐 <b>برای استفاده از Mafia Nights ابتدا باید ثبت‌نام کنید.</b>\n\n"
            "روی دکمه زیر بزنید تا وارد پیوی ربات شوید و ثبت‌نام را انجام دهید."
        )
    else:
        markup = registration_keyboard()
        text = (
            "👋 <b>به Mafia Nights خوش آمدید.</b>\n\n"
            "برای استفاده از ربات ابتدا ثبت‌نام کنید.\n"
            "نام خود را وارد کنید؛ این نام به‌عنوان نام مستعار شما ثبت می‌شود.\n\n"
            "فقط حروف فارسی و فاصله مجاز است."
        )
    await message.answer(text, parse_mode="HTML", reply_markup=markup)


async def start(app: Any, message: types.Message) -> bool:
    """Handle /start. Return True when the registration flow owns the update."""
    if message.chat.type != "private":
        return False
    raw = str(getattr(message, "text", "") or "").strip()
    parameter = ""
    if " " in raw:
        parameter = raw.split(" ", 1)[1].strip().casefold()
    if is_registered(int(message.from_user.id)) and parameter != "register":
        return False
    if is_registered(int(message.from_user.id)):
        await message.answer(
            "✅ حساب شما قبلاً ثبت شده است.\n\n"
            "اگر می‌خواهید نام مستعار را تغییر دهید، از «پروفایل» استفاده کنید."
        )
        return True
    await prompt_registration(message, app, group=False)
    return True


async def begin(callback: types.CallbackQuery, state: FSMContext | None = None, **kwargs: Any) -> None:
    # aiogram callback dispatchers may inject FSMContext by keyword depending on
    # which compatibility wrapper owns the callback. Accept both forms so the
    # registration button cannot fail before the FSM state is created.
    if state is None:
        state = kwargs.get("state")
    if state is None:
        raise RuntimeError("registration FSM state is unavailable")
    await state.set_state(RegistrationStates.waiting_name)
    await callback.message.answer(
        "✍️ <b>نام خود را وارد کنید:</b>\n\n"
        "فقط حروف فارسی و فاصله مجاز است؛ حداکثر ۳۲ نویسه.\n"
        "عدد، انگلیسی، ایموجی و علامت پذیرفته نمی‌شود.",
        parse_mode="HTML",
    )
    await callback.answer()


async def save_name(message: types.Message, state: FSMContext) -> None:
    value = normalize_name(message.text)
    if not valid_persian_name(value):
        await message.answer(
            "❌ نام نامعتبر است.\n\n"
            "نام باید فقط شامل حروف فارسی باشد و در صورت چندبخشی بودن با فاصله جدا شود.\n"
            "حداکثر ۳۲ نویسه مجاز است."
        )
        return
    try:
        with PlayerRepository().SessionLocal() as session:
            from sqlalchemy import text
            session.execute(
                text("""
                    insert into public.mafia_players
                        (id, username, first_name, last_name, nickname, registered_at, created_at, updated_at)
                    values
                        (:id, :username, :first_name, null, :nickname, now(), now(), now())
                    on conflict (id) do update set
                        username = coalesce(excluded.username, public.mafia_players.username),
                        first_name = coalesce(excluded.first_name, public.mafia_players.first_name),
                        nickname = excluded.nickname,
                        registered_at = now(),
                        updated_at = now()
                """),
                {
                    "id": int(message.from_user.id),
                    "username": message.from_user.username,
                    "first_name": value,
                    "nickname": value,
                },
            )
            session.commit()
        await state.finish()
        try:
            from player_service import player_service
            player_service.invalidate(int(message.from_user.id))
        except Exception:
            pass
        await message.answer(
            f"✅ ثبت‌نام با موفقیت انجام شد.\n\n"
            f"👤 نام مستعار شما: <b>{html.escape(value)}</b>\n\n"
            "حالا می‌توانید از تمام امکانات ربات استفاده کنید.",
            parse_mode="HTML",
        )
    except Exception:
        logging.exception("registration: save failed for %s", message.from_user.id)
        await message.answer("❌ ثبت‌نام انجام نشد. لطفاً دوباره نام خود را ارسال کنید.")


def install(app: Any) -> None:
    if getattr(app, "_registration_installed", False):
        return
    dp = app.dp
    dp.register_callback_query_handler(
        begin, lambda c: str(c.data or "") == "registration:start", state="*"
    )
    dp.register_message_handler(
        save_name,
        state=RegistrationStates.waiting_name,
        content_types=types.ContentTypes.TEXT,
    )
    app._registration_installed = True
