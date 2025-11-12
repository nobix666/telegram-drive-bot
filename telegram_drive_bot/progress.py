"""Progress helpers for reporting download/upload speeds."""
from __future__ import annotations

import asyncio
import time
from typing import Optional

from pyrogram.errors import MessageNotModified
from pyrogram.types import Message

from .utils import format_timedelta, humanize_bytes


class ProgressReporter:
    """Utility callable that can be passed as a Pyrogram progress callback."""

    def __init__(self, status_message: Message, stage: str) -> None:
        self._message = status_message
        self._stage = stage
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:  # pragma: no cover - fallback for sync usage
            self._loop = asyncio.get_event_loop()
        self._start_time = time.time()
        self._last_update = 0.0
        self._last_value = 0

    def set_stage(self, stage: str) -> None:
        self._stage = stage
        self._start_time = time.time()
        self._last_update = 0.0
        self._last_value = 0

    def __call__(self, current: int, total: int) -> None:
        now = time.time()
        if now - self._last_update < 1 and current != total:
            return
        delta = current - self._last_value
        delta_time = max(now - self._last_update, 1e-3)
        speed = delta / delta_time if delta_time > 0 else 0
        eta = (total - current) / speed if speed > 0 else 0
        text = (
            f"{self._stage}\n"
            f"{humanize_bytes(current)} / {humanize_bytes(total)}\n"
            f"Speed: {humanize_bytes(speed)}/s\n"
            f"ETA: {format_timedelta(eta)}"
        )
        self._last_update = now
        self._last_value = current
        self._loop.create_task(self._safe_edit(text))

    async def _safe_edit(self, text: str) -> None:
        try:
            await self._message.edit_text(text)
        except MessageNotModified:
            pass
        except Exception:  # pragma: no cover - defensive logging path
            # Swallow exceptions to avoid breaking the progress callback.
            pass

    async def finalize(self, extra: Optional[str] = None) -> None:
        text = f"{self._stage} completed"
        if extra:
            text = f"{text}\n{extra}"
        await self._safe_edit(text)
