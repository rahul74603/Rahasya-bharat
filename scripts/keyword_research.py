#!/usr/bin/env python3
"""Keyword research from REAL search suggestions — YouTube, Google, Bing.

Why: gen_meta asks an AI to invent tags/hashtags. Models guess; search
boxes know. The public suggestion endpoints are what browsers themselves
use for autocomplete — they return phrases real people actually type,
in Devanagari too. We harvest them for the topic's own title words,
keep only phrases tied to the story, and hand the survivors to gen_meta
as data (its honesty rules still apply: no claim beyond the script).

Hard rules: NO key, NO signup, every source independent and best-effort,
overall deadline, ANY failure returns [] and metadata falls back to the
plain AI/rotation path. KEYWORD_HINTS=off disables the whole thing.
"""
import os
import re
import time

SOURCES = ("youtube", "google", "bing")
STOP = {"hindi", "india", "bharat", "rahasya", "story", "facts",
        "video", "shorts", "youtube", "watch", "full", "viral"}
TIMEOUT = 4        # seconds per request
DEADLINE = 9       # seconds overall — metadata must never stall a post


def _significant(topic):
    """Story tokens worth matching: Devanagari words (3+) and Latin
    words (4+, minus generic filler)."""
    text = f"{topic.get('title', '')} {topic.get('hook', '')}"
    dev = re.findall(r"[\u0900-\u097F]{3,}", text)
    lat = [w for w in re.findall(r"[a-zA-Z]{4,}", text.lower())
           if w not in STOP]
    return dev, lat


def _seeds(topic):
    """Search-box seeds. Autocomplete sirf CHHOTE shabdon par kaam
    karta hai — poora title query banane se khaali list milti hai
    (2026-11-05 live jaanch). Isliye: title/hook ke pehle do bade
    shabd, sabse lamba shabd (+ slot suffix), aur aakhir me title."""
    title = (topic.get("title") or "").strip()
    if not title:
        return []
    dev_t = re.findall(r"[\u0900-\u097F]{3,}", title)
    dev_h = re.findall(r"[\u0900-\u097F]{3,}", topic.get("hook") or "")
    dev = dev_t + dev_h
    suf = " रहस्य" if topic.get("slot") == "evening" else " इतिहास"
    seeds = []
    if len(dev_t) >= 2:
        seeds.append(" ".join(dev_t[:2]))
    if len(dev_h) >= 2:
        seeds.append(" ".join(dev_h[:2]))
    if dev:
        big = max(dev, key=len)
        seeds.append(big + suf)
        seeds.append(big)
    seeds.append(title)
    out = []
    for s in seeds:
        if s and s not in out:
            out.append(s)
    return out[:5]


def _suggest(source, seed):
    """One source, one seed -> list of suggestion strings. Raises on
    any problem; the caller treats every failure as 'no data'."""
    import requests
    if source == "youtube":
        r = requests.get(
            "https://suggestqueries.google.com/complete/search",
            params={"client": "firefox", "ds": "yt", "q": seed},
            timeout=TIMEOUT)
    elif source == "google":
        r = requests.get(
            "https://suggestqueries.google.com/complete/search",
            params={"client": "firefox", "q": seed}, timeout=TIMEOUT)
    else:  # bing — the OpenSearch suggestions endpoint browsers use
        r = requests.get("https://api.bing.com/osjson.aspx",
                         params={"query": seed}, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    if isinstance(data, list) and len(data) > 1 \
            and isinstance(data[1], list):
        return [str(x) for x in data[1]]
    return []


def research(topic):
    """Up to 12 real searched phrases for this topic. Never raises."""
    if os.environ.get("KEYWORD_HINTS", "").lower() == "off":
        return []
    try:
        return _research(topic)
    except Exception:
        return []


def _research(topic):
    dev, lat = _significant(topic)
    sig = set(dev) | set(lat)
    if not sig:
        return []
    counts = {}  # lowercased phrase -> [original, {seeds it appeared for}]
    start = time.time()
    for seed in _seeds(topic):
        if time.time() - start > DEADLINE:
            break
        for src in SOURCES:
            if time.time() - start > DEADLINE:
                break
            try:
                found = _suggest(src, seed)
            except Exception:
                continue
            for s in found:
                p = " ".join(str(s).split()).strip()
                if not (3 <= len(p) <= 60):
                    continue
                toks = p.lower().split()
                if len(set(toks)) < len(toks):
                    continue  # "गोलकुंडा गोलकुंडा" jaise dohra shabd wale
                e = counts.setdefault(p.lower(), [p, set()])
                e[1].add(seed)
    scored = []
    for low, (orig, seed_set) in counts.items():
        hits = len(seed_set)
        toks = [t for t in re.split(r"\s+", low) if t]
        overlap = 0
        for t in toks:
            if t in sig or any(len(s) >= 4 and (t.startswith(s)
                                                or s.startswith(t))
                               for s in sig):
                overlap += 1
        # Relevant = touches the story, or independently suggested
        # for at least two different seeds/sources.
        if overlap >= 1 or hits >= 2:
            scored.append((overlap, hits, orig))
    scored.sort(key=lambda x: (-x[0], -x[1], len(x[2])))
    out, seen = [], set()
    for _, _, orig in scored:
        if orig.lower() not in seen:
            seen.add(orig.lower())
            out.append(orig)
        if len(out) >= 12:
            break
    return out
