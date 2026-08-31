"""Platform-neutral adapter contracts.

The game core must not depend on Telegram, Rubika, Bale, or any other chat
transport. Adapters translate platform updates into domain/application calls.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Mapping


class PlatformAdapter(ABC):
    """Minimal contract implemented by each chat platform."""

    name: str

    @abstractmethod
    async def handle_update(self, update: Mapping[str, Any]) -> Any:
        """Translate one platform update into application behavior."""
        raise NotImplementedError
