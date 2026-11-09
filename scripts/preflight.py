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
    accepted by Graph; everything else is a real failure detail.

    ORDER MATTERS (regression of 2026-11-03 05:00): this permission
    error can arrive WITH code 190 attached, so the permission check
    must run before the dead-token check. A genuine dead-token 190
    response always carries the validation/expiry text and never a
    permissions message, so checking permissions first is safe."""
    text = resp.text or ""
    try:
        err = resp.json().get("error", {})
    except Exception:
        err = {}
    code = err.get("code")
    msg = err.get("message", "") or text
    if any(m in msg for m in PERM_MARKERS) or (
            code in PERM_CODES and "validating" not in msg):
        return True, ("token alive (probe asked for a read permission the "
                      "posting token doesn't carry; posting permissions "
                      "were verified when the token was minted)")
    if code == 190 or any(m in msg for m in DEAD_MARKERS):
        return False, f"token DEAD — HTTP {resp.status_code}: {text[:200]}"
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


def check_threads():
    # Threads optional hai: secrets na hon to check hi nahi — OK maan
    # kar aage badho, taaki feature band haalat me pipeline na ruke.
    # Token Threads ka apna hota hai (FB Page token se alag) aur
    # threads_basic ke saath /me padh sakta hai, isliye yahan asal
    # read probe chal sakta hai.
    user_id = os.environ.get("THREADS_USER_ID")
    token = os.environ.get("THREADS_ACCESS_TOKEN")
    if not user_id or not token:
        return "not configured (secrets missing) — Threads skipped"
    try:
        r = requests.get("https://graph.threads.net/v1.0/me",
                         params={"fields": "id,username",
                                 "access_token": token},
                         timeout=TIMEOUT)
    except requests.RequestException as e:
        return (f"probe network error ({e.__class__.__name__}) — token not "
                "proven dead, proceeding")
    if r.status_code == 200:
        d = r.json()
        if str(d.get("id")) != str(user_id):
            raise RuntimeError(
                f"token returned a different Threads user: {d.get('id')}")
        return "reachable: " + str(d.get("username") or d["id"])
    alive, detail = _classify_meta(r)
    if alive:
        return detail
    raise RuntimeError(detail)


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
          ("youtube", check_youtube),
          ("threads", check_threads))


def check_all():
    """Returns a list of (platform, ok, detail) — never raises."""
    results = []
    for name, fn in CHECKS:
        try:
            results.append((name, True, fn()))
        except Exception as e:
            results.append((name, False, str(e)))
    return results
