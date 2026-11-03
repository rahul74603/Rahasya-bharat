#!/usr/bin/env python3
"""Rahasya Bharat — daily orchestrator (V2).

Flow per run:
  1. VAULT FIRST: any video built earlier but not fully published is
     retried — only on the platforms still missing it (duplicate-safe).
     A stuck queue blocks new builds for that slot, so videos never pile up.
  2. Otherwise pick the next script-ready topic, build the video, put it
     in the vault BEFORE publishing, then publish platform by platform,
     saving progress after every single platform.
  3. A topic is recorded as posted only when all 3 platforms have it.

Design rules: nothing fails silently (any failure -> exit 1 -> red run);
a built video is never lost; the same script is never posted twice
(topic id + script fingerprint are both checked).

V2 additions: dynamic titles and rotating hashtag pools (per slot,
rotated daily); topic-bank-low warning so the monthly refresh is visible.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gen_meta
import gh_release
import make_video
import post_comment
import preflight
import publish_fb
import publish_ig
import publish_tg
import publish_yt
import vault

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLATFORMS = ("facebook", "instagram", "youtube")
MAX_ATTEMPTS = 3  # failed runs before a pending video is quarantined
YT_TAGS = ["Rahasya Bharat", "Hindi Facts", "Itihaas", "Rahasya"]


def load(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return json.load(f)


def save(name, obj):
    with open(os.path.join(ROOT, name), "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


def ist_now():
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=5, minutes=30)))


def fingerprint(topic):
    return hashlib.sha256((topic.get("script") or "").encode("utf-8")).hexdigest()[:16]


def pick_topic(topics, posted_ids, done_fingerprints, slot):
    """Next script-ready topic for the slot, skipping anything already
    posted — by topic id OR by identical script under another id."""
    for t in topics["topics"]:
        if t["slot"] != slot or t["id"] in posted_ids:
            continue
        if not t.get("script"):
            continue
        if fingerprint(t) in done_fingerprints:
            print(f"skip (same script already posted): {t['id']}")
            continue
        return t
    return None


def script_ready_left(topics, posted_ids, slot):
    return sum(1 for t in topics["topics"]
               if t["slot"] == slot and t["id"] not in posted_ids and t.get("script"))


def texts(topics, topic, when=None):
    """Dynamic caption/description/title: hashtag pools rotate daily,
    the YouTube title alternates between the stored title and a
    hook-led variant. No fake 'trending' claims — rotation is ours."""
    when = when or ist_now()
    day = when.timetuple().tm_yday
    tags = list(topics["common_hashtags"])
    pools = topics.get("hashtag_pools", {})
    pool = pools.get("itihaas" if topic["slot"] == "morning" else "rahasya", [])
    if pool:
        start = (day + (0 if topic["slot"] == "morning" else 3)) % len(pool)
        tags += [pool[(start + i) % len(pool)] for i in range(3)]
    slot_tag = "#ItihaasKiKahani" if topic["slot"] == "morning" else "#Rahasya"
    tags.append(slot_tag)
    caption = (
        f"{topic['hook']}\n\n{topic['desc_extra']}\n\n"
        f"{topics['outro_line']}\n{' '.join(tags)}"
    )
    description = (
        f"{topic['desc_extra']}\n\n{topic['script'][:240]}...\n\n"
        f"{topics['outro_line']}\nचैनल: {topics['handle']} (YouTube / Instagram / Facebook)\n"
        f"{' '.join(tags)}"
    )
    if day % 2 == 0:
        yt_title = topic["title"]
    else:
        yt_title = topic["hook"].rstrip("।.!? ") + " | Rahasya Bharat"
    return caption, description, yt_title


def attempt(entry, name, fn):
    try:
        pid = fn()
        entry["platforms"][name] = {"status": "done", "id": str(pid), "error": None}
        print(f"[OK] {name}: {pid}")
        return True
    except Exception as e:  # report and continue with other platforms
        entry["platforms"][name] = {"status": "pending", "id": None, "error": str(e)}
        print(f"[FAIL] {name}: {e}")
        return False


def publish_entry(manifest, topic_id, entry, video_path):
    """Publish one vault entry on every platform still missing it.
    Manifest is saved after EACH platform, so progress is never lost."""
    warnings = []

    def ig_flow():
        rid, tag, url = gh_release.create_public_copy(video_path)
        try:
            return publish_ig.publish(url, entry["caption"])
        finally:
            try:
                gh_release.delete_public_copy(rid, tag)
            except Exception as e:
                warnings.append(f"ig temp-release cleanup: {e}")

    jobs = {
        "facebook": lambda: publish_fb.publish(video_path, entry["caption"]),
        "instagram": ig_flow,
        "youtube": lambda: publish_yt.publish(
            video_path, entry["yt_title"], entry["description"],
            entry.get("yt_tags") or YT_TAGS),
    }
    for name in PLATFORMS:
        if entry["platforms"][name]["status"] == "done":
            print(f"[skip] {name} already posted for {topic_id}")
            continue
        attempt(entry, name, jobs[name])
        vault.save_manifest(manifest)
    if warnings:
        print("warnings:", warnings)
    return all(entry["platforms"][p]["status"] == "done" for p in PLATFORMS)


QUESTION_FALLBACK = {
    "morning": "आपको क्या लगता है — क्या आप इस जगह की ये कहानी पहले से जानते थे? Comment में बताइए 👇",
    "evening": "आपको क्या लगता है — ये सच है या किंवदंती? Comment में अपनी राय बताइए 👇",
}


def _tg_caption(entry):
    p = entry["platforms"]
    lines = [entry["caption"], ""]
    if p["youtube"].get("id"):
        lines.append(f"▶️ YouTube: https://youtu.be/{p['youtube']['id']}")
    lines.append("📸 Instagram: https://www.instagram.com/rahasyabharatt/")
    lines.append("📘 Facebook: https://www.facebook.com/rahasyabharatt")
    return "\n".join(lines)


def try_extras(manifest, topic_id, entry, video_path=None):
    """Pinned-question comments + Telegram post — garnish, never a gate.
    The video is already posted; each extra is attempted once per run,
    recorded in entry['extras'], and failures are printed loudly but
    change nothing about the video's posted status."""
    question = entry.get("question") or QUESTION_FALLBACK.get(entry["slot"], "")
    entry.setdefault("extras", {})
    jobs = {
        "facebook": lambda: post_comment.comment_facebook(
            entry["platforms"]["facebook"]["id"], question),
        "instagram": lambda: post_comment.comment_instagram(
            entry["platforms"]["instagram"]["id"], question),
        "youtube": lambda: post_comment.comment_youtube(
            entry["platforms"]["youtube"]["id"], question),
    }
    for name in PLATFORMS:
        if entry["platforms"][name]["status"] != "done":
            continue
        if entry["extras"].get(name, {}).get("status") == "done":
            continue
        try:
            cid = jobs[name]()
            entry["extras"][name] = {"status": "done", "id": str(cid), "error": None}
            print(f"[OK] {name} sawal comment: {cid}")
        except Exception as e:
            entry["extras"][name] = {"status": "failed", "id": None, "error": str(e)}
            print(f"[FAIL] {name} sawal comment (video posted hai, ye extra hai): {e}")
        vault.save_manifest(manifest)

    # Telegram — channel ki apni audience, teeno bade platforms ke
    # algorithm se azaad. Video file chahiye, isliye sirf tab jab
    # caller ne video_path diya ho aur dono secrets lage hon.
    if (video_path and os.environ.get("TELEGRAM_BOT_TOKEN")
            and os.environ.get("TELEGRAM_CHAT_ID")
            and entry["extras"].get("telegram", {}).get("status") != "done"):
        try:
            mid = publish_tg.publish(video_path, _tg_caption(entry))
            entry["extras"]["telegram"] = {
                "status": "done", "id": str(mid), "error": None}
            print(f"[OK] telegram post: {mid}")
        except Exception as e:
            entry["extras"]["telegram"] = {
                "status": "failed", "id": None, "error": str(e)}
            print(f"[FAIL] telegram post (extra hai, video posted hai): {e}")
        vault.save_manifest(manifest)


