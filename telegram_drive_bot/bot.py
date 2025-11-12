"""Main Telegram bot implementation."""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Dict, Optional, Set

import psutil
from pyrogram import Client, enums, filters, handlers
from pyrogram.types import Message

from .clone import CloneError, clone_messages, fetch_media_group, fetch_target_message
from .utils import TrafficStats, calculate_left_traffic, disk_usage, humanize_bytes

logger = logging.getLogger(__name__)


@dataclass
class BotConfig:
    api_id: int
    api_hash: str
    session_name: str
    allowed_users: Optional[Set[int]]
    traffic_limit_gb: Optional[float]

    @classmethod
    def from_env(cls) -> "BotConfig":
        try:
            api_id = int(os.environ["API_ID"])
            api_hash = os.environ["API_HASH"]
        except KeyError as exc:  # pragma: no cover - defensive configuration
            raise RuntimeError("API_ID and API_HASH environment variables must be set") from exc
        session_name = os.getenv("SESSION_NAME", "telegram_drive_bot")
        limit_raw = os.getenv("TRAFFIC_LIMIT_GB")
        traffic_limit_gb = float(limit_raw) if limit_raw else None
        allowed_raw = os.getenv("ALLOWED_USER_IDS")
        allowed_users = None
        if allowed_raw:
            allowed_users = {int(part.strip()) for part in allowed_raw.split(",") if part.strip()}
        return cls(api_id, api_hash, session_name, allowed_users, traffic_limit_gb)


class TelegramDriveBot:
    def __init__(self, config: BotConfig) -> None:
        self.config = config
        self.client = Client(config.session_name, api_id=config.api_id, api_hash=config.api_hash)
        self._active_tasks: Dict[int, asyncio.Task] = {}

        self.client.add_handler(handlers.MessageHandler(self.start_handler, filters.command("start")))
        self.client.add_handler(handlers.MessageHandler(self.help_handler, filters.command("help")))
        self.client.add_handler(handlers.MessageHandler(self.status_handler, filters.command("status")))
        self.client.add_handler(handlers.MessageHandler(self.single_handler, filters.command("single")))
        self.client.add_handler(handlers.MessageHandler(self.batch_handler, filters.command("batch")))
        self.client.add_handler(handlers.MessageHandler(self.cancel_handler, filters.command("cancel")))

    async def start_handler(self, client: Client, message: Message) -> None:
        if not self._is_authorized(message):
            return
        await message.reply_text(
            "Welcome! Use /single <link> to clone a single message or /batch <link> to clone an entire media group."
        )

    async def help_handler(self, client: Client, message: Message) -> None:
        if not self._is_authorized(message):
            return
        help_text = (
            "<b>Available commands</b>\n"
            "/single &lt;link&gt; – Clone a single Telegram message.\n"
            "/batch &lt;link&gt; – Clone an entire media group/post.\n"
            "/cancel – Cancel the current cloning task.\n"
            "/status – Show VPS resource usage."
        )
        await message.reply_text(help_text, parse_mode=enums.ParseMode.HTML)

    async def status_handler(self, client: Client, message: Message) -> None:
        if not self._is_authorized(message):
            return
        cpu_percent = psutil.cpu_percent(interval=0.5)
        virtual_memory = psutil.virtual_memory()
        disk = disk_usage("/")
        disk_percent = (disk.used / disk.total) * 100 if disk.total else 0
        traffic = psutil.net_io_counters()
        used_traffic, left_traffic = calculate_left_traffic(
            self.config.traffic_limit_gb, TrafficStats(traffic.bytes_sent, traffic.bytes_recv)
        )
        status_text = (
            f"<b>CPU:</b> {cpu_percent:.1f}%\n"
            f"<b>RAM:</b> {humanize_bytes(virtual_memory.used)} / {humanize_bytes(virtual_memory.total)} "
            f"({virtual_memory.percent:.1f}%)\n"
            f"<b>Disk:</b> {humanize_bytes(disk.used)} / {humanize_bytes(disk.total)} "
            f"({disk_percent:.1f}%)\n"
            f"<b>Network used:</b> {used_traffic}\n"
            f"<b>Traffic left:</b> {left_traffic}"
        )
        await message.reply_text(status_text, parse_mode=enums.ParseMode.HTML)

    async def single_handler(self, client: Client, message: Message) -> None:
        if not await self._prepare_task(message):
            return
        args = message.command
        if not args or len(args) < 2:
            await message.reply_text("Usage: /single <message link>")
            self._active_tasks.pop(message.chat.id, None)
            return
        link = args[1]
        status_message = await message.reply_text("Fetching message...")

        async def runner() -> None:
            try:
                target_message = await fetch_target_message(client, link)
                await clone_messages(client, [target_message], status_message)
            except asyncio.CancelledError:
                await status_message.edit_text("Task cancelled")
                raise
            except CloneError as exc:
                await status_message.edit_text(f"Failed: {exc}")
            except Exception as exc:  # pragma: no cover - network dependent
                logger.exception("Unexpected error while cloning message")
                await status_message.edit_text("Unexpected error during cloning")

        task = asyncio.create_task(runner())
        self._register_task(message.chat.id, task)

    async def batch_handler(self, client: Client, message: Message) -> None:
        if not await self._prepare_task(message):
            return
        args = message.command
        if not args or len(args) < 2:
            await message.reply_text("Usage: /batch <message link>")
            self._active_tasks.pop(message.chat.id, None)
            return
        link = args[1]
        status_message = await message.reply_text("Fetching media group...")

        async def runner() -> None:
            try:
                target_message = await fetch_target_message(client, link)
                group = await fetch_media_group(client, target_message)
                await clone_messages(client, group, status_message)
            except asyncio.CancelledError:
                await status_message.edit_text("Task cancelled")
                raise
            except CloneError as exc:
                await status_message.edit_text(f"Failed: {exc}")
            except Exception as exc:  # pragma: no cover - network dependent
                logger.exception("Unexpected error while cloning media group")
                await status_message.edit_text("Unexpected error during cloning")

        task = asyncio.create_task(runner())
        self._register_task(message.chat.id, task)

    async def cancel_handler(self, client: Client, message: Message) -> None:
        task = self._active_tasks.get(message.chat.id)
        if not task:
            await message.reply_text("No active task to cancel.")
            return
        task.cancel()
        await message.reply_text("Cancellation requested.")

    async def _prepare_task(self, message: Message) -> bool:
        if not self._is_authorized(message):
            return False
        if message.chat.id in self._active_tasks:
            await message.reply_text("Another task is already running. Use /cancel to stop it first.")
            return False
        return True

    def _register_task(self, chat_id: int, task: asyncio.Task) -> None:
        self._active_tasks[chat_id] = task

        def _cleanup(_task: asyncio.Task) -> None:
            self._active_tasks.pop(chat_id, None)

        task.add_done_callback(_cleanup)

    def _is_authorized(self, message: Message) -> bool:
        if self.config.allowed_users is None:
            return True
        user = message.from_user
        if not user:
            return False
        if user.id not in self.config.allowed_users:
            return False
        return True

    def run(self) -> None:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        self.client.run()


def main() -> None:
    config = BotConfig.from_env()
    bot = TelegramDriveBot(config)
    bot.run()


if __name__ == "__main__":
    main()
