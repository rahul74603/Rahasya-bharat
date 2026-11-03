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
API = "https://generativelanguage.googleapis.com/v1beta/models"
PER_SLOT = 2

# Model names ROT: providers retire models without asking (2026-11-03:
# gemini-2.0-flash AND llama-3.3-70b-versatile both started returning
# 404 the same week, and every draft silently failed). So never depend
# on one name — try the current model first, then the fallbacks; an env
# override, when set, is tried before all of them.
GEMINI_MODELS = [m for m in dict.fromkeys([
    os.environ.get("GEMINI_MODEL"),
    "gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.0-flash",
]) if m]
GROQ_MODELS = [m for m in dict.fromkeys([
    os.environ.get("GROQ_MODEL"),
    "llama-3.3-70b-versatile", "openai/gpt-oss-120b", "llama-3.1-8b-instant",
]) if m]


def _gemini_json(prompt):
    import requests
    last = None
    for model in GEMINI_MODELS:
        try:
            r = requests.post(f"{API}/{model}:generateContent",
                              params={"key": os.environ["GEMINI_API_KEY"]},
                              json={"contents": [{"parts": [{"text": prompt}]}],
                                    "generationConfig": {
                                        "temperature": 0.8,
                                        "responseMimeType": "application/json"}},
                              timeout=90)
            r.raise_for_status()
            text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            text = re.sub(r"^```(?:json)?|```$", "", text.strip(),
                          flags=re.M).strip()
            return json.loads(text)
        except Exception as e:
            last = e
    raise last


def _groq_json(prompt):
    import requests
    last = None
    for model in GROQ_MODELS:
        try:
            r = requests.post("https://api.groq.com/openai/v1/chat/completions",
                              headers={"Authorization":
                                       f"Bearer {os.environ['GROQ_API_KEY']}"},
                              json={"model": model,
                                    "messages": [{"role": "user",
                                                  "content": prompt}],
                                    "temperature": 0.8,
                                    "response_format": {"type": "json_object"}},
                              timeout=90)
            r.raise_for_status()
            text = r.json()["choices"][0]["message"]["content"]
            text = re.sub(r"^```(?:json)?|```$", "", text.strip(),
                          flags=re.M).strip()
            return json.loads(text)
        except Exception as e:
            last = e
    raise last


def _draft_json(prompt):
    """Gemini first, Groq as backup — whichever answers, wins."""
    errors = []
    if os.environ.get("GEMINI_API_KEY"):
        try:
            return _gemini_json(prompt)
        except Exception as e:
            errors.append(f"gemini: {e}")
    if os.environ.get("GROQ_API_KEY"):
        try:
            return _groq_json(prompt)
        except Exception as e:
            errors.append(f"groq: {e}")
    raise RuntimeError("; ".join(errors) or "no AI key set")


def _qc(script, hook):
    """Groq's independent quality pre-check of a draft: is the story
    complete, clean, interesting? Best-effort — returns None when Groq
    is unavailable. Muse's morning review stays the final gate; this
    score just tells the reviewer where to look first."""
    if not os.environ.get("GROQ_API_KEY"):
        return None
    prompt = f"""Tum ek sakht Hindi video-script reviewer ho. Neeche ek 60-90 second ki Shorts narration script ka draft hai. Use jaancho: (1) kahani PURI hai ya adhuri kat gayi hai? (2) koi spasht gadbadi, dohraav ya ajeeb jumla? (3) shuruaat rokne wali hai aur ant me agli video ki jhalak hai? (4) sunne me interesting hai?

Hook: {hook}
Script: {script}

SIRF ek JSON object do: {{"score": 1-10 ka number, "complete": true/false, "issues": ["chhoti chhoti samasyayein, agar hon"]}}"""
    raw = _groq_json(prompt)
    score = int(raw.get("score") or 0)
    issues = [str(i)[:120] for i in (raw.get("issues") or [])][:5]
    return {"by": "groq", "score": max(1, min(10, score)),
            "complete": bool(raw.get("complete")), "issues": issues}


