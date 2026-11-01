#!/usr/bin/env python3
"""Run this ONCE on your own PC to get the YouTube REFRESH TOKEN.

Steps:
  1. In Google Cloud Console, create an OAuth client (type: Desktop app)
     for a project with the YouTube Data API v3 enabled.
  2. Download it as client_secret.json and keep it next to this file.
  3. pip install google-auth-oauthlib
  4. python yt_auth_local.py
     -> a browser opens; sign in with the Google account that OWNS the
        Rahasya Bharat channel and allow access.
  5. The script prints the REFRESH TOKEN. Copy it into the GitHub repo's
     secret named YT_REFRESH_TOKEN. Never share it in chat or commit it.
"""
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def main():
    flow = InstalledAppFlow.from_client_secrets_file("client_secret.json", SCOPES)
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    print("\n================ COPY THIS ================")
    print("YT_REFRESH_TOKEN =", creds.refresh_token)
    print("===========================================\n")


if __name__ == "__main__":
    main()
