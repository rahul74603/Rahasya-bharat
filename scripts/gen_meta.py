#!/usr/bin/env python3
"""Dynamic metadata — title, caption, description, tags, hashtags —
generated per video by Gemini, from the video's own script.

Why: fixed pools rotate blindly; metadata written FOR this story (its
places, names, questions) is what search and suggestions actually match.
A best-effort look at YouTube's most-popular Education titles in India
is passed as flavour — never copied, and ignored when unavailable.

Safety rails (channel rules): the prompt forbids claims that are not in
the script and forbids clickbait lies; the output is validated in code
(lengths, counts, shapes). ANY failure — no GEMINI_API_KEY, API error,
bad JSON, failed validation — returns None and the caller falls back to
the deterministic rotation in run.py. Metadata can never block a post.
"""
import json
import os
import re

API = "https://generativelanguage.googleapis.com/v1beta/models"
GROQ_API = "https://api.groq.com/openai/v1/chat/completions"

# Model names ROT: providers retire models without asking (2026-11-03:
# gemini-2.0-flash AND llama-3.3-70b-versatile both started returning
# 404 the same week, silently disabling every AI feature). Never depend
# on one name — env override first, then current models, then older.
GEMINI_MODELS = [m for m in dict.fromkeys([
    os.environ.get("GEMINI_MODEL"),
    "gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.0-flash",
]) if m]
GROQ_MODELS = [m for m in dict.fromkeys([
    os.environ.get("GROQ_MODEL"),
    "llama-3.3-70b-versatile", "openai/gpt-oss-120b", "llama-3.1-8b-instant",
]) if m]


def _groq_json(prompt):
    """Groq (free tier) — the backup brain when Gemini is unavailable."""
    import requests
    last = None
    for model in GROQ_MODELS:
        try:
            r = requests.post(GROQ_API,
                              headers={"Authorization":
                                       f"Bearer {os.environ['GROQ_API_KEY']}"},
                              json={"model": model,
                                    "messages": [{"role": "user",
                                                  "content": prompt}],
                                    "temperature": 0.7,
                                    "response_format": {"type": "json_object"}},
                              timeout=60)
            r.raise_for_status()
            text = r.json()["choices"][0]["message"]["content"]
            text = re.sub(r"^```(?:json)?|```$", "", text.strip(),
                          flags=re.M).strip()
            return json.loads(text)
        except Exception as e:
            last = e
    raise last


def _gemini_json(prompt):
    import requests
    key = os.environ["GEMINI_API_KEY"]
    last = None
    for model in GEMINI_MODELS:
        try:
            r = requests.post(f"{API}/{model}:generateContent",
                              params={"key": key},
                              json={"contents": [{"parts": [{"text": prompt}]}],
                                    "generationConfig": {
                                        "temperature": 0.7,
                                        "responseMimeType": "application/json"}},
                              timeout=60)
            r.raise_for_status()
            text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            text = re.sub(r"^```(?:json)?|```$", "", text.strip(),
                          flags=re.M).strip()
            return json.loads(text)
        except Exception as e:
            last = e
    raise last


def _trending_hint():
    """Best-effort: titles of today's most-popular IN Education videos.
    Returns '' on any problem — flavour only, never a dependency."""
    try:
        import requests
        r = requests.post("https://oauth2.googleapis.com/token", data={
            "client_id": os.environ["YT_CLIENT_ID"],
            "client_secret": os.environ["YT_CLIENT_SECRET"],
            "refresh_token": os.environ["YT_REFRESH_TOKEN"],
            "grant_type": "refresh_token",
        }, timeout=30)
        r.raise_for_status()
        access = r.json()["access_token"]
        r = requests.get("https://www.googleapis.com/youtube/v3/videos",
                         params={"part": "snippet", "chart": "mostPopular",
                                 "regionCode": "IN", "videoCategoryId": "27",
                                 "maxResults": "10"},
                         headers={"Authorization": f"Bearer {access}"},
                         timeout=30)
        r.raise_for_status()
        titles = [it["snippet"]["title"] for it in r.json().get("items", [])]
        return " / ".join(titles)
    except Exception:
        return ""


