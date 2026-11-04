#!/usr/bin/env python3
"""Offline tests for the captions upgrade (Phase 1 + Phase 2).

- Phase 1: jumla-dar-jumla TTS ke exact timings aur unse bani SRT —
  cues kabhi jumle ki sarhad paar nahi karte (drift impossible).
- Phase 2: faster-whisper karaoke — alignment (screen par script ke
  hi shabd), ASS banana (sunehra highlight, BGR rang), fallback seedhi.

Sab kuch offline hai: transcriber hamesha stub hai (faster-whisper
installed ho ya na ho, model download kabhi nahi hota), TTS stub hai,
aur ffmpeg wale test sirf tab chalte hain jab ffmpeg maujud ho.

Dhyaan: test_pipeline.py sys.modules me "make_video" ka STUB ghusedta
hai (woh is file se pehle load hota hai), isiliye asli module yahan
file-path se alag naam par load kiye jate hain.
"""
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, SCRIPTS)


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(SCRIPTS, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


make_video = _load("make_video_captions_test", "make_video.py")
wc = _load("word_captions_under_test", "word_captions.py")

HAS_FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")
TS_RE = re.compile(r"(\d+):(\d+):(\d+),(\d+)\s+-->\s+(\d+):(\d+):(\d+),(\d+)")


def _sec(h, m, s, ms):
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def _srt_cues(path):
    cues = []
    with open(path, encoding="utf-8") as f:
        content = f.read()
    for match in TS_RE.finditer(content):
        g = match.groups()
        cues.append((_sec(*g[:4]), _sec(*g[4:])))
    return cues


class TestSentenceSrt(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="cap-")
        self.srt = os.path.join(self.dir, "c.srt")

    def test_cues_stay_within_sentence_bounds(self):
        timings = [("एक दो तीन चार।", 0.0, 4.0), ("पाँच छह।", 4.08, 6.08)]
        cues = make_video.make_srt_from_timings(timings, self.srt)
        self.assertEqual(len(cues), 2)
        self.assertAlmostEqual(cues[0][0], 0.0)
        self.assertAlmostEqual(cues[0][1], 4.0)   # jumla 1 ki sarhad
        self.assertAlmostEqual(cues[1][0], 4.08)  # gap ke baad shuru
        self.assertAlmostEqual(cues[1][1], 6.08)

    def test_long_sentence_split_never_crosses_boundary(self):
        sent = " ".join(["aaaa"] * 4 + ["bbbb"] * 4 + ["cccc"] * 4) + "।"
        timings = [(sent, 2.0, 12.0), ("chhota।", 12.08, 13.0)]
        cues = make_video.make_srt_from_timings(timings, self.srt)
        self.assertGreaterEqual(len(cues), 3)  # lamba jumla + chhota
        starts = [c[0] for c in cues]
        self.assertEqual(starts, sorted(starts))  # monotonic
        for a, b, _ in cues[:-1]:
            self.assertLessEqual(b, 12.0 + 1e-9)  # sarhad paar nahi
        self.assertAlmostEqual(cues[-2][1], 12.0)  # aakhri cue pinned
        self.assertAlmostEqual(cues[-1][0], 12.08)

    def test_written_file_matches_returned_cues(self):
        timings = [("पहला jumla।", 0.0, 3.0), ("दूसरा jumla।", 3.08, 5.0)]
        cues = make_video.make_srt_from_timings(timings, self.srt)
        file_cues = _srt_cues(self.srt)
        self.assertEqual(len(file_cues), len(cues))
        for (a, b, _txt), (fa, fb) in zip(cues, file_cues):
            self.assertAlmostEqual(a, fa, places=2)
            self.assertAlmostEqual(b, fb, places=2)


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg/ffprobe chahiye")
class TestSynthesizeSentences(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="synth-")
        self.out = os.path.join(self.dir, "voice.mp3")

    @staticmethod
    def _fake_tts(dur=0.6):
        def fake(text, out_mp3):
            subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                 "-i", "anullsrc=r=44100:cl=mono", "-t", str(dur),
                 "-c:a", "libmp3lame", "-q:a", "4", out_mp3],
                check=True, capture_output=True)
        return fake

    def test_exact_timings_and_gap(self):
        script = "पहला jumla hai। दूसरा jumla hai। तीसरा jumla hai।"
        with mock.patch.object(make_video, "tts", self._fake_tts()):
            total, timings = make_video.synthesize_sentences(
                script, self.out, self.dir)
        self.assertTrue(os.path.exists(self.out))
        self.assertEqual(len(timings), 3)
        starts = [t[1] for t in timings]
        self.assertEqual(starts, sorted(starts))
        for _, a, b in timings:
            self.assertTrue(0.4 < b - a < 0.95)  # ~0.6s (+mp3 padding)
        for (_, _, b1), (_, a2, _) in zip(timings, timings[1:]):
            self.assertTrue(0.0 <= a2 - b1 <= 0.35)  # ~80ms gap
        self.assertAlmostEqual(timings[0][1], 0.0)
        self.assertAlmostEqual(total, timings[-1][2], delta=0.35)

    def test_sentence_failure_raises_for_caller_fallback(self):
        calls = {"n": 0}

        def flaky(text, out_mp3):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("provider down")
            TestSynthesizeSentences._fake_tts()(text, out_mp3)

        with mock.patch.object(make_video, "tts", flaky):
            with self.assertRaises(RuntimeError):
                make_video.synthesize_sentences(
                    "एक। दो। तीन।", self.out, self.dir)


