#!/usr/bin/env python3
"""Upload a video to YouTube via Data API v3 (OAuth refresh-token flow).

NOTE (Google policy): videos uploaded through an UNVERIFIED OAuth app are
locked to private by YouTube until the Cloud project passes verification
for the youtube.upload scope. If uploads come out private-locked, see
SECRETS.md — the fix is the one-time app verification, not new code.
"""
import os
import sys

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def publish(video_path, title, description, tags):
    creds = Credentials(
        token=None,
        refresh_token=os.environ["YT_REFRESH_TOKEN"],
        client_id=os.environ["YT_CLIENT_ID"],
        client_secret=os.environ["YT_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES,
    )
    yt = build("youtube", "v3", credentials=creds)
    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": "27",  # Education
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
        },
    }
    media = MediaFileUpload(video_path, mimetype="video/mp4", resumable=True)
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    resp = None
    while resp is None:
        status, resp = req.next_chunk()
        if status:
            print(f"upload {int(status.progress() * 100)}%")
    vid = resp["id"]
    print(f"YouTube OK: https://www.youtube.com/watch?v={vid} (shorts: https://www.youtube.com/shorts/{vid})")
    return vid


if __name__ == "__main__":
    publish(sys.argv[1], sys.argv[2], sys.argv[3], ["Rahasya Bharat", "Hindi Facts"])
