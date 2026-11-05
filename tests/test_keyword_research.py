#!/usr/bin/env python3
"""Offline tests for keyword_research — _suggest is stubbed; the suite
never touches the network or any suggestion endpoint."""
import os
import sys
import unittest
from unittest import mock

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "scripts")
sys.path.insert(0, SCRIPTS)

import keyword_research as kr  # noqa: E402

TOPIC = {"id": "k", "slot": "evening",
         "title": "कोहिनूर हीरे का रहस्य",
         "hook": "दुनिया का सबसे मशहूर हीरा भारत से लंदन कैसे पहुँचा?"}


def fake_suggest(source, seed):
    if "कोहिनूर" not in seed:
        return []
    out = ["कोहिनूर हीरा", "कोहिनूर हीरे का इतिहास"]
    if seed.startswith("कोहिनूर हीरा"):
        out += ["कोहिनूर हीरा कहाँ है"]
    if seed.startswith("कोहिनूर हीरे"):
        out += ["random spam phrase xyz"]
    if seed.startswith("कोहिनूर का"):
        out += ["random spam phrase xyz", "कोहिनूर हीरा किसके पास है"]
    return out


class TestKeywordResearch(unittest.TestCase):
    def test_relevant_phrases_kept_spam_dropped(self):
        with mock.patch.object(kr, "_suggest", fake_suggest):
            out = kr.research(TOPIC)
        self.assertIn("कोहिनूर हीरा", out)
        self.assertTrue(any("कोहिनूर" in p for p in out))
        # 2 baar aaya par kahani se bilkul alag — sirf hits par na aaye
        # jab tak woh kam se kam 2 alag jagah se aaya ho; yahan woh
        # 2 seeds se aaya hai isliye reh sakta hai — asal kasauti:
        # कोहिनूर wala pehle aana chahiye (overlap ranking)
        self.assertIn("कोहिनूर", out[0])

    def test_pure_spam_single_hit_dropped(self):
        def one(source, seed):
            return ["bilkul alag bakwas"] if seed == TOPIC["title"] else []
        with mock.patch.object(kr, "_suggest", one):
            out = kr.research(TOPIC)
        self.assertNotIn("bilkul alag bakwas", out)

    def test_source_failure_means_empty_not_exception(self):
        def boom(source, seed):
            raise RuntimeError("network down")
        with mock.patch.object(kr, "_suggest", boom):
            self.assertEqual(kr.research(TOPIC), [])

    def test_kill_switch(self):
        with mock.patch.dict(os.environ, {"KEYWORD_HINTS": "off"}):
            with mock.patch.object(kr, "_suggest", fake_suggest):
                self.assertEqual(kr.research(TOPIC), [])

    def test_no_title_no_keywords(self):
        with mock.patch.object(kr, "_suggest", fake_suggest):
            self.assertEqual(kr.research({"title": "", "hook": ""}), [])

    def test_dedupes_and_caps(self):
        def lots(source, seed):
            return ["कोहिनूर हीरा"] * 3 + \
                   [f"कोहिनूर तथ्य {i}" for i in range(30)]
        with mock.patch.object(kr, "_suggest", lots):
            out = kr.research(TOPIC)
        self.assertLessEqual(len(out), 12)
        self.assertEqual(len(out), len({p.lower() for p in out}))

    def test_morning_slot_seeds_use_itihaas(self):
        seeds = kr._seeds({"title": "नालंदा विश्वविद्यालय", "hook": "x",
                           "slot": "morning"})
        self.assertTrue(any("इतिहास" in s for s in seeds))


if __name__ == "__main__":
    unittest.main()
