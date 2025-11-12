"""Core cloning logic for copying Telegram messages to Saved Messages."""
from __future__ import annotations

import os
import tempfile
from typing import Iterable, List

from pyrogram import Client
from pyrogram.types import Message

from .progress import ProgressReporter
from .utils import MessageLinkParseError, ensure_directory, parse_message_link


class CloneError(RuntimeError):
    """Raised when a cloning action fails."""


async def fetch_target_message(client: Client, link: str) -> Message:
    try:
        chat_id_raw, message_id = parse_message_link(link)
    except MessageLinkParseError as exc:
        raise CloneError(str(exc)) from exc

    chat_id = int(chat_id_raw) if chat_id_raw.startswith("-") and chat_id_raw[1:].isdigit() else chat_id_raw
    try:
        message = await client.get_messages(chat_id, message_id)
    except Exception as exc:  # pragma: no cover - network dependent
        raise CloneError("Unable to fetch the referenced message") from exc
    if not message:
        raise CloneError("Message not found")
    return message


async def fetch_media_group(client: Client, message: Message) -> List[Message]:
    if not message.media_group_id:
        return [message]
    try:
        group = await client.get_media_group(message.chat.id, message.id)
    except Exception as exc:  # pragma: no cover - network dependent
        raise CloneError("Unable to fetch media group") from exc
    if not group:
        raise CloneError("Media group is empty")
    return group


async def _send_text(client: Client, message: Message) -> None:
    text = message.text or message.caption or ""
    if not text:
        return
    await client.send_message(
        "me",
        text,
        entities=message.entities or message.caption_entities,
        disable_web_page_preview=message.web_page is None,
    )


async def _clone_media_message(client: Client, message: Message, status_message: Message, tmpdir: str) -> None:
    progress = ProgressReporter(status_message, "Downloading")
    try:
        file_path = await client.download_media(
            message,
            file_name=tmpdir,
            progress=progress,
        )
    except Exception as exc:  # pragma: no cover - network dependent
        raise CloneError("Failed to download media") from exc

    if not file_path:
        await progress.finalize("Nothing to download")
        return

    caption = message.caption or ""
    caption_entities = message.caption_entities

    progress.set_stage("Uploading")
    upload_kwargs = {
        "caption": caption,
        "caption_entities": caption_entities,
        "progress": progress,
    }

    thumb_path = await _thumbnail_for_message(client, message, tmpdir)
    if thumb_path:
        upload_kwargs["thumb"] = thumb_path

    try:
        if message.photo:
            await client.send_photo("me", file_path, **upload_kwargs)
        elif message.video:
            await client.send_video(
                "me",
                file_path,
                supports_streaming=True,
                duration=message.video.duration if message.video else None,
                width=message.video.width if message.video else None,
                height=message.video.height if message.video else None,
                **upload_kwargs,
            )
        elif message.document:
            await client.send_document("me", file_path, file_name=os.path.basename(file_path), **upload_kwargs)
        elif message.animation:
            await client.send_animation("me", file_path, **upload_kwargs)
        elif message.audio:
            await client.send_audio(
                "me",
                file_path,
                duration=message.audio.duration if message.audio else None,
                performer=message.audio.performer if message.audio else None,
                title=message.audio.title if message.audio else None,
                **upload_kwargs,
            )
        elif message.voice:
            await client.send_voice(
                "me",
                file_path,
                duration=message.voice.duration if message.voice else None,
                **upload_kwargs,
            )
        elif message.video_note:
            await client.send_video_note(
                "me",
                file_path,
                duration=message.video_note.duration if message.video_note else None,
                length=message.video_note.length if message.video_note else None,
                **upload_kwargs,
            )
        else:
            await client.send_document("me", file_path, **upload_kwargs)
    except Exception as exc:  # pragma: no cover - network dependent
        raise CloneError("Failed to upload media") from exc
    finally:
        try:
            os.remove(file_path)
        except OSError:
            pass
        if thumb_path and os.path.exists(thumb_path):
            try:
                os.remove(thumb_path)
            except OSError:
                pass
    await progress.finalize()


async def _thumbnail_for_message(client: Client, message: Message, tmpdir: str) -> str | None:
    from PIL import Image, ImageDraw, ImageFont

    # Try to fetch an existing thumbnail from Telegram if available.
    media = message.photo or message.video or message.document or message.animation or message.audio or message.video_note
    if media and getattr(media, "thumbnails", None):
        try:
            return await client.download_media(media.thumbnails[-1], file_name=os.path.join(tmpdir, "thumb.jpg"))
        except Exception:  # pragma: no cover - network dependent
            pass

    # Generate a placeholder thumbnail.
    thumb_path = os.path.join(tmpdir, f"thumb_{message.id}.jpg")
    size = (320, 320)
    background = (34, 40, 49)
    image = Image.new("RGB", size, color=background)
    draw = ImageDraw.Draw(image)
    label = _thumbnail_label(message)
    text_color = (240, 240, 240)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 48)
    except Exception:
        font = ImageFont.load_default()
    text_bbox = draw.textbbox((0, 0), label, font=font)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]
    position = ((size[0] - text_width) / 2, (size[1] - text_height) / 2)
    draw.text(position, label, fill=text_color, font=font)
    image.save(thumb_path, "JPEG", quality=85)
    return thumb_path


def _thumbnail_label(message: Message) -> str:
    if message.photo:
        return "PHOTO"
    if message.video:
        return "VIDEO"
    if message.document:
        return "DOC"
    if message.animation:
        return "GIF"
    if message.audio:
        return "AUDIO"
    if message.voice:
        return "VOICE"
    if message.video_note:
        return "NOTE"
    return "FILE"


async def clone_messages(client: Client, messages: Iterable[Message], status_message: Message) -> None:
    ensure_directory("downloads")
    with tempfile.TemporaryDirectory(dir="downloads") as tmpdir:
        for msg in messages:
            if msg.media:
                await _clone_media_message(client, msg, status_message, tmpdir)
            else:
                await status_message.edit_text("Sending text message...")
                await _send_text(client, msg)
    await status_message.edit_text("Clone completed successfully")
