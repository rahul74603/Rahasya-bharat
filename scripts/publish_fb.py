#!/usr/bin/env python3
"""Publish a video file directly to the Facebook Page (Graph API)."""
import os
import sys

import requests

GRAPH = "https://graph.facebook.com/v19.0"


def publish(video_path, description):
    page_id = os.environ["FB_PAGE_ID"]
    token = os.environ["FB_PAGE_TOKEN"]
    with open(video_path, "rb") as f:
        r = requests.post(
            f"{GRAPH}/{page_id}/videos",
            files={"source": f},
            data={"description": description},
            params={"access_token": token},
            timeout=600,
        )
    data = r.json()
    if r.status_code != 200 or "id" not in data:
        raise RuntimeError(f"Facebook upload failed: {data}")
    vid = data["id"]
    print(f"Facebook OK: https://www.facebook.com/{vid}")
    return vid


if __name__ == "__main__":
    publish(sys.argv[1], sys.argv[2])
