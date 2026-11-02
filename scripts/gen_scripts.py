#!/usr/bin/env python3
"""Daily script DRAFTS by Gemini — raw material for Muse's review.

Picks the next script-less topics (2 morning + 2 evening, in bank order)
and asks Gemini for a narration draft each, saved to drafts.json.
Drafts are NEVER published directly: Muse reviews, fact-checks and
improves every draft before it enters topics.json (channel quality
gate). This script only guarantees the raw material keeps flowing so
the bank never runs dry.
"""
import datetime as dt
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
API = "https://generativelanguage.googleapis.com/v1beta/models"
PER_SLOT = 2


def _gemini_json(prompt):
    import requests
    r = requests.post(f"{API}/{MODEL}:generateContent",
                      params={"key": os.environ["GEMINI_API_KEY"]},
                      json={"contents": [{"parts": [{"text": prompt}]}],
                            "generationConfig": {
                                "temperature": 0.8,
                                "responseMimeType": "application/json"}},
                      timeout=90)
    r.raise_for_status()
    text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    return json.loads(text)


def _prompt(topic, next_title):
    slot_hi = "इतिहास की कहानी (सुबह)" if topic["slot"] == "morning" else "रहस्य/अनोखी जगह (शाम)"
    when = "कल सुबह" if topic["slot"] == "morning" else "कल शाम"
    return f"""Tum Hindi channel "Rahasya Bharat" ke liye ek Shorts video ki narration script ka DRAFT likh rahe ho. Series: {slot_hi}.
Video ka vishay (title): {topic['title']}
Jagah/vishay ki search query (andaz ke liye): {topic['image_query']}

SIRF ek JSON object do: {{"hook": "...", "desc_extra": "...", "script": "..."}}

SCRIPT KE NIYAM (lazmi):
- script: Devanagari Hindi me 820-1000 characters ki boli jaane wali narration. Pehli line hook wali ho — wahi "hook" field me bhi do (ek chhoti si line jo 3 second me sunne wale ko rok de, "..." se shuru ho sakti hai jaise "एक गाँव... जहाँ...").
- Lehja: katha-vachak jaisa, aasan shabdon me, har 2-3 line me nayi baat ya mod — bore hone ki jagah na ho.
- IMAANDARI SABSE UPAR: sirf pakke, mashhoor tathya hi likho. Jo baat pakki na ho use "kaha jata hai" / "mana jata hai" karke likho. Kinwadanti ko kinwadanti hi kaho, use sach mat banao. Koi date, sankhya ya naam andaze se bilkul mat banao — shak ho to woh detail chhod do.
- Ant ki aakhri line me agli video ka tease ho: "{when} — {next_title}" ki tarz par ek chhoti si jhalak.
- desc_extra: ek line me video ka saar (caption ke liye)."""


def _next_title(topics, topic):
    same = [t for t in topics if t["slot"] == topic["slot"]]
    i = same.index(topic)
    nxt = same[(i + 1) % len(same)]
    return nxt["title"].split("|")[0].strip()


def main():
    if not os.environ.get("GEMINI_API_KEY"):
        print("ERROR: GEMINI_API_KEY not set")
        return 1
    topics_path = os.path.join(ROOT, "topics.json")
    drafts_path = os.path.join(ROOT, "drafts.json")
    topics = json.load(open(topics_path, encoding="utf-8"))["topics"]
    try:
        drafts = json.load(open(drafts_path, encoding="utf-8"))
    except Exception:
        drafts = {"drafts": []}
    drafted_ids = {d["id"] for d in drafts["drafts"]}

    picks = []
    for slot in ("morning", "evening"):
        n = 0
        for t in topics:
            if n >= PER_SLOT:
                break
            if t["slot"] == slot and not t.get("script") and t["id"] not in drafted_ids:
                picks.append(t)
                n += 1
    if not picks:
        print("no script-less topics left to draft — bank is full")
        return 0

    ist = dt.timezone(dt.timedelta(hours=5, minutes=30))
    for t in picks:
        try:
            raw = _gemini_json(_prompt(t, _next_title(topics, t)))
            script = str(raw.get("script") or "").strip()
            hook = str(raw.get("hook") or "").strip()
            desc = str(raw.get("desc_extra") or "").strip()
            if not (600 <= len(script) <= 1250) or len(hook) < 10:
                print(f"draft rejected (bad shape): {t['id']} script={len(script)} chars")
                continue
            drafts["drafts"].append({
                "id": t["id"], "hook": hook, "desc_extra": desc,
                "script": script,
                "drafted_at": dt.datetime.now(ist).isoformat(timespec="seconds"),
            })
            print(f"drafted: {t['id']} ({len(script)} chars)")
        except Exception as e:
            print(f"draft failed for {t['id']}: {e}")

    with open(drafts_path, "w", encoding="utf-8") as f:
        json.dump(drafts, f, ensure_ascii=False, indent=1)
    print(f"drafts.json now holds {len(drafts['drafts'])} draft(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
