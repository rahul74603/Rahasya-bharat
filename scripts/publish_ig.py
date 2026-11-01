#!/usr/bin/env python3
"""Publish a Reel to Instagram via the Content Publishing API.

Needs a PUBLIC video URL (Meta's servers fetch it) — see gh_release.py.
Uses the same Meta Page token as Facebook, with instagram_content_publish.
"""
import os
import sys
import time

import requests

GRAPH = "https://graph.facebook.com/v19.0"


def publish(video_url, caption):
    ig_id = os.environ["IG_USER_ID"]
    token = os.environ["FB_PAGE_TOKEN"]

    r = requests.post(f"{GRAPH}/{ig_id}/media", data={
        "media_type": "REELS", "video_url": video_url,
        "caption": caption, "share_to_feed": "true",
        "access_token": token,
    }, timeout=120)
    data = r.json()
    if "id" not in data:
        raise RuntimeError(f"IG container failed: {data}")
    container = data["id"]

    for _ in range(60):  # up to ~10 minutes
        s = requests.get(f"{GRAPH}/{container}", params={
            "fields": "status_code,status", "access_token": token,
        }, timeout=60).json()
        code = s.get("status_code")
        print("IG container:", s)
        if code == "FINISHED":
            break
        if code == "ERROR":
            raise RuntimeError(f"IG processing error: {s}")
        time.sleep(10)
    else:
        raise RuntimeError("IG container timeout")

    r = requests.post(f"{GRAPH}/{ig_id}/media_publish", data={
        "creation_id": container, "access_token": token,
    }, timeout=120)
    data = r.json()
    if "id" not in data:
        raise RuntimeError(f"IG publish failed: {data}")
    media_id = data["id"]
    p = requests.get(f"{GRAPH}/{media_id}", params={
        "fields": "permalink", "access_token": token,
    }, timeout=60).json()
    print("Instagram OK:", p.get("permalink", media_id))
    return media_id


if __name__ == "__main__":
    publish(sys.argv[1], sys.argv[2])
