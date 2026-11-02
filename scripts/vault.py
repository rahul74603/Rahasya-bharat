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
  "done": { "<topic_id>": {"fingerprint": ..., "at": iso} }
}

The manifest is updated through the API after EVERY platform attempt, so
a crashed or failed run never loses track of what is already posted —
that is what makes retries duplicate-safe.
"""
import json
import os

import requests

API = "https://api.github.com"
TAG = "vault"
MANIFEST = "vault.json"


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
    up = requests.post(
        release["upload_url"].split("{")[0],
        headers={**_h(), "Content-Type": ctype},
        params={"name": name}, data=data, timeout=900,
    )
    up.raise_for_status()
    return up.json()


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
            return m
    return {"pending": {}, "done": {}}


def save_manifest(manifest):
    rel = _release()
    for a in _assets(rel["id"]):
        if a["name"] == MANIFEST:
            _delete_asset(a["id"])
    _upload(rel, MANIFEST,
            json.dumps(manifest, ensure_ascii=False, indent=1).encode("utf-8"),
            "application/json")


def put_video(topic_id, video_path):
    """Store (or replace) the pending video; returns the asset id."""
    rel = _release()
    name = f"{topic_id}.mp4"
    for a in _assets(rel["id"]):
        if a["name"] == name:
            _delete_asset(a["id"])
    with open(video_path, "rb") as f:
        asset = _upload(rel, name, f, "video/mp4")
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
