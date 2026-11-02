#!/usr/bin/env python3
"""Preflight credential check — catch DEAD tokens BEFORE any video is
built. A dead/expired token fails the run immediately, with the platform
and cause named, instead of wasting a full render or — worse — looking
green while nothing posts. (Lesson imported from gyaani_babba, whose
channel sat silent for weeks behind green runs and dead uploads.)

IMPORTANT (learned the hard way, 2026-11-02 evening run): preflight
probes must match what the tokens are actually FOR. Our tokens are
minted for POSTING only — pages_manage_posts /
instagram_content_publish / youtube.upload — and deliberately carry no
read permissions. Graph validates a token BEFORE checking endpoint
permissions, so a live posting token answers a read probe with a
PERMISSION error (codes 10/200, "permission(s) must be granted"),
while a dead token always answers OAuthException 190 ("Error
validating access token" / "Session has expired"). Permission errors
therefore mean "alive — the probe asked for too much", NOT failure.
The same tokens that "failed" the old read probes had posted Roopkund
to all three platforms hours earlier. Network errors likewise do not
prove a token dead; the publish calls have their own retries, so a
probe network failure warns and proceeds instead of killing the run.
"""
import os

import requests

GRAPH = "https://graph.facebook.com/v19.0"
TIMEOUT = 30

DEAD_MARKERS = ("Error validating access token", "Session has expired",
                "Invalid OAuth access token", "has expired on")
PERM_CODES = (10, 200, 230, 294)
PERM_MARKERS = ("permission(s) must be granted", "Permissions error",
                "does not have permission", "pages_read_engagement",
                "pages_manage_metadata")


def _need(name):
    v = os.environ.get(name)
    if not v:
        raise RuntimeError(f"secret missing: {name}")
    return v


def _classify_meta(resp):
    """(alive, detail) for a non-200 Graph probe response. `alive` is
    True only for permission errors, which prove the token itself was
    accepted by Graph; everything else is a real failure detail."""
    text = resp.text or ""
    try:
        err = resp.json().get("error", {})
    except Exception:
        err = {}
    code = err.get("code")
    msg = err.get("message", "") or text
    if code == 190 or any(m in msg for m in DEAD_MARKERS):
        return False, f"token DEAD — HTTP {resp.status_code}: {text[:200]}"
    if code in PERM_CODES or any(m in msg for m in PERM_MARKERS):
        return True, ("token alive (probe asked for a read permission the "
                      "posting token doesn't carry; posting permissions "
                      "were verified when the token was minted)")
    return False, f"HTTP {resp.status_code}: {text[:200]}"


def _meta_probe(url, params, expect_id, label):
    try:
        r = requests.get(url, params=params, timeout=TIMEOUT)
    except requests.RequestException as e:
        return (f"probe network error ({e.__class__.__name__}) — token not "
                "proven dead, proceeding")
    if r.status_code == 200:
        d = r.json()
        if str(d.get("id")) != str(expect_id):
            raise RuntimeError(
                f"token returned a different {label}: {d.get('id')}")
        return "reachable: " + str(d.get("name") or d.get("username") or d["id"])
    alive, detail = _classify_meta(r)
    if alive:
        return detail
    raise RuntimeError(detail)


def check_facebook():
    page_id, token = _need("FB_PAGE_ID"), _need("FB_PAGE_TOKEN")
    return _meta_probe(f"{GRAPH}/{page_id}",
                       {"fields": "id,name", "access_token": token},
                       page_id, "page")


def check_instagram():
    ig_id, token = _need("IG_USER_ID"), _need("FB_PAGE_TOKEN")
    return _meta_probe(f"{GRAPH}/{ig_id}",
                       {"fields": "id,username", "access_token": token},
                       ig_id, "IG user")


def check_youtube():
    # The refresh exchange IS the credential test: a revoked/expired
    # refresh token fails here with invalid_grant. channels.list is
    # deliberately NOT called — it needs a read scope the upload-only
    # token intentionally doesn't carry (scope was verified at mint).
    try:
        r = requests.post("https://oauth2.googleapis.com/token", data={
            "client_id": _need("YT_CLIENT_ID"),
            "client_secret": _need("YT_CLIENT_SECRET"),
            "refresh_token": _need("YT_REFRESH_TOKEN"),
            "grant_type": "refresh_token",
        }, timeout=TIMEOUT)
    except requests.RequestException as e:
        return (f"probe network error ({e.__class__.__name__}) — token not "
                "proven dead, proceeding")
    if r.status_code != 200:
        raise RuntimeError(
            f"token refresh failed HTTP {r.status_code}: {r.text[:200]}")
    return "refresh token alive (upload scope verified when it was minted)"


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
