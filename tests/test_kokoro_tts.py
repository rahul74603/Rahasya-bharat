#!/usr/bin/env python3
"""Offline tests for the Kokoro offline-TTS fallback provider.

Sab kuch offline hai: kokoro_onnx aur soundfile hamesha fake modules
hain (asli ~350MB model kabhi download nahi hota), ffmpeg ki jagah
make_video.sh stub hai jo bas output file bana deta hai. Parikshit
sirf chain ka vyavhaar hai:

- kokoro safal -> mp3 banta hai, model ek hi baar load hota hai
  (jumla-dar-jumla TTS me singleton zaroori hai);
- chain me kokoro edge-tts se PEHLE aata hai;
- kokoro package na ho / create() fail ho -> chain edge par girti hai;
- KOKORO_TTS=off -> kokoro chhua hi nahi jata.

Dhyaan: test_pipeline.py sys.modules me "make_video" ka STUB ghusedta
hai, isiliye asli module yahan file-path se alag naam par load hota
hai (test_word_captions.py wala hi tareeka).
"""
import importlib.util
import os
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


make_video = _load("make_video_kokoro_test", "make_video.py")


class FakeKokoro:
    instances = 0
    fail = False

    def __init__(self, model_path, voices_path):
        FakeKokoro.instances += 1
        self.model_path = model_path

    def create(self, text, voice=None, speed=1.0, lang=None):
        if FakeKokoro.fail:
            raise RuntimeError("fake kokoro boom")
        # 0.1s ki khamoshi-jaise samples — asal content se matlab nahi,
        # sirf itna ki khaali na hon.
        return [0.0, 0.05, -0.05, 0.0] * 600, 24000


def _fake_soundfile():
    mod = types.ModuleType("soundfile")

    def write(path, samples, sr):
        with open(path, "wb") as f:
            f.write(b"fake-wav")

    mod.write = write
    return mod


def _fake_kokoro_module():
    mod = types.ModuleType("kokoro_onnx")
    mod.Kokoro = FakeKokoro
    return mod


def _fake_sh(cmd):
    # ffmpeg ki nakal: aakhiri argument wali file bana do.
    with open(cmd[-1], "wb") as f:
        f.write(b"fake-mp3")
    return ""


class KokoroBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kokoro-test-")
        self.cache = os.path.join(self.tmp, "cache")
        os.makedirs(self.cache)
        # Model files pehle se "downloaded" — download kabhi na chale.
        for name in ("kokoro-v1.0.onnx", "voices-v1.0.bin"):
            with open(os.path.join(self.cache, name), "wb") as f:
                f.write(b"fake")
        self.out = os.path.join(self.tmp, "out.mp3")
        make_video._KOKORO_MODEL = None
        FakeKokoro.instances = 0
        FakeKokoro.fail = False
        env = {k: v for k, v in os.environ.items()
               if k not in ("GOOGLE_TTS_API_KEY", "AZURE_SPEECH_KEY")}
        env["KOKORO_CACHE_DIR"] = self.cache
        self._env = mock.patch.dict(os.environ, env, clear=True)
        self._env.start()
        self._sh = mock.patch.object(make_video, "sh", _fake_sh)
        self._sh.start()
        self.edge_calls = []

        async def fake_edge(text, out_mp3):
            self.edge_calls.append(text)
            with open(out_mp3, "wb") as f:
                f.write(b"edge-mp3")

        self._edge = mock.patch.object(make_video, "_tts_edge", fake_edge)
        self._edge.start()

    def tearDown(self):
        self._edge.stop()
        self._sh.stop()
        self._env.stop()
        make_video._KOKORO_MODEL = None


class TestKokoroProvider(KokoroBase):
    def test_writes_mp3_and_caches_model(self):
        mods = {"kokoro_onnx": _fake_kokoro_module(),
                "soundfile": _fake_soundfile()}
        with mock.patch.dict(sys.modules, mods):
            make_video._tts_kokoro("पहला jumla", self.out)
            out2 = os.path.join(self.tmp, "out2.mp3")
            make_video._tts_kokoro("दूसरा jumla", out2)
        self.assertTrue(os.path.exists(self.out))
        self.assertTrue(os.path.exists(out2))
        # Singleton: do jumlon par bhi model ek hi baar bana.
        self.assertEqual(FakeKokoro.instances, 1)
        # Temp wav saaf ho gaya.
        self.assertFalse(os.path.exists(self.out + ".kokoro.wav"))

    def test_empty_audio_raises(self):
        class EmptyKokoro(FakeKokoro):
            def create(self, text, voice=None, speed=1.0, lang=None):
                return [], 24000

        mod = _fake_kokoro_module()
        mod.Kokoro = EmptyKokoro
        with mock.patch.dict(sys.modules,
                             {"kokoro_onnx": mod,
                              "soundfile": _fake_soundfile()}):
            with self.assertRaises(RuntimeError):
                make_video._tts_kokoro("kuch bhi", self.out)


class TestChainOrder(KokoroBase):
    def test_kokoro_wins_over_edge(self):
        mods = {"kokoro_onnx": _fake_kokoro_module(),
                "soundfile": _fake_soundfile()}
        with mock.patch.dict(sys.modules, mods):
            make_video.tts("namaste", self.out)
        self.assertEqual(self.edge_calls, [])
        with open(self.out, "rb") as f:
            self.assertEqual(f.read(), b"fake-mp3")

    def test_missing_package_falls_to_edge(self):
        # sys.modules me None = import fail (package installed nahi).
        with mock.patch.dict(sys.modules, {"kokoro_onnx": None}):
            make_video.tts("namaste", self.out)
        self.assertEqual(self.edge_calls, ["namaste"])
        with open(self.out, "rb") as f:
            self.assertEqual(f.read(), b"edge-mp3")

    def test_kokoro_failure_falls_to_edge(self):
        FakeKokoro.fail = True
        mods = {"kokoro_onnx": _fake_kokoro_module(),
                "soundfile": _fake_soundfile()}
        with mock.patch.dict(sys.modules, mods):
            make_video.tts("namaste", self.out)
        self.assertEqual(self.edge_calls, ["namaste"])

    def test_kill_switch_skips_kokoro(self):
        mods = {"kokoro_onnx": _fake_kokoro_module(),
                "soundfile": _fake_soundfile()}
        with mock.patch.dict(os.environ, {"KOKORO_TTS": "off"}):
            with mock.patch.dict(sys.modules, mods):
                make_video.tts("namaste", self.out)
        self.assertEqual(FakeKokoro.instances, 0)
        self.assertEqual(self.edge_calls, ["namaste"])


if __name__ == "__main__":
    unittest.main()
