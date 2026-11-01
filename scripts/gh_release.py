#!/usr/bin/env python3
"""Temporary public URL for the video, via a GitHub Release asset.

Instagram's API can only fetch the video from a public URL. We create a
release, hand its asset URL to Instagram, then delete the release (and tag)
so no video stays stored on GitHub — exactly the lifecycle the channel
owner asked for.
"""
import os
import time

import requests

API = "https://api.github.com"


def _h():
    return {
        "Authorization": f"Bearer {os.environ['GH_TOKEN']}",
        "Accept": "application/vnd.github+json",
    }


def create_public_copy(video_path):
    repo = os.environ["GITHUB_REPOSITORY"]  # owner/name, auto-set in Actions
    tag = f"tmp-{int(time.time())}"
    r = requests.post(f"{API}/repos/{repo}/releases", headers=_h(), json={
        "tag_name": tag, "name": tag, "draft": False, "prerelease": True,
    }, timeout=60)
    r.raise_for_status()
    rel = r.json()
    with open(video_path, "rb") as f:
        up = requests.post(
            rel["upload_url"].split("{")[0],
            headers={**_h(), "Content-Type": "application/octet-stream"},
            params={"name": "video.mp4"}, data=f, timeout=900,
        )
    up.raise_for_status()
    url = up.json()["browser_download_url"]
    print("temp public URL:", url)
    return rel["id"], tag, url


def delete_public_copy(release_id, tag):
    repo = os.environ["GITHUB_REPOSITORY"]
    requests.delete(f"{API}/repos/{repo}/releases/{release_id}",
                    headers=_h(), timeout=60)
    requests.delete(f"{API}/repos/{repo}/git/refs/tags/{tag}",
                    headers=_h(), timeout=60)
    print("temp release deleted:", tag)
