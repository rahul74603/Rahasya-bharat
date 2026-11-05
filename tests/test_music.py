#!/usr/bin/env python3
"""Offline tests for the background-music fix (2026-11-05):
bundled tracks pehle, amix normalize=0, kharab file = music nahi.
ffmpeg se chhoti asal audio file banti hai; network bilkul nahi."""
import base64
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "scripts")
sys.path.insert(0, SCRIPTS)

import make_video  # noqa: E402


def _make_audio(path, seconds=20):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                    "-i", f"sine=frequency=440:duration={seconds}",
                    "-ar", "22050", "-ac", "1", "-c:a", "pcm_u8", path],
                   check=True)


class TestMusicOk(unittest.TestCase):
    def test_real_audio_passes(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "ok.wav")
            _make_audio(p)
            self.assertTrue(make_video._music_ok(p))

    def test_garbage_fails(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "bad.oga")
            with open(p, "wb") as f:
                f.write(b"not audio at all" * 5000)
            self.assertFalse(make_video._music_ok(p))

    def test_tiny_file_fails(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "tiny.wav")
            _make_audio(p, seconds=2)
            self.assertFalse(make_video._music_ok(p))

    def test_missing_file_fails(self):
        self.assertFalse(make_video._music_ok("/nonexistent/x.oga"))


class TestFetchMusic(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        os.makedirs(os.path.join(root, "assets", "music"))
        self.workdir = os.path.join(root, "work")
        os.makedirs(self.workdir)
        # ek asal track bundle banao
        raw = os.path.join(root, "raw.wav")
        _make_audio(raw)
        with open(raw, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        with open(os.path.join(root, "assets", "music", "good.oga.b64"),
                  "w") as f:
            f.write(b64)
        self.tracks = [
            {"name": "Missing Wala", "credit": "C1", "slots": ["evening"],
             "file": "music/missing.oga.b64",
             "url": "https://example.invalid/missing.oga"},
            {"name": "Good Wala", "credit": "C2", "slots": ["evening"],
             "file": "music/good.oga.b64",
             "url": "https://example.invalid/good.oga"},
        ]
        manifest = os.path.join(root, "assets", "music.json")
        with open(manifest, "w") as f:
            json.dump({"tracks": self.tracks}, f)
        self._root = mock.patch.object(make_video, "ROOT", root)
        self._man = mock.patch.object(make_video, "MUSIC_MANIFEST", manifest)
        self._root.start()
        self._man.start()

    def tearDown(self):
        self._root.stop()
        self._man.stop()
        self.tmp.cleanup()

    def test_bundled_track_used_without_download(self):
        def no_download(url, dest):
            raise AssertionError("download hona hi nahi chahiye")
        with mock.patch.object(make_video, "_download", no_download):
            got = make_video.fetch_music({"slot": "evening"}, self.workdir)
        self.assertIsNotNone(got)
        self.assertEqual(got["credit"], "C2")  # missing wala skip hua
        self.assertTrue(make_video._music_ok(got["path"]))

    def test_all_fail_returns_none(self):
        tracks = [{"name": "Sirf Missing", "credit": "C9",
                   "slots": ["morning"], "file": "music/nope.oga.b64",
                   "url": "https://example.invalid/nope.oga"}]
        manifest = os.path.join(self.tmp.name, "assets", "music.json")
        with open(manifest, "w") as f:
            json.dump({"tracks": tracks}, f)

        def boom(url, dest):
            raise RuntimeError("429")
        with mock.patch.object(make_video, "_download", boom):
            got = make_video.fetch_music({"slot": "morning"}, self.workdir)
        self.assertIsNone(got)


class TestMixFilter(unittest.TestCase):
    def test_normalize_zero_and_limiter(self):
        fc = make_video._mix_filter("subtitles=x.srt", 80.0)
        self.assertIn("normalize=0", fc)   # aadha-hone wala bug band
        self.assertIn("alimiter=limit=0.95", fc)
        self.assertIn(f"volume={make_video.MUSIC_VOLUME}", fc)
        self.assertIn("afade=t=out:st=76.0:d=4", fc)


if __name__ == "__main__":
    unittest.main()
