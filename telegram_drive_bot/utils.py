"""Utility helpers for telegram_drive_bot."""
from __future__ import annotations

import math
import os
import re
import shutil
from dataclasses import dataclass
from datetime import timedelta
from typing import Tuple
from urllib.parse import urlparse

_MESSAGE_LINK_RE = re.compile(r"https?://t\.me/(?P<path>.+)")


class MessageLinkParseError(ValueError):
    """Raised when a Telegram message link cannot be parsed."""


def _normalize_link(link: str) -> str:
    if not link:
        raise MessageLinkParseError("Empty link provided")
    link = link.strip()
    if not link:
        raise MessageLinkParseError("Empty link provided")
    if not _MESSAGE_LINK_RE.match(link):
        link = f"https://t.me/{link}" if not link.startswith("https://") else link
    return link


def parse_message_link(link: str) -> Tuple[str, int]:
    """Parse a Telegram message link and return the chat identifier and message id.

    The chat identifier can be either a username or the numeric identifier of a
    private/supergroup chat. For links in the form ``https://t.me/c/<id>/<msg>``
    the returned chat id corresponds to the numeric peer id used by Pyrogram
    (``-100xxxxxxxxxx``).
    """

    link = _normalize_link(link)
    parsed = urlparse(link)
    path = parsed.path.strip("/")
    if not path:
        raise MessageLinkParseError("The link does not point to a specific message")
    parts = path.split("/")
    if len(parts) < 2:
        raise MessageLinkParseError("The link does not include a message id")

    if parts[0] == "c":
        if len(parts) < 3:
            raise MessageLinkParseError("Incomplete private chat link")
        try:
            raw_chat = int(parts[1])
            message_id = int(parts[2])
        except ValueError as exc:  # pragma: no cover - defensive programming
            raise MessageLinkParseError("Invalid numeric values in link") from exc
        # For t.me/c links the displayed id omits the -100 prefix.
        chat_id = -1000000000000 - raw_chat
        return str(chat_id), message_id

    chat_id = parts[0]
    try:
        message_id = int(parts[1])
    except ValueError as exc:
        raise MessageLinkParseError("Invalid message id") from exc
    return chat_id, message_id


def humanize_bytes(num_bytes: float) -> str:
    """Return a human-readable representation for the given byte count."""

    if not math.isfinite(num_bytes):
        return "0 B"
    num_bytes = max(num_bytes, 0.0)
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    if num_bytes == 0:
        return "0 B"
    order = int(math.log(num_bytes, 1024)) if num_bytes else 0
    order = min(order, len(units) - 1)
    value = num_bytes / (1024 ** order)
    return f"{value:.2f} {units[order]}"


def format_timedelta(delta_seconds: float) -> str:
    """Format seconds into a human readable time span."""

    delta_seconds = max(delta_seconds, 0.0)
    delta = timedelta(seconds=int(delta_seconds))
    total_seconds = int(delta.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    parts = []
    if hours:
        parts.append(f"{hours}h")
    if minutes or hours:
        parts.append(f"{minutes}m")
    parts.append(f"{seconds}s")
    return " ".join(parts)


def disk_usage(path: str = "/") -> shutil.disk_usage:
    """Return disk usage statistics for ``path``.

    This helper exists so that tests can patch it easily.
    """

    return shutil.disk_usage(path)


@dataclass
class TrafficStats:
    """Simple structure capturing network traffic statistics."""

    bytes_sent: int
    bytes_recv: int

    @property
    def total(self) -> int:
        return self.bytes_sent + self.bytes_recv


def calculate_left_traffic(limit_gb: float | None, stats: TrafficStats) -> Tuple[str, str]:
    """Calculate human readable network usage and remaining traffic.

    If ``limit_gb`` is ``None`` the remaining traffic is reported as ``Unlimited``.
    """

    used = humanize_bytes(stats.total)
    if limit_gb is None or limit_gb <= 0:
        return used, "Unlimited"
    limit_bytes = limit_gb * (1024 ** 3)
    left_bytes = max(limit_bytes - stats.total, 0)
    return used, humanize_bytes(left_bytes)


def ensure_directory(path: str) -> None:
    """Ensure that ``path`` exists."""

    os.makedirs(path, exist_ok=True)
