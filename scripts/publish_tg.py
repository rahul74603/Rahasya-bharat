#!/usr/bin/env python3
"""Publish to the Telegram channel via the Bot API — the channel's own
audience, independent of YouTube/Instagram/Facebook algorithms.

Sends the actual video file (Bot API allows 50 MB; ours are ~25 MB)
with a caption carrying the other platforms' links. This is an EXTRA
(run.py try_extras): it is attempted once per run after the main three
platforms succeed, and a failure never touches the video's posted
status. Inactive until TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID are set.
"""
import os
import sys

import requests

API = "https://api.telegram.org"


def publish(video_path, caption):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat = os.environ["TELEGRAM_CHAT_ID"]
    caption = (caption or "")[:1000]
    with open(video_path, "rb") as f:
        r = requests.post(f"{API}/bot{token}/sendVideo",
                          data={"chat_id": chat, "caption": caption,
                                "supports_streaming": "true"},
                          files={"video": f}, timeout=900)
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram sendVideo failed: {data}")
    mid = data["result"]["message_id"]
    print(f"Telegram OK: message {mid}")
    return mid


if __name__ == "__main__":
    publish(sys.argv[1], sys.argv[2])