def _prompt(topics, topic, trending):
    slot_hi = "इतिहास की कहानी" if topic["slot"] == "morning" else "रहस्य/अनोखी जगह"
    trend_line = (f"\nAaj India me Education category ke popular titles (sirf andaz ke liye, copy bilkul mat karna): {trending}"
                  if trending else "")
    return f"""Tum ek Hindi YouTube channel "Rahasya Bharat" ke SEO expert ho. Neeche ek Shorts video ki script di hai ({slot_hi} series). Isi video ke liye metadata banao.

Hook: {topic['hook']}
Draft title: {topic['title']}
Description extra: {topic['desc_extra']}
Script: {topic['script']}{trend_line}

SIRF ek JSON object do (koi extra text nahi):
{{"yt_title": "...", "caption": "...", "description": "...", "tags": ["...", ...], "hashtags": ["#...", ...], "question": "..."}}

NIYAM (lazmi):
- yt_title: Devanagari Hindi me, 90 characters se kam, script ke sach par based — jo baat script me nahi hai woh title me daalna MANA hai, jhootha clickbait MANA hai. Ant me "| Rahasya Bharat" jodo.
- tags: 15-20 search phrases — is kahani ke sthan, naam, prashn par. Devanagari Hindi + Hinglish + English ka mix.
- hashtags: 5-8, pehla #RahasyaBharat ho.
- caption: pehli line hook wali ho, phir 2-3 chhoti lines, ant me ye line bilkul aisi: "{topics['outro_line']}" aur phir hashtags.
- description: 3-5 lines — kahani ka saar aur ek sawal jo comment ke liye uksaye, ant me hashtags.
- question: ek chhota sawal (1 line) jo is video par pehle comment ke roop me lagega aur logon ko jawab dene par uksayega — is kahani se juda ho, "?" par khatm ho."""


def _clean_tags(raw):
    tags, seen = [], set()
    for t in raw or []:
        t = str(t).strip().lstrip("#")
        if t and t.lower() not in seen:
            seen.add(t.lower())
            tags.append(t)
    while tags and len(", ".join(tags)) > 480:
        tags.pop()
    return tags


def _clean_hashtags(raw):
    tags, seen = [], set()
    for t in raw or []:
        t = "#" + str(t).strip().lstrip("#").replace(" ", "")
        if re.fullmatch(r"#[\w\u0900-\u097F]+", t, flags=re.UNICODE) and t.lower() not in seen:
            seen.add(t.lower())
            tags.append(t)
    if "#RahasyaBharat" not in tags:
        tags.insert(0, "#RahasyaBharat")
    return tags[:8]


def _validate(raw, topics):
    if not isinstance(raw, dict):
        return None
    title = str(raw.get("yt_title") or "").strip()
    if not (10 <= len(title) <= 100):
        return None
    if "Rahasya Bharat" not in title and len(title) <= 84:
        title += " | Rahasya Bharat"
    tags = _clean_tags(raw.get("tags"))
    if len(tags) < 5:
        return None
    hashtags = _clean_hashtags(raw.get("hashtags"))
    if len(hashtags) < 3:
        return None
    caption = str(raw.get("caption") or "").strip()
    description = str(raw.get("description") or "").strip()
    if len(caption) < 40 or len(description) < 40:
        return None
    if "#RahasyaBharat" not in caption:
        caption += "\n" + " ".join(hashtags)
    if "#RahasyaBharat" not in description:
        description += "\n" + " ".join(hashtags)
    meta = {"yt_title": title, "caption": caption,
            "description": description, "yt_tags": tags}
    q = str(raw.get("question") or "").strip()
    if 10 <= len(q) <= 160:
        meta["question"] = q
    return meta


def generate(topics, topic):
    """Returns {yt_title, caption, description, yt_tags} or None.
    Provider chain: Gemini, then Groq (both free), then None —
    the caller falls back to deterministic rotation. Never raises."""
    prompt = _prompt(topics, topic, _trending_hint())
    providers = []
    if os.environ.get("GEMINI_API_KEY"):
        providers.append(("Gemini", _gemini_json))
    if os.environ.get("GROQ_API_KEY"):
        providers.append(("Groq", _groq_json))
    if not providers:
        print("gen_meta: no AI key set — fallback metadata")
        return None
    for name, fn in providers:
        try:
            meta = _validate(fn(prompt), topics)
            if meta is not None:
                print(f"gen_meta: {name} metadata ready")
                return meta
            print(f"gen_meta: {name} output failed validation")
        except Exception as e:
            print(f"gen_meta: {name} failed ({e})")
    print("gen_meta: all providers failed — fallback metadata")
    return None
