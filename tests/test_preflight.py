"""Offline tests for preflight's liveness classification.

Regression guard for the 2026-11-02 evening run: read probes demanded
permissions the posting tokens never carried (pages_read_engagement,
YouTube readonly scope) and preflight killed a run whose credentials
were fine. Permission errors must read as ALIVE; only real token-death
signals (OAuth 190 / invalid_grant) may fail the run.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import requests  # noqa: E402

import preflight  # noqa: E402

ENV = {"FB_PAGE_ID": "111", "FB_PAGE_TOKEN": "tok",
       "IG_USER_ID": "222",
       "YT_CLIENT_ID": "cid", "YT_CLIENT_SECRET": "sec",
       "YT_REFRESH_TOKEN": "rtok"}


class Resp:
    def __init__(self, status, payload=None, text=""):
        self.status_code = status
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


PERM_ERR = {"error": {"message": "Any of the pages_read_engagement, "
                                 "pages_manage_metadata permission(s) must "
                                 "be granted", "code": 10}}
DEAD_ERR = {"error": {"message": "Error validating access token: Session "
                                 "has expired on Sunday", "code": 190}}


def run_with(get=None, post=None):
    old_env = dict(os.environ)
    os.environ.update(ENV)
    old_get, old_post = requests.get, requests.post
    if get is not None:
        requests.get = get
    if post is not None:
        requests.post = post
    try:
        return {n: (ok, d) for n, ok, d in preflight.check_all()}
    finally:
        requests.get, requests.post = old_get, old_post
        os.environ.clear()
        os.environ.update(old_env)


def test_meta_ok_when_reachable():
    res = run_with(get=lambda *a, **k: Resp(200, {"id": "111",
                                                  "name": "Page"}))
    # IG probe gets the FB-shaped 200 too; id mismatch must fail IG only
    assert res["facebook"][0] is True


def test_meta_permission_error_means_alive():
    res = run_with(get=lambda *a, **k: Resp(400, PERM_ERR, "perm"))
    assert res["facebook"][0] is True, res["facebook"]
    assert res["instagram"][0] is True, res["instagram"]
    assert "alive" in res["facebook"][1]


def test_meta_dead_token_fails():
    res = run_with(get=lambda *a, **k: Resp(400, DEAD_ERR, "dead"))
    assert res["facebook"][0] is False, res["facebook"]
    assert res["instagram"][0] is False, res["instagram"]


def test_meta_network_error_proceeds():
    def boom(*a, **k):
        raise requests.ConnectionError("no route")
    res = run_with(get=boom)
    assert res["facebook"][0] is True, res["facebook"]


def test_youtube_refresh_ok_without_channels_call():
    calls = []

    def fake_post(url, **k):
        calls.append(url)
        return Resp(200, {"access_token": "x"})

    def no_get(*a, **k):
        raise AssertionError("channels.list must not be called")

    res = run_with(get=no_get, post=fake_post)
    assert res["youtube"][0] is True, res["youtube"]
    assert calls == ["https://oauth2.googleapis.com/token"]


def test_youtube_dead_refresh_fails():
    res = run_with(post=lambda *a, **k: Resp(400, {}, "invalid_grant"))
    assert res["youtube"][0] is False, res["youtube"]


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print("ok:", fn.__name__)
    print(f"{len(fns)} preflight tests passed")
