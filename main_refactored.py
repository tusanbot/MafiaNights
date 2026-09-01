"""MafiaNights clean Telegram application target.

This file is intentionally separate from ``main.py`` during migration.
``main.py`` remains the untouched rollback/reference implementation.

Design rules:
- PersistentGameRuntime is the only authoritative game-state boundary.
- No mutable module-level game containers are used.
- Telegram message IDs, asyncio Tasks and anti-spam timestamps live inside
  one application instance and are never persisted as game truth.
- Lobby/turn/challenge/day mutations go through the persistent runtimes.
- The file is a migration target; production entry is switched only after
  integration tests against the real bot/database pass.
"""
from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils import executor
from aiogram.utils.exceptions import MessageCantBeEdited, MessageNotModified, MessageToEditNotFound

from mafia_addons import MafiaAddons
from player_service import player_service
from runtime.game_runtime import PersistentGameRuntime
from runtime.game_state_machine import Phase
from runtime.ephemeral_recovery import EphemeralRecoveryManager


DEFAULT_TURN_DURATION = 120
DEFAULT_CHALLENGE_DURATION = 60

# ==============================
# گروه‌های مجاز اجرای ربات
# ==============================
# فقط یک گروه فعال است.
# گروه تست قبلی:
# ALLOWED_GROUP_ID = -1003080272814
# گروه اصلی قبلی:
# ALLOWED_GROUP_ID = -1001760002160
# گروه فعال فعلی:
ALLOWED_GROUP_ID = -1002356353761

SCENARIOS_FILE = Path("scenarios.json")


class AddScenario(StatesGroup):
    waiting_for_name = State()
    waiting_for_roles = State()
    waiting_for_min_players = State()


@dataclass
class TelegramRuntime:
    """Process-local Telegram/UI state only.

    Nothing in this object is authoritative game state. Recreating it after a
    restart from PersistentGameRuntime is expected and safe.
    """
    group_chat_id: Optional[int] = None
    lobby_message_id: Optional[int] = None
    game_message_id: Optional[int] = None
    current_turn_message_id: Optional[int] = None
    waiting_message_id: Optional[int] = None
    turn_timer_task: Optional[asyncio.Task] = None
    last_next_at: float = 0.0
    recovered_turn_plans: dict[int, dict[str, Any]] = field(default_factory=dict)
    recovered_challenges: list[dict[str, Any]] = field(default_factory=list)
