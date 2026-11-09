#!/usr/bin/env python3
"""Publish a video to Threads via the Threads API (graph.threads.net).

Needs a PUBLIC video URL (Meta's servers fetch it) — same temp public
copy mechanism as Instagram (see gh_release.py). Uses its OWN token:
the Threads API does not accept the Facebook Page token. Secrets:
THREADS_USER_ID + THREADS_ACCESS_TOKEN (long-lived, ~60 days, minted
from the app dashboard's User Token Generator — see SECRETS.md).

Threads text limit is 500 characters, so the caption is trimmed
line-wise: the hook (first line) always survives; later lines are
added only while they still fit.
"""
import os
import sys
import time

import requests

GRAPH = "https://graph.threads.net/v1.0"
MAX_TEXT = 500


def make_text(caption):
    """Caption ko Threads ki 500-char seema me rakho — pehli (hook)
    line hamesha rahe, baaki lines tab tak jab tak jagah bache."""
    out = []
    total = 0
    for ln in (caption or "").split("\n"):
        add = len(ln) + (1 if out else 0)
        if out and total + add > MAX_TEXT:
            break
        out.append(ln)
        total += add
    text = "\n".join(out).strip()
    if len(text) > MAX_TEXT:  # hook line khud bahut lambi ho to
        text = text[:MAX_TEXT - 1].rstrip() + "…"
    return text


def publish(video_url, caption):
    user_id = os.environ["THREADS_USER_ID"]
    token = os.environ["THREADS_ACCESS_TOKEN"]

    r = requests.post(f"{GRAPH}/{user_id}/threads", data={
        "media_type": "VIDEO", "video_url": video_url,
        "text": make_text(caption), "access_token": token,
    }, timeout=120)
    data = r.json()
    if "id" not in data:
        raise RuntimeError(f"Threads container failed: {data}")
    container = data["id"]

    for _ in range(30):  # up to ~5 minutes
        s = requests.get(f"{GRAPH}/{container}", params={
            "fields": "status,error_message", "access_token": token,
        }, timeout=60).json()
        code = s.get("status")
        print("Threads container:", s)
        if code == "FINISHED":
            break
        if code in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Threads processing error: {s}")
        time.sleep(10)
    else:
        raise RuntimeError("Threads container timeout")

    r = requests.post(f"{GRAPH}/{user_id}/threads_publish", data={
        "creation_id": container, "access_token": token,
    }, timeout=120)
    data = r.json()
    if "id" not in data:
        raise RuntimeError(f"Threads publish failed: {data}")
    media_id = data["id"]
    p = requests.get(f"{GRAPH}/{media_id}", params={
        "fields": "permalink", "access_token": token,
    }, timeout=60).json()
    print("Threads OK:", p.get("permalink", media_id))
    return media_id


if __name__ == "__main__":
    publish(sys.argv[1], sys.argv[2])