class TestAlignWords(unittest.TestCase):
    def test_exact_match_uses_heard_timings(self):
        heard = [("राम", 0.0, 0.4), ("घर", 0.5, 0.8), ("गया", 0.9, 1.4)]
        out = wc.align_words(["राम", "घर", "गया"], heard)
        self.assertEqual([w for w, _, _ in out], ["राम", "घर", "गया"])
        self.assertEqual([(s, e) for _, s, e in out],
                         [(0.0, 0.4), (0.5, 0.8), (0.9, 1.4)])

    def test_script_words_always_preserved_with_danda(self):
        heard = [("गया", 0.9, 1.4), ("राम", 0.0, 0.4), ("घर", 0.5, 0.8)]
        out = wc.align_words(["राम", "घर", "गया।"], heard)
        # screen par script ka shabd (danda sahit), samay heard ka
        self.assertEqual(out[2][0], "गया।")
        self.assertAlmostEqual(out[2][1], 0.9)

    def test_missing_word_interpolated_monotonic(self):
        heard = [("राम", 0.0, 0.4), ("गया", 0.9, 1.4)]  # "घर" gayab
        out = wc.align_words(["राम", "घर", "गया"], heard)
        self.assertEqual(len(out), 3)
        times = [(s, e) for _, s, e in out]
        for (s1, e1), (s2, e2) in zip(times, times[1:]):
            self.assertLessEqual(s1, s2)
            self.assertLess(e1, e2)
            self.assertGreater(e1, s1)
        self.assertTrue(0.4 <= times[1][0] <= 0.9)  # beech me bhara

    def test_extra_heard_words_ignored(self):
        heard = [("shor", 0.0, 0.2), ("राम", 0.3, 0.6), ("गया", 0.7, 1.0),
                 ("bheed", 1.1, 1.3)]
        out = wc.align_words(["राम", "गया"], heard)
        self.assertEqual([w for w, _, _ in out], ["राम", "गया"])

    def test_replace_block_gets_span_timings(self):
        heard = [("a", 0.0, 0.3), ("x", 0.4, 0.6), ("y", 0.7, 0.9),
                 ("d", 1.0, 1.3)]
        out = wc.align_words(["a", "b", "c", "d"], heard)
        self.assertEqual([w for w, _, _ in out], ["a", "b", "c", "d"])
        self.assertTrue(0.4 <= out[1][1] <= 0.9)
        self.assertTrue(0.4 <= out[2][1] <= 0.95)

    def test_no_anchor_returns_none(self):
        self.assertIsNone(wc.align_words(["a", "b"], []))
        script = [f"shabd{i}" for i in range(10)]
        self.assertIsNone(wc.align_words(script, [("alag", 0.0, 0.5)]))
        self.assertIsNone(wc.align_words([], [("a", 0.0, 0.5)]))


