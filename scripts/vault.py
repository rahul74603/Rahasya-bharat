#!/usr/bin/env python3
"""Pending-video vault — a built video is NEVER lost if publishing fails.

Storage: one permanent GitHub Release (tag "vault") in this repo.
Assets: one <topic_id>.mp4 per pending video + one vault.json manifest.

Manifest shape:
{
  "pending": {
     "<topic_id>": {
        "slot": "morning|evening", "title": ..., "caption": ...,
        "description": ..., "tags": [...], "fingerprint": ...,
        "built_at": iso, "video_asset": <asset id>,
        "platforms": {
           "facebook":  {"status": "pending|done", "id": ..., "error": ...},
           "instagram": {...}, "youtube": {...}
        }
     }
  },
  "done": { "<topic_id>": {"fingerprint": ..., "at": iso} },
  "quarantined": { "<topic_id>": <entry + quarantined_at + reason> }
}

Each pending entry also carries "attempts" (failed runs so far). After
MAX_ATTEMPTS failed runs an entry is moved to "quarantined": its video
stays stored, but it stops blocking new builds (a permanently broken
upload once froze a sister channel for ~2 months — never again).

The manifest is updated through the API after EVERY platform attempt, so
a crashed or failed run never loses track of what is already posted —
that is what makes retries duplicate-safe.
"""
import json
import os
import time

import requests

API = "https://api.github.com"
TAG = "vault"
MANIFEST = "vault.json"

# GitHub occasionally answers a perfectly good request with a transient
# 502/503 (2026-11-04: a manifest save died on a 502 right after the
# Facebook post succeeded, killing the run before Instagram/YouTube).
# 5xx and network errors are retried with backoff; 4xx is a real error
# and raises immediately.
RETRY_DELAYS = (3, 8, 20)


def _h():
    return {
        "Authorization": f"Bearer {os.environ['GH_TOKEN']}",
        "Accept": "application/vnd.github+json",
    }


def _repo():
    return os.environ["GITHUB_REPOSITORY"]  # owner/name, auto-set in Actions


def _release():
    r = requests.get(f"{API}/repos/{_repo()}/releases/tags/{TAG}",
                     headers=_h(), timeout=60)
    if r.status_code == 404:
        r = requests.post(f"{API}/repos/{_repo()}/releases", headers=_h(), json={
            "tag_name": TAG, "name": "Pending Video Vault",
            "body": "Videos built but not yet fully published live here. "
                    "Do not delete by hand.",
            "draft": False, "prerelease": True,
        }, timeout=60)
    r.raise_for_status()
    return r.json()


def _assets(release_id):
    r = requests.get(f"{API}/repos/{_repo()}/releases/{release_id}/assets",
                     headers=_h(), timeout=60)
    r.raise_for_status()
    return r.json()


def _upload(release, name, data, ctype):
    last = None
    for attempt in range(len(RETRY_DELAYS) + 1):
        try:
            up = requests.post(
                release["upload_url"].split("{")[0],
                headers={**_h(), "Content-Type": ctype},
                params={"name": name}, data=data, timeout=900,
            )
            if up.status_code >= 500:
                raise requests.HTTPError(
                    f"{up.status_code} Server Error for asset upload {name}",
                    response=up)
            up.raise_for_status()
            return up.json()
        except (requests.HTTPError, requests.RequestException) as e:
            if isinstance(e, requests.HTTPError) and \
                    e.response is not None and e.response.status_code < 500:
                raise
            last = e
            if attempt < len(RETRY_DELAYS):
                print(f"vault upload {name}: transient error ({e}) — "
                      f"retry {attempt + 1} in {RETRY_DELAYS[attempt]}s")
                time.sleep(RETRY_DELAYS[attempt])
    raise last


def _delete_asset(asset_id):
    requests.delete(f"{API}/repos/{_repo()}/releases/assets/{asset_id}",
                    headers=_h(), timeout=60)


def load_manifest():
    rel = _release()
    for a in _assets(rel["id"]):
        if a["name"] == MANIFEST:
            r = requests.get(
                f"{API}/repos/{_repo()}/releases/assets/{a['id']}",
                headers={**_h(), "Accept": "application/octet-stream"},
                timeout=60)
            r.raise_for_status()
            m = json.loads(r.content.decode("utf-8"))
            m.setdefault("pending", {})
            m.setdefault("done", {})
            m.setdefault("quarantined", {})
            return m
    return {"pending": {}, "done": {}, "quarantined": {}}


def save_manifest(manifest):
    data = json.dumps(manifest, ensure_ascii=False,
                      indent=1).encode("utf-8")
    last = None
    for attempt in range(len(RETRY_DELAYS) + 1):
        try:
            rel = _release()
            for a in _assets(rel["id"]):
                if a["name"] == MANIFEST:
                    _delete_asset(a["id"])
            _upload(rel, MANIFEST, data, "application/json")
            return
        except requests.RequestException as e:
            last = e
            status = getattr(e.response, "status_code", None)
            if status is not None and status < 500:
                raise
            if attempt < len(RETRY_DELAYS):
                print(f"vault save_manifest: transient error ({e}) — "
                      f"retry {attempt + 1} in {RETRY_DELAYS[attempt]}s")
                time.sleep(RETRY_DELAYS[attempt])
    raise last


def put_video(topic_id, video_path):
    """Store (or replace) the pending video; returns the asset id."""
    rel = _release()
    name = f"{topic_id}.mp4"
    for a in _assets(rel["id"]):
        if a["name"] == name:
            _delete_asset(a["id"])
    with open(video_path, "rb") as f:
        data = f.read()  # bytes, not a stream — an upload retry must be
        # able to resend the whole file, a consumed stream cannot
    asset = _upload(rel, name, data, "video/mp4")
    return asset["id"]


def get_video(asset_id, dest_path):
    r = requests.get(
        f"{API}/repos/{_repo()}/releases/assets/{asset_id}",
        headers={**_h(), "Accept": "application/octet-stream"},
        timeout=900)
    r.raise_for_status()
    with open(dest_path, "wb") as f:
        f.write(r.content)
    return dest_path


def delete_video(asset_id):
    _delete_asset(asset_id)
