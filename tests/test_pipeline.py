#!/usr/bin/env python3
"""Offline safety tests for the Rahasya Bharat pipeline.

Runs in CI BEFORE any video is built (workflow "Test gate" step) and
locally with:  python -m unittest discover -s tests -v
No network, no secrets: publishers, video builder and the vault are
replaced with in-memory/file stubs before run.py is imported.
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile
import types
import unittest

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "scripts")
sys.path.insert(0, SCRIPTS)

CALLS = []
FAIL = set()


def _mkmod(name, **attrs):
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[name] = m
    return m


def _build(topic, workdir):
    os.makedirs(workdir, exist_ok=True)
    p = os.path.join(workdir, "video.mp4")
    with open(p, "wb") as f:
        f.write(b"FAKE-" + topic["id"].encode())
    CALLS.append(("build", topic["id"]))
    return {"video": p}


def _pub(platform, pid):
    def f(*a, **k):
        CALLS.append((platform,))
        if platform in FAIL:
            raise RuntimeError(f"{platform} boom")
        return pid
    return f


_mkmod("make_video", build=_build)
_mkmod("gh_release",
       create_public_copy=lambda p: (1, "tag", "http://x/v.mp4"),
       delete_public_copy=lambda rid, tag: None)
_mkmod("publish_fb", publish=_pub("facebook", "fb-1"))
_mkmod("publish_ig", publish=_pub("instagram", "ig-1"))
_mkmod("publish_yt", publish=_pub("youtube", "yt-1"))
_mkmod("preflight", check_all=lambda: [(p, True, "ok") for p in
                                        ("facebook", "instagram", "youtube")])

# File-backed stub vault (same API as scripts/vault.py).
_vault_dir = tempfile.mkdtemp(prefix="vault-stub-")
_vault_file = os.path.join(_vault_dir, "manifest.json")


def _v_load():
    if os.path.exists(_vault_file):
        m = json.load(open(_vault_file))
    else:
        m = {}
    m.setdefault("pending", {})
    m.setdefault("done", {})
    m.setdefault("quarantined", {})
    return m


def _v_save(m):
    json.dump(m, open(_vault_file, "w"))


def _v_put(topic_id, path):
    dest = os.path.join(_vault_dir, topic_id + ".mp4")
    shutil.copy(path, dest)
    return topic_id


def _v_get(asset_id, dest):
    shutil.copy(os.path.join(_vault_dir, asset_id + ".mp4"), dest)
    return dest


def _v_del(asset_id):
    p = os.path.join(_vault_dir, asset_id + ".mp4")
    if os.path.exists(p):
        os.remove(p)


_mkmod("vault", load_manifest=_v_load, save_manifest=_v_save,
       put_video=_v_put, get_video=_v_get, delete_video=_v_del)

import run  # noqa: E402  (imports resolve to the stubs above)


def topic(tid, slot="morning", script="SCRIPT"):
    return {"id": tid, "slot": slot, "script": script, "title": f"T-{tid}",
            "hook": f"H-{tid}", "desc_extra": "d", "image_query": "q"}


def topics_of(*ts):
    return {"channel": "Rahasya Bharat", "common_hashtags": ["#C"],
            "hashtag_pools": {"itihaas": ["#i1", "#i2", "#i3", "#i4"],
                              "rahasya": ["#r1", "#r2", "#r3", "#r4"]},
            "outro_line": "out", "handle": "@h", "topics": list(ts)}


def entry(tid, slot="morning", attempts=0):
    return {"slot": slot, "title": f"T-{tid}", "yt_title": f"T-{tid}",
            "caption": "c", "description": "d",
            "fingerprint": hashlib.sha256(b"SCRIPT").hexdigest()[:16],
            "attempts": attempts, "built_at": "x", "video_asset": tid,
            "platforms": {p: {"status": "pending", "id": None, "error": None}
                          for p in run.PLATFORMS}}


class Base(unittest.TestCase):
    def setUp(self):
        CALLS.clear()
        FAIL.clear()
        self.root = tempfile.mkdtemp(prefix="rb-root-")
        run.ROOT = self.root
        if os.path.exists(_vault_file):
            os.remove(_vault_file)
        for f in os.listdir(_vault_dir):
            if f.endswith(".mp4"):
                os.remove(os.path.join(_vault_dir, f))


class TestPickTopic(Base):
    def test_skips_posted_scriptless_and_wrong_slot(self):
        ts = topics_of(topic("a", script="S1"), topic("b", script=None),
                       topic("c", slot="evening", script="S3"),
                       topic("d", script="S4"))
        picked = run.pick_topic(ts, {"a"}, set(), "morning")
        self.assertEqual(picked["id"], "d")

    def test_duplicate_fingerprint_skipped(self):
        ts = topics_of(topic("copy", script="SAME"), topic("fresh", script="NEW"))
        fp = hashlib.sha256(b"SAME").hexdigest()[:16]
        picked = run.pick_topic(ts, set(), {fp}, "morning")
        self.assertEqual(picked["id"], "fresh")

    def test_none_left_returns_none(self):
        ts = topics_of(topic("a", script="S1"))
        self.assertIsNone(run.pick_topic(ts, {"a"}, set(), "morning"))


class TestTexts(Base):
    def test_morning_tags_and_title_parity(self):
        t = topic("x")
        when = run.dt.datetime(2026, 1, 4, tzinfo=run.dt.timezone.utc)  # yday 4 (even)
        caption, desc, yt_title = run.texts(topics_of(t), t, when)
        self.assertIn("#ItihaasKiKahani", caption)
        self.assertIn("#C", caption)
        pool_hits = sum(tag in caption for tag in ("#i1", "#i2", "#i3", "#i4"))
        self.assertEqual(pool_hits, 3)
        self.assertEqual(yt_title, "T-x")
        when2 = run.dt.datetime(2026, 1, 5, tzinfo=run.dt.timezone.utc)  # yday 5 (odd)
        _, _, yt_title2 = run.texts(topics_of(t), t, when2)
        self.assertEqual(yt_title2, "H-x | Rahasya Bharat")

    def test_evening_uses_rahasya_pool(self):
        t = topic("y", slot="evening")
        when = run.dt.datetime(2026, 1, 4, tzinfo=run.dt.timezone.utc)
        caption, _, _ = run.texts(topics_of(t), t, when)
        self.assertIn("#Rahasya", caption)
        self.assertTrue(any(tag in caption for tag in ("#r1", "#r2", "#r3", "#r4")))


class TestPublishEntry(Base):
    def test_partial_failure_marks_only_failed(self):
        FAIL.add("instagram")
        m = {"pending": {}, "done": {}, "quarantined": {}}
        e = entry("t1")
        ok = run.publish_entry(m, "t1", e, "/nonexistent.mp4")
        self.assertFalse(ok)
        self.assertEqual(e["platforms"]["facebook"]["status"], "done")
        self.assertEqual(e["platforms"]["instagram"]["status"], "pending")
        self.assertEqual(e["platforms"]["youtube"]["status"], "done")

    def test_retry_calls_only_missing_platform(self):
        FAIL.add("instagram")
        m = {"pending": {}, "done": {}, "quarantined": {}}
        e = entry("t1")
        run.publish_entry(m, "t1", e, "/nonexistent.mp4")
        CALLS.clear()
        FAIL.clear()
        ok = run.publish_entry(m, "t1", e, "/nonexistent.mp4")
        self.assertTrue(ok)
        self.assertEqual(CALLS, [("instagram",)])


class TestVaultFlow(Base):
    def _seed_pending(self, attempts=0):
        src_dir = os.path.join(self.root, "seed")
        os.makedirs(src_dir, exist_ok=True)
        src = os.path.join(src_dir, "t1.mp4")
        with open(src, "wb") as f:
            f.write(b"V")
        _v_put("t1", src)
        return {"pending": {"t1": entry("t1", attempts=attempts)},
                "done": {}, "quarantined": {}}

    def test_finish_records_state_and_done(self):
        m = self._seed_pending()
        state = {"posted": {}}
        stuck = run.process_vault(m, state, "morning")
        self.assertEqual(stuck, 0)
        self.assertIn("t1", state["posted"])
        self.assertIn("t1", m["done"])
        self.assertEqual(m["pending"], {})

    def test_stuck_before_cap(self):
        FAIL.update(run.PLATFORMS)
        m = self._seed_pending(attempts=0)
        stuck = run.process_vault(m, {"posted": {}}, "morning")
        self.assertEqual(stuck, 1)
        self.assertIn("t1", m["pending"])
        self.assertEqual(m["pending"]["t1"]["attempts"], 1)

    def test_quarantine_after_max_attempts(self):
        FAIL.update(run.PLATFORMS)
        m = self._seed_pending(attempts=run.MAX_ATTEMPTS - 1)
        stuck = run.process_vault(m, {"posted": {}}, "morning")
        self.assertEqual(stuck, 0)  # quarantined entries no longer block
        self.assertEqual(m["pending"], {})
        self.assertIn("t1", m["quarantined"])
        self.assertTrue(os.path.exists(os.path.join(_vault_dir, "t1.mp4")))


if __name__ == "__main__":
    unittest.main()
