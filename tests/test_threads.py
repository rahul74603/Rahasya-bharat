#!/usr/bin/env python3
"""Offline tests for the Threads add-on (2026-11-09).

Threads is an OPTIONAL fourth platform: without its secrets the
pipeline must behave exactly like the original three-platform one;
with them, Threads joins publishing, vault retry and preflight.
No network, no real secrets — heavy pipeline modules are stubbed
before run.py is imported (same pattern as test_pipeline.py).
"""
import os
import sys
import types
import unittest
from unittest import mock

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "scripts")
sys.path.insert(0, SCRIPTS)


def _mkmod(name, **attrs):
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[name] = m
    return m


_mkmod("make_video", build=lambda *a, **k: {"video": "x.mp4"})
_mkmod("gh_release", create_public_copy=lambda p: (1, "tag", "http://x/v.mp4"),
       delete_public_copy=lambda rid, tag: None)
_mkmod("publish_fb", publish=lambda *a, **k: "fb-1")
_mkmod("publish_ig", publish=lambda *a, **k: "ig-1")
_mkmod("publish_yt", publish=lambda *a, **k: "yt-1")
_mkmod("gen_meta", generate=lambda *a, **k: None)
_mkmod("post_comment", comment_facebook=lambda *a: "c",
       comment_instagram=lambda *a: "c", comment_youtube=lambda *a: "c")
_mkmod("vault")

import publish_threads  # noqa: E402  (real module — make_text ke liye)
import run  # noqa: E402

# test_pipeline.py sys.modules me preflight ka stub daal deta hai, isliye
# asal preflight ko file path se alag naam par load karo — stub se takraav
# nahi hoga aur check_threads ki asal jaanch hogi.
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "preflight_real", os.path.join(SCRIPTS, "preflight.py"))
preflight = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(preflight)

OFF = {"THREADS_USER_ID": "", "THREADS_ACCESS_TOKEN": ""}
ON = {"THREADS_USER_ID": "17841441106180278", "THREADS_ACCESS_TOKEN": "tok"}


def _entry():
    return {"platforms": {p: {"status": "pending", "id": None, "error": None}
                          for p in run.PLATFORMS}}


class MakeTextTests(unittest.TestCase):
    def test_short_caption_unchanged(self):
        cap = "Hook line\n\nDesc line\n#tag1 #tag2"
        self.assertEqual(publish_threads.make_text(cap), cap)

    def test_long_caption_trimmed_keeps_hook(self):
        cap = "HOOK\n" + "\n".join(f"line {i} " + "x" * 40 for i in range(40))
        text = publish_threads.make_text(cap)
        self.assertLessEqual(len(text), publish_threads.MAX_TEXT)
        self.assertTrue(text.startswith("HOOK"))

    def test_single_huge_line_capped(self):
        text = publish_threads.make_text("x" * 900)
        self.assertEqual(len(text), publish_threads.MAX_TEXT)
        self.assertTrue(text.endswith("…"))


class GatingTests(unittest.TestCase):
    def test_disabled_without_secrets(self):
        with mock.patch.dict(os.environ, OFF):
            self.assertFalse(run.threads_enabled())
            e = _entry()
            self.assertEqual(run.entry_platforms(e),
                             ["facebook", "instagram", "youtube"])
            self.assertNotIn("threads", e["platforms"])

    def test_enabled_with_secrets_adds_platform(self):
        with mock.patch.dict(os.environ, ON):
            self.assertTrue(run.threads_enabled())
            e = _entry()
            plats = run.entry_platforms(e)
            self.assertEqual(plats[-1], "threads")
            self.assertEqual(e["platforms"]["threads"]["status"], "pending")

    def test_existing_threads_state_preserved(self):
        with mock.patch.dict(os.environ, ON):
            e = _entry()
            e["platforms"]["threads"] = {"status": "done", "id": "t-1",
                                          "error": None}
            run.entry_platforms(e)
            self.assertEqual(e["platforms"]["threads"]["id"], "t-1")


class PreflightTests(unittest.TestCase):
    def test_threads_check_skips_without_secrets(self):
        with mock.patch.dict(os.environ, OFF):
            detail = preflight.check_threads()
        self.assertIn("skipped", detail)


if __name__ == "__main__":
    unittest.main()