def _prompt(topic, next_title):
    slot_hi = "इतिहास की कहानी (सुबह)" if topic["slot"] == "morning" else "रहस्य/अनोखी जगह (शाम)"
    when = "कल सुबह" if topic["slot"] == "morning" else "कल शाम"
    return f"""Tum Hindi channel "Rahasya Bharat" ke liye ek Shorts video ki narration script ka DRAFT likh rahe ho. Series: {slot_hi}.
Video ka vishay (title): {topic['title']}
Jagah/vishay ki search query (andaz ke liye): {topic['image_query']}

SIRF ek JSON object do: {{"hook": "...", "desc_extra": "...", "script": "...", "stock_query": "..."}}

SCRIPT KE NIYAM (lazmi):
- script: Devanagari Hindi me 820-1000 characters ki boli jaane wali narration. Pehli line hook wali ho — wahi "hook" field me bhi do (ek chhoti si line jo 3 second me sunne wale ko rok de, "..." se shuru ho sakti hai jaise "एक गाँव... जहाँ...").
- Lehja: katha-vachak jaisa, aasan shabdon me, har 2-3 line me nayi baat ya mod — bore hone ki jagah na ho.
- IMAANDARI SABSE UPAR: sirf pakke, mashhoor tathya hi likho. Jo baat pakki na ho use "kaha jata hai" / "mana jata hai" karke likho. Kinwadanti ko kinwadanti hi kaho, use sach mat banao. Koi date, sankhya ya naam andaze se bilkul mat banao — shak ho to woh detail chhod do.
- Ant ki aakhri line me agli video ka tease ho: "{when} — {next_title}" ki tarz par ek chhoti si jhalak.
- desc_extra: ek line me video ka saar (caption ke liye).
- stock_query: 2-4 angrezi shabdon me stock video ki khoj — sirf MAHAUL ke liye (jaise pahad, kohra, mandir ki ghanti, udte pakshi); asli jagah ka naam mat do, mahaul do."""


def _next_title(topics, topic):
    same = [t for t in topics if t["slot"] == topic["slot"]]
    i = same.index(topic)
    nxt = same[(i + 1) % len(same)]
    return nxt["title"].split("|")[0].strip()


def main():
    if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GROQ_API_KEY")):
        print("ERROR: neither GEMINI_API_KEY nor GROQ_API_KEY is set")
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
    made = 0
    for t in picks:
        try:
            raw = _draft_json(_prompt(t, _next_title(topics, t)))
            script = str(raw.get("script") or "").strip()
            hook = str(raw.get("hook") or "").strip()
            desc = str(raw.get("desc_extra") or "").strip()
            if not (600 <= len(script) <= 1250) or len(hook) < 10:
                print(f"draft rejected (bad shape): {t['id']} script={len(script)} chars")
                continue
            stock = str(raw.get("stock_query") or "").strip()[:60]
            entry = {
                "id": t["id"], "hook": hook, "desc_extra": desc,
                "script": script, "stock_query": stock,
                "drafted_at": dt.datetime.now(ist).isoformat(timespec="seconds"),
            }
            try:
                qc = _qc(script, hook)
                if qc:
                    entry["qc"] = qc
                    print(f"qc: {t['id']} score {qc['score']}/10, "
                          f"complete={qc['complete']}, issues={qc['issues']}")
            except Exception as e:
                print(f"qc skipped for {t['id']}: {e}")
            drafts["drafts"].append(entry)
            made += 1
            print(f"drafted: {t['id']} ({len(script)} chars)")
        except Exception as e:
            print(f"draft failed for {t['id']}: {e}")

    with open(drafts_path, "w", encoding="utf-8") as f:
        json.dump(drafts, f, ensure_ascii=False, indent=1)
    print(f"drafts.json now holds {len(drafts['drafts'])} draft(s)")
    if not made:
        # Topics needed drafts and EVERY provider failed: go red so the
        # failure is seen, instead of a green run that drafted nothing
        # (the StudyGyaan silent-failure disease — never again).
        print("ERROR: 0 drafts made although topics were waiting — "
              "all AI providers failed. See the lines above.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