def finish_entry(manifest, state, topic_id, entry):
    """All platforms have it: clear the vault slot, remember it forever."""
    try:
        vault.delete_video(entry["video_asset"])
    except Exception as e:
        print("vault video delete warning:", e)
    manifest["pending"].pop(topic_id, None)
    manifest["done"][topic_id] = {
        "fingerprint": entry["fingerprint"], "at": ist_now().isoformat(timespec="seconds"),
    }
    vault.save_manifest(manifest)
    state.setdefault("posted", {})[topic_id] = {
        "at": ist_now().isoformat(timespec="seconds"),
        "slot": entry["slot"],
        "results": {p: entry["platforms"][p]["id"] for p in PLATFORMS},
        "failures": [],
        "fingerprint": entry["fingerprint"],
        "comments": {p: s.get("status") for p, s in entry.get("extras", {}).items()},
    }
    save("state.json", state)


def process_vault(manifest, state, slot):
    """Retry this slot's pending videos. Returns how many are STILL
    incomplete afterwards (those block new builds for the slot)."""
    stuck = 0
    for topic_id in list(manifest["pending"].keys()):
        entry = manifest["pending"][topic_id]
        if entry["slot"] != slot:
            continue
        print(f"vault retry: {topic_id}")
        with tempfile.TemporaryDirectory() as td:
            video_path = vault.get_video(entry["video_asset"],
                                         os.path.join(td, f"{topic_id}.mp4"))
            if publish_entry(manifest, topic_id, entry, video_path):
                try_extras(manifest, topic_id, entry, video_path)
                finish_entry(manifest, state, topic_id, entry)
            else:
                entry["attempts"] = entry.get("attempts", 0) + 1
                if entry["attempts"] >= MAX_ATTEMPTS:
                    entry["quarantined_at"] = ist_now().isoformat(timespec="seconds")
                    entry["quarantine_reason"] = (
                        f"still incomplete after {entry['attempts']} failed runs")
                    manifest["quarantined"][topic_id] = entry
                    manifest["pending"].pop(topic_id, None)
                    vault.save_manifest(manifest)
                    print(f"QUARANTINED: {topic_id} — video kept in the vault, "
                          "no longer blocking new builds. Manual review needed.")
                else:
                    vault.save_manifest(manifest)
                    stuck += 1
    return stuck


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slot", choices=["morning", "evening"], required=True)
    ap.add_argument("--dry-run", action="store_true",
                    help="build the video but do not publish or update state")
    args = ap.parse_args()

    topics = load("topics.json")
    state = load("state.json")

    if args.dry_run:
        topic = pick_topic(topics, set(state.get("posted", {})),
                           {v.get("fingerprint") for v in state.get("posted", {}).values()},
                           args.slot)
        if topic is None:
            print(f"ERROR: no script-ready topic left for slot={args.slot}.")
            return 2
        workdir = os.path.join(ROOT, "build", f"{ist_now():%Y%m%d}-{args.slot}-{topic['id']}")
        built = make_video.build(topic, workdir)
        print("dry-run: skipping publish. video at", built["video"])
        return 0

    # 0) Preflight — tokens pehle, mehnat baad me. Ek bhi platform ki
    #    credential mari ho to run yahin laal, wajah ke saath.
    failed = []
    for name, ok, detail in preflight.check_all():
        print(f"preflight {name}: {'OK' if ok else 'FAIL'} — {detail}")
        if not ok:
            failed.append(name)
    if failed:
        print(f"PREFLIGHT FAILED: {', '.join(failed)} — fix the credential "
              "first; nothing was built or posted.")
        return 3

    manifest = vault.load_manifest()
    manifest.setdefault("quarantined", {})
    for qid in manifest["quarantined"]:
        print(f"WARNING: {qid} is QUARANTINED in the vault (video safe, "
              "not blocking). Manual review needed to retry or drop it.")
    posted_ids = (set(state.get("posted", {})) | set(manifest["done"])
                  | set(manifest["quarantined"]))
    done_fps = {v.get("fingerprint") for v in state.get("posted", {}).values()}
    done_fps |= {v.get("fingerprint") for v in manifest["done"].values()}
    done_fps |= {v.get("fingerprint") for v in manifest["quarantined"].values()}

    # 1) Vault first — kal ki adhuri video aaj ki nayi video se pehle.
    stuck = process_vault(manifest, state, args.slot)
    if stuck:
        print(f"ERROR: {stuck} pending video(s) for slot={args.slot} still "
              "incomplete — not building a new one until the queue clears.")
        return 1
    posted_ids = (set(state.get("posted", {})) | set(manifest["done"])
                  | set(manifest["quarantined"]))

    # 2) Next topic.
    topic = pick_topic(topics, posted_ids, done_fps, args.slot)
    left = script_ready_left(topics, posted_ids, args.slot)
    if left <= 3:
        print(f"WARNING: TOPIC BANK LOW — only {left} script-ready topic(s) "
              f"left for slot={args.slot}. Monthly topic refresh due.")
    if topic is None:
        print(f"ERROR: no script-ready topic left for slot={args.slot}. "
              "Add narration scripts in topics.json — refusing to post filler.")
        return 2
    print(f"topic: {topic['id']} — {topic['title']}")

    workdir = os.path.join(ROOT, "build", f"{ist_now():%Y%m%d}-{args.slot}-{topic['id']}")
    built = make_video.build(topic, workdir)

    # Metadata: Gemini har video ke hisaab se banata hai (dynamic);
    # na mile to purani rotation wali fallback — post kabhi nahi rukti.
    meta = gen_meta.generate(topics, topic)
    if meta:
        caption, description = meta["caption"], meta["description"]
        yt_title, yt_tags = meta["yt_title"], meta["yt_tags"]
        question = meta.get("question")
        print("metadata: Gemini dynamic (title/tags is video ke hisaab se)")
    else:
        caption, description, yt_title = texts(topics, topic)
        yt_tags = YT_TAGS
        question = None
        print("metadata: fallback rotation")
    if built.get("music"):
        description += f"\n\n🎵 Background music: {built['music']}"

    # 3) Vault BEFORE publishing — the built video can no longer be lost.
    entry = {
        "slot": args.slot, "title": topic["title"], "yt_title": yt_title,
        "caption": caption, "description": description, "yt_tags": yt_tags,
        "question": question,
        "fingerprint": fingerprint(topic),
        "attempts": 0,
        "built_at": ist_now().isoformat(timespec="seconds"),
        "video_asset": vault.put_video(topic["id"], built["video"]),
        "platforms": {p: {"status": "pending", "id": None, "error": None}
                      for p in PLATFORMS},
    }
    manifest["pending"][topic["id"]] = entry
    vault.save_manifest(manifest)
    print(f"vault: {topic['id']} stored (asset {entry['video_asset']})")

    # 4) Publish; on any failure the entry stays in the vault for next run.
    if publish_entry(manifest, topic["id"], entry, built["video"]):
        try_extras(manifest, topic["id"], entry, built["video"])
        finish_entry(manifest, state, topic["id"], entry)
        print(json.dumps({"posted": topic["id"], "ok": list(PLATFORMS)},
                         ensure_ascii=False))
        return 0
    entry["attempts"] = entry.get("attempts", 0) + 1
    vault.save_manifest(manifest)
    print(f"PARTIAL: {topic['id']} stays in the vault (attempt "
          f"{entry['attempts']}/{MAX_ATTEMPTS}) — the next run will retry "
          "only the missing platforms.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
