#!/usr/bin/env python3
"""Preflight credential check — verify all three platforms BEFORE any
video is built. A dead/expired token fails the run immediately, with the
platform and cause named, instead of wasting a full render or — worse —
looking green while nothing posts. (Lesson imported from gyaani_babba,
whose channel sat silent for weeks behind green runs and dead uploads.)
"""
import os

import requests

GRAPH = "https://graph.facebook.com/v19.0"
TIMEOUT = 30


def _need(name):
    v = os.environ.get(name)
    if not v:
        raise RuntimeError(f"secret missing: {name}")
    return v


def check_facebook():
    page_id, token = _need("FB_PAGE_ID"), _need("FB_PAGE_TOKEN")
    r = requests.get(f"{GRAPH}/{page_id}",
                     params={"fields": "id,name", "access_token": token},
                     timeout=TIMEOUT)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
    d = r.json()
    if str(d.get("id")) != str(page_id):
        raise RuntimeError(f"token returned a different page: {d.get('id')}")
    return f"page '{d.get('name')}' reachable"


def check_instagram():
    ig_id, token = _need("IG_USER_ID"), _need("FB_PAGE_TOKEN")
    r = requests.get(f"{GRAPH}/{ig_id}",
                     params={"fields": "id,username", "access_token": token},
                     timeout=TIMEOUT)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
    d = r.json()
    if str(d.get("id")) != str(ig_id):
        raise RuntimeError(f"token returned a different IG user: {d.get('id')}")
    return f"@{d.get('username')} reachable"


def check_youtube():
    r = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": _need("YT_CLIENT_ID"),
        "client_secret": _need("YT_CLIENT_SECRET"),
        "refresh_token": _need("YT_REFRESH_TOKEN"),
        "grant_type": "refresh_token",
    }, timeout=TIMEOUT)
    if r.status_code != 200:
        raise RuntimeError(f"token refresh failed HTTP {r.status_code}: {r.text[:200]}")
    access = r.json()["access_token"]
    r = requests.get("https://www.googleapis.com/youtube/v3/channels",
                     params={"part": "id,snippet", "mine": "true"},
                     headers={"Authorization": f"Bearer {access}"},
                     timeout=TIMEOUT)
    if r.status_code != 200:
        raise RuntimeError(f"channels.list failed HTTP {r.status_code}: {r.text[:200]}")
    items = r.json().get("items", [])
    if not items:
        raise RuntimeError("no channel found for this token")
    return f"channel '{items[0]['snippet']['title']}' reachable"


CHECKS = (("facebook", check_facebook),
          ("instagram", check_instagram),
          ("youtube", check_youtube))


def check_all():
    """Returns a list of (platform, ok, detail) — never raises."""
    results = []
    for name, fn in CHECKS:
        try:
            results.append((name, True, fn()))
        except Exception as e:
            results.append((name, False, str(e)))
    return results
