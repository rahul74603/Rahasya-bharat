"""Offline tests for stock_media helpers (no network)."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import stock_media


def _video(*files):
    return {"video_files": list(files)}


def _f(height, link="https://x/clip.mp4", ftype="video/mp4"):
    return {"height": height, "link": link, "file_type": ftype}


class TestPickFile(unittest.TestCase):
    def test_prefers_near_1600_mp4(self):
        v = _video(_f(720, "a"), _f(1920, "b"), _f(4096, "c"))
        # 1920 is closest to 1600 among >=720
        self.assertEqual(stock_media.pick_file(v), "b")

    def test_skips_small_and_non_mp4(self):
        v = _video(_f(480, "a"), _f(1080, "b", "video/webm"))
        self.assertIsNone(stock_media.pick_file(v))

    def test_empty(self):
        self.assertIsNone(stock_media.pick_file({"video_files": []}))
        self.assertIsNone(stock_media.pick_file({}))


class TestPlanMedia(unittest.TestCase):
    def test_photo_first_then_interleave(self):
        plan = stock_media.plan_media(["i0", "i1", "i2"], ["c0"])
        self.assertEqual(plan, [("image", "i0"), ("clip", "c0"),
                                ("image", "i1"), ("image", "i2")])

    def test_no_clips_photos_only(self):
        self.assertEqual(stock_media.plan_media(["i0"], []),
                         [("image", "i0")])

    def test_no_images_clips_only(self):
        self.assertEqual(stock_media.plan_media([], ["c0", "c1"]),
                         [("clip", "c0"), ("clip", "c1")])

    def test_empty(self):
        self.assertEqual(stock_media.plan_media([], []), [])

    def test_cap_six(self):
        plan = stock_media.plan_media([f"i{i}" for i in range(6)],
                                      [f"c{i}" for i in range(6)])
        self.assertLessEqual(len(plan), 6)
        self.assertEqual(plan[0], ("image", "i0"))


class _Resp:
    def __init__(self, content=b"x" * 30000, ctype="image/jpeg", fail=False):
        self.content = content
        self.headers = {"Content-Type": ctype}
        self._fail = fail

    def raise_for_status(self):
        if self._fail:
            raise RuntimeError("http 500")


class TestAiImages(unittest.TestCase):
    def test_success_writes_file(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch("requests.get", return_value=_Resp()):
                got = stock_media.fetch_ai_images("mountain fog", d, want=1)
            self.assertEqual(len(got), 1)
            self.assertTrue(os.path.exists(got[0]))

    def test_failure_returns_empty(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch("requests.get", return_value=_Resp(fail=True)):
                self.assertEqual(stock_media.fetch_ai_images("x", d, want=1),
                                 [])

    def test_non_image_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch("requests.get",
                            return_value=_Resp(ctype="text/html")):
                self.assertEqual(stock_media.fetch_ai_images("x", d, want=1),
                                 [])

    def test_empty_query(self):
        self.assertEqual(stock_media.fetch_ai_images("", "/tmp"), [])


if __name__ == "__main__":
    unittest.main()
