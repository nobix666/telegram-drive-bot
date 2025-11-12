# Telegram Drive Bot

A Telegram userbot that clones posts and media into your Saved Messages. It supports
single-message cloning, media-group cloning, cancellation, runtime status reporting, and
login flows with optional two-factor authentication.

## Features

- `/single <link>`: clone a single message or file by providing its Telegram link.
- `/batch <link>`: clone an entire media group (albums or multi-message posts).
- `/cancel`: cancel the currently running cloning task.
- `/status`: display CPU, RAM, disk usage, and network traffic information for the VPS.
- Progress updates with download and upload speeds while cloning.
- Media uploads include generated thumbnails to avoid missing preview errors.
- All cloned messages are sent to Saved Messages (`me`) for reliability.

## Requirements

- Python 3.11+
- Telegram API credentials (API ID and API Hash)
- A VPS or machine where you can run a persistent Python process

Install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Configuration

Set the following environment variables before running the bot or the login helper:

- `API_ID`: Telegram API ID from https://my.telegram.org/apps
- `API_HASH`: Telegram API Hash from the same page
- `SESSION_NAME` (optional): name for the local session file (defaults to
  `telegram_drive_bot`)
- `ALLOWED_USER_IDS` (optional): comma-separated Telegram user IDs allowed to use the
  commands. If omitted, anyone who can message the account can interact with it.
- `TRAFFIC_LIMIT_GB` (optional): monthly traffic limit in gigabytes. The `/status`
  command will show the remaining traffic if provided.

## Logging in

First, create a user session so that Pyrogram can act on behalf of your account:

```bash
python login.py
```

You will be asked for your phone number, the login code (hyphens are automatically
stripped, so `1-2-3-4-5` works), and your two-factor password if enabled.

## Running the bot

After a successful login, start the bot with:

```bash
python -m telegram_drive_bot.bot
```

Keep the process running to allow the bot to listen for commands. Use a process manager
like `systemd`, `screen`, or `tmux` on your VPS as needed.

## Usage notes

- Provide full Telegram message links such as `https://t.me/c/<chat>/<msg>` or
  `https://t.me/channelusername/<msg>` with `/single` and `/batch`.
- `/batch` automatically detects the entire media group for the provided message.
- Media is downloaded to a temporary directory and uploaded to Saved Messages. The bot
  displays live download and upload speeds during the process.
- `/cancel` interrupts the active cloning task in the current chat.

## License

MIT
