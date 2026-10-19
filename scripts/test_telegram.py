"""Manual Telegram connectivity test for Whale Intelligence.
Credentials are read from GitHub Actions secrets and never printed.
"""
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        print("ERROR: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is missing.")
        return 1
    if "\n" in token or "/" in token or ":" not in token:
        print("ERROR: Telegram bot token format is invalid.")
        return 1
    if not (chat_id.lstrip("-").isdigit()):
        print("ERROR: TELEGRAM_CHAT_ID should be a numeric chat ID.")
        return 1
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    message = (
        "🐋 WHALE INTELLIGENCE V3\n"
        "✅ Tes notifikasi Telegram berhasil.\n"
        f"Waktu: {stamp}\n"
        "GitHub Actions dapat mengirim pesan melalui bot.\n"
        "Notifikasi whale otomatis dikirim hanya saat perubahan posisi terdeteksi.\n"
        "⚠️ Bukan sinyal trading."
    )
    body = json.dumps({"chat_id": chat_id, "text": message}).encode("utf-8")
    req = urllib.request.Request(
        "https://api.telegram.org/bot" + token + "/sendMessage",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            result = json.loads(response.read(65536))
        if result.get("ok") is not True:
            print("ERROR: Telegram API did not confirm message delivery.")
            return 1
    except urllib.error.HTTPError as exc:
        print(f"ERROR: Telegram returned HTTP {exc.code}. Check token, chat ID, and whether the bot was started.")
        return 1
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        print("ERROR: Telegram request failed; check networking and retry.")
        return 1
    print("SUCCESS: Telegram API accepted test message. Check your Telegram chat.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
