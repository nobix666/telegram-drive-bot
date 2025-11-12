"""Interactive login helper for creating a Pyrogram user session."""
from __future__ import annotations

from getpass import getpass

from pyrogram import Client
from pyrogram.errors import PasswordHashInvalid, PhoneCodeInvalid, SessionPasswordNeeded

from telegram_drive_bot.bot import BotConfig


def main() -> int:
    config = BotConfig.from_env()
    client = Client(config.session_name, api_id=config.api_id, api_hash=config.api_hash)
    client.connect()
    if client.is_authorized():
        print("Already logged in.")
        client.disconnect()
        return 0

    phone_number = input("Enter your phone number (international format): ").strip()
    if not phone_number:
        print("Phone number is required.")
        return 1

    sent_code = client.send_code(phone_number)
    code = input("Enter the login code (use 1-2-3-4-5 format if necessary): ").replace("-", "").replace(" ", "")
    try:
        client.sign_in(phone_number=phone_number, phone_code=code, phone_code_hash=sent_code.phone_code_hash)
    except SessionPasswordNeeded:
        password = getpass("Enter your two-factor password: ")
        try:
            client.check_password(password=password)
        except PasswordHashInvalid:
            print("Invalid two-factor authentication password.")
            client.disconnect()
            return 1
    except PhoneCodeInvalid:
        print("Invalid login code.")
        client.disconnect()
        return 1

    print("Login successful. Session saved to disk.")
    client.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