class TestAss(unittest.TestCase):
    def test_bgr_conversion(self):
        self.assertEqual(wc.rgb_to_ass_bgr("EEC45E"), "5EC4EE")
        self.assertEqual(wc.rgb_to_ass_bgr("#eec45e"), "5EC4EE")
        self.assertEqual(wc.rgb_to_ass_bgr("FFFFFF"), "FFFFFF")
        self.assertEqual(wc.GOLD_ASS, "5EC4EE")

    def test_group_phrases_balanced(self):
        tw = [(f"w{i}", i * 0.3, i * 0.3 + 0.25) for i in range(11)]
        sizes = [len(p) for p in wc.group_phrases(tw)]
        self.assertEqual(sizes, [4, 4, 3])
        tw10 = tw[:10]
        self.assertEqual([len(p) for p in wc.group_phrases(tw10)], [5, 5])
        self.assertEqual(wc.group_phrases([]), [])

    def test_build_ass_gold_moves_word_by_word(self):
        tw = [("पहला", 0.0, 0.4), ("दूसरा", 0.4, 0.8),
              ("तीसरा", 0.8, 1.2), ("चौथा", 1.2, 1.6)]
        ass = wc.build_ass(tw)
        self.assertIn("[Events]", ass)
        self.assertIn("Noto Sans Devanagari", ass)
        dlg = [l for l in ass.splitlines() if l.startswith("Dialogue:")]
        self.assertEqual(len(dlg), 4)  # har shabd-step par ek cue
        gold = "{\\c&H5EC4EE&}"
        self.assertIn(gold + "पहला", dlg[0])
        self.assertIn(gold + "दूसरा", dlg[1])
        self.assertNotIn(gold + "पहला", dlg[1])
        self.assertRegex(dlg[0], r"Dialogue: 0,\d+:\d{2}:\d{2}\.\d{2},")

    def test_make_word_captions_with_stub(self):
        heard = [("राम", 0.0, 0.4), ("घर", 0.5, 0.8), ("गया", 0.9, 1.4)]
        out = os.path.join(tempfile.mkdtemp(prefix="wc-"), "c.ass")
        ok = wc.make_word_captions("voice.mp3", "राम घर गया", out,
                                   _transcriber=lambda p: heard)
        self.assertTrue(ok)
        with open(out, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("{\\c&H5EC4EE&}", text)

    def test_make_word_captions_never_raises(self):
        out = os.path.join(tempfile.mkdtemp(prefix="wc-"), "c.ass")
        self.assertFalse(wc.make_word_captions(
            "v.mp3", "राम घर गया", out, _transcriber=lambda p: []))
        def boom(p):
            raise RuntimeError("model download fail")
        self.assertFalse(wc.make_word_captions(
            "v.mp3", "राम घर गया", out, _transcriber=boom))
        self.assertFalse(wc.make_word_captions(
            "v.mp3", "छोटी script", out,
            _transcriber=lambda p: [("a", 0.0, 0.3)]))


class TestChooseCaptions(unittest.TestCase):
    TIMINGS = [("पहला jumla।", 0.0, 3.0), ("दूसरा jumla।", 3.08, 5.5)]
    SCRIPT = "पहला jumla। दूसरा jumla।"

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="choose-")

    def _fake_wc(self, result):
        m = types.ModuleType("word_captions")
        calls = []

        def fake_make(audio, script, out_path):
            calls.append(out_path)
            if isinstance(result, Exception):
                raise result
            if result:
                with open(out_path, "w", encoding="utf-8") as f:
                    f.write("[Events]\n")
            return result

        m.make_word_captions = fake_make
        m.calls = calls
        return m

    def _choose(self, mode, fake, timings="default"):
        env = {"CAPTIONS_MODE": mode}
        with mock.patch.dict(os.environ, env), \
                mock.patch.dict(sys.modules, {"word_captions": fake}):
            return make_video.choose_captions(
                self.SCRIPT, 5.5, "voice.mp3", self.dir,
                self.TIMINGS if timings == "default" else timings)

    def test_word_mode_uses_ass_when_available(self):
        path, is_ass = self._choose("word", self._fake_wc(True))
        self.assertTrue(is_ass)
        self.assertTrue(path.endswith(".ass"))

    def test_word_failure_falls_to_sentence_srt(self):
        path, is_ass = self._choose("word", self._fake_wc(False))
        self.assertFalse(is_ass)
        self.assertTrue(path.endswith(".srt"))
        cues = _srt_cues(path)
        self.assertTrue(cues)
        self.assertLessEqual(cues[0][1], 3.0 + 0.02)  # jumla sarhad

    def test_word_exception_falls_to_sentence_srt(self):
        path, is_ass = self._choose(
            "word", self._fake_wc(RuntimeError("boom")))
        self.assertFalse(is_ass)
        self.assertTrue(os.path.exists(path))

    def test_sentence_mode_never_calls_word(self):
        fake = self._fake_wc(True)
        path, is_ass = self._choose("sentence", fake)
        self.assertFalse(is_ass)
        self.assertEqual(fake.calls, [])

    def test_legacy_mode_ignores_timings_and_word(self):
        fake = self._fake_wc(True)
        path, is_ass = self._choose("legacy", fake)
        self.assertFalse(is_ass)
        self.assertEqual(fake.calls, [])
        self.assertTrue(_srt_cues(path))

    def test_word_mode_without_timings_falls_to_legacy(self):
        path, is_ass = self._choose("word", self._fake_wc(False),
                                    timings=None)
        self.assertFalse(is_ass)
        self.assertTrue(_srt_cues(path))

    def test_legacy_make_srt_still_works(self):
        p = os.path.join(self.dir, "legacy.srt")
        make_video.make_srt("पहला भाग। दूसरा भाग।", 10.0, p)
        self.assertTrue(_srt_cues(p))


if __name__ == "__main__":
    unittest.main()
