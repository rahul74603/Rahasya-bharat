#!/usr/bin/env python3
"""Post the pinned-question comment on an already-published video.

These are EXTRAS: they run only after the video itself is safely posted,
and a failure here never marks the video as failed (run.py records the
outcome separately). Commenting needs permissions beyond posting
(Meta: engagement/comments scopes; YouTube: force-ssl scope) — until
those are granted, attempts fail loudly in the log/summary instead of
silently, and start working automatically once the tokens gain them.
"""
import os

import requests

GRAPH = "https://graph.facebook.com/v19.0"
TIMEOUT = 30


def comment_facebook(object_id, text):
    r = requests.post(f"{GRAPH}/{object_id}/comments",
                      params={"access_token": os.environ["FB_PAGE_TOKEN"]},
                      data={"message": text}, timeout=TIMEOUT)
    if r.status_code != 200:
        raise RuntimeError(f"FB comment HTTP {r.status_code}: {r.text[:200]}")
    return r.json()["id"]


def comment_instagram(media_id, text):
    r = requests.post(f"{GRAPH}/{media_id}/comments",
                      params={"access_token": os.environ["FB_PAGE_TOKEN"]},
                      data={"message": text}, timeout=TIMEOUT)
    if r.status_code != 200:
        raise RuntimeError(f"IG comment HTTP {r.status_code}: {r.text[:200]}")
    return r.json()["id"]


def _yt_access_token():
    r = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": os.environ["YT_CLIENT_ID"],
        "client_secret": os.environ["YT_CLIENT_SECRET"],
        "refresh_token": os.environ["YT_REFRESH_TOKEN"],
        "grant_type": "refresh_token",
    }, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()["access_token"]


def comment_youtube(video_id, text):
    access = _yt_access_token()
    h = {"Authorization": f"Bearer {access}"}
    r = requests.get("https://www.googleapis.com/youtube/v3/channels",
                     params={"part": "id", "mine": "true"}, headers=h,
                     timeout=TIMEOUT)
    r.raise_for_status()
    channel_id = r.json()["items"][0]["id"]
    r = requests.post(
        "https://www.googleapis.com/youtube/v3/commentThreads",
        params={"part": "snippet"}, headers=h,
        json={"snippet": {
            "videoId": video_id, "channelId": channel_id,
            "topLevelComment": {"snippet": {"textOriginal": text}}}},
        timeout=TIMEOUT)
    if r.status_code != 200:
        raise RuntimeError(f"YT comment HTTP {r.status_code}: {r.text[:200]}")
    return r.json()["id"]
