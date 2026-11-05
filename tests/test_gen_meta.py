#!/usr/bin/env python3
"""Offline tests for gen_meta — Gemini is stubbed; no network, no key."""
import os
import sys
import unittest
from unittest import mock

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "scripts")
sys.path.insert(0, SCRIPTS)

import gen_meta  # noqa: E402

TOPICS = {"outro_line": "OUTRO LINE", "common_hashtags": ["#C"]}
TOPIC = {"id": "x", "slot": "morning", "hook": "hook", "title": "Draft Title",
         "desc_extra": "extra", "script": "poori script yahan hai"}

GOOD = {
    "yt_title": "झील का रहस्य | Rahasya Bharat",
    "caption": "पहली line hook wali hai aur ye caption kaafi lamba hai taaki chal jaye.\nOUTRO LINE\n#RahasyaBharat",
    "description": "Ye description bhi kaafi lambi hai, kahani ka saar ke saath.\n#RahasyaBharat",
    "tags": ["roopkund", "roopkund lake mystery", "uttarakhand rahasya",
             "skeleton lake", "hindi facts", "roopkund ki kahani"],
    "hashtags": ["#RahasyaBharat", "#HindiFacts", "#Shorts"],
    "question": "क्या आप कभी रूपकुंड जैसी किसी रहस्यमयी जगह पर गए हैं?",
}


class TestGenMeta(unittest.TestCase):
    def setUp(self):
        gen_meta._trending_hint = lambda: ""
        gen_meta._keyword_hint = lambda topic: []

    def test_groq_fallback_when_gemini_fails(self):
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "k",
                                          "GROQ_API_KEY": "g"}):
            def boom(prompt):
                raise RuntimeError("gemini down")
            gen_meta._gemini_json = boom
            gen_meta._groq_json = lambda prompt: dict(GOOD)
            meta = gen_meta.generate(TOPICS, TOPIC)
        self.assertIsNotNone(meta)
        self.assertTrue(meta["yt_title"].endswith("Rahasya Bharat"))

    def test_all_providers_fail_returns_none(self):
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "k",
                                          "GROQ_API_KEY": "g"}):
            def boom(prompt):
                raise RuntimeError("down")
            gen_meta._gemini_json = boom
            gen_meta._groq_json = boom
            self.assertIsNone(gen_meta.generate(TOPICS, TOPIC))

    def test_no_key_returns_none(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(gen_meta.generate(TOPICS, TOPIC))

    def test_good_output_accepted(self):
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "k"}):
            gen_meta._gemini_json = lambda prompt: dict(GOOD)
            meta = gen_meta.generate(TOPICS, TOPIC)
        self.assertIsNotNone(meta)
        self.assertTrue(meta["yt_title"].endswith("Rahasya Bharat"))
        self.assertGreaterEqual(len(meta["yt_tags"]), 5)
        self.assertIn("RahasyaBharat", meta["caption"])

    def test_question_carried_when_valid(self):
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "k"}):
            gen_meta._gemini_json = lambda prompt: dict(GOOD)
            meta = gen_meta.generate(TOPICS, TOPIC)
        self.assertIn("question", meta)

    def test_question_optional(self):
        noq = dict(GOOD)
        del noq["question"]
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "k"}):
            gen_meta._gemini_json = lambda prompt: noq
            meta = gen_meta.generate(TOPICS, TOPIC)
        self.assertIsNotNone(meta)
        self.assertNotIn("question", meta)

    def test_title_suffix_appended_when_missing(self):
        bad = dict(GOOD)
        bad["yt_title"] = "झील का अनसुलझा रहस्य"
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "k"}):
            gen_meta._gemini_json = lambda prompt: bad
            meta = gen_meta.generate(TOPICS, TOPIC)
        self.assertTrue(meta["yt_title"].endswith("| Rahasya Bharat"))

    def test_short_title_rejected(self):
        bad = dict(GOOD)
        bad["yt_title"] = "छोटा"
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "k"}):
            gen_meta._gemini_json = lambda prompt: bad
            self.assertIsNone(gen_meta.generate(TOPICS, TOPIC))

    def test_too_few_tags_rejected(self):
        bad = dict(GOOD)
        bad["tags"] = ["ek", "do"]
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "k"}):
            gen_meta._gemini_json = lambda prompt: bad
            self.assertIsNone(gen_meta.generate(TOPICS, TOPIC))

    def test_api_error_returns_none(self):
        def boom(prompt):
            raise RuntimeError("quota")
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "k"}):
            gen_meta._gemini_json = boom
            self.assertIsNone(gen_meta.generate(TOPICS, TOPIC))

    def test_tag_budget_trimmed(self):
        tags = gen_meta._clean_tags([f"tag number {i} lamba wala" for i in range(60)])
        self.assertLessEqual(len(", ".join(tags)), 480)
        self.assertGreater(len(tags), 5)

    def test_hashtag_brand_forced_first(self):
        tags = gen_meta._clean_hashtags(["#HindiFacts", "#Shorts"])
        self.assertEqual(tags[0], "#RahasyaBharat")

    def test_prompt_carries_keywords(self):
        p = gen_meta._prompt(TOPICS, TOPIC, "", ["रूपकुंड झील रहस्य"])
        self.assertIn("रूपकुंड झील रहस्य", p)
        self.assertIn("asal me ye khojte hain", p)

    def test_prompt_without_keywords_unchanged_shape(self):
        p = gen_meta._prompt(TOPICS, TOPIC, "", [])
        self.assertNotIn("asal me ye khojte hain", p)

    def test_ensure_keywords_appends_fitting(self):
        meta = {"yt_title": "झील का रहस्य | Rahasya Bharat",
                "description": "रूपकुंड झील की कहानी और उसका इतिहास।",
                "yt_tags": ["roopkund", "uttarakhand"]}
        meta = gen_meta._ensure_keywords(
            meta, ["रूपकुंड झील", "बिलकुल अलग विषय"])
        self.assertIn("रूपकुंड झील", meta["yt_tags"])
        self.assertNotIn("बिलकुल अलग विषय", meta["yt_tags"])

    def test_ensure_keywords_noop_without_keywords(self):
        meta = {"yt_title": "x", "description": "y", "yt_tags": ["a"]}
        self.assertEqual(gen_meta._ensure_keywords(meta, []), meta)

    def test_ensure_keywords_skips_wrong_intent(self):
        meta = {"yt_title": "झील का रहस्य | Rahasya Bharat",
                "description": "रूपकुंड झील की कहानी और उसका इतिहास।",
                "yt_tags": ["roopkund", "uttarakhand"]}
        meta = gen_meta._ensure_keywords(meta, ["रूपकुंड झील मूवी"])
        self.assertNotIn("रूपकुंड झील मूवी", meta["yt_tags"])

    def test_generate_uses_keyword_hints_end_to_end(self):
        gen_meta._keyword_hint = lambda topic: ["रूपकुंड झील"]
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "k"}):
            gen_meta._gemini_json = lambda prompt: dict(GOOD)
            meta = gen_meta.generate(TOPICS, TOPIC)
        self.assertIsNotNone(meta)
        self.assertIn("रूपकुंड झील", meta["yt_tags"])


if __name__ == "__main__":
    unittest.main()
