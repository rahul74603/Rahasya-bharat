#!/usr/bin/env python3
"""Rahasya Bharat — daily orchestrator.

Pick the next script-ready topic for the slot -> build the video ->
publish to Facebook, Instagram, YouTube -> record state.

Design rule (learned from StudyGyaan): NOTHING fails silently.
Every platform is attempted, results are printed, and the run exits
non-zero if anything failed, so the Actions run turns red and is noticed.
"""
import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gh_release
import make_video
import publish_fb
import publish_ig
import publish_yt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return json.load(f)


def save(name, obj):
    with open(os.path.join(ROOT, name), "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


def ist_now():
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=5, minutes=30)))


def pick_topic(topics, state, slot):
    posted = state.get("posted", {})
    for t in topics["topics"]:
        if t["slot"] != slot or t["id"] in posted:
            continue
        if not t.get("script"):
            print(f"skip (script pending): {t['id']}")
            continue
        return t
    return None


def texts(topics, topic):
    tags = topics["common_hashtags"]
    slot_tag = "#ItihaasKiKahani" if topic["slot"] == "morning" else "#Rahasya"
    caption = (
        f"{topic['hook']}\n\n{topic['desc_extra']}\n\n"
        f"{topics['outro_line']}\n{' '.join(tags)} {slot_tag}"
    )
    description = (
        f"{topic['desc_extra']}\n\n{topic['script'][:240]}...\n\n"
        f"{topics['outro_line']}\nचैनल: {topics['handle']} (YouTube / Instagram / Facebook)\n"
        f"{' '.join(tags)} {slot_tag}"
    )
    return caption, description


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slot", choices=["morning", "evening"], required=True)
    ap.add_argument("--dry-run", action="store_true",
                    help="build the video but do not publish or update state")
    args = ap.parse_args()

    topics = load("topics.json")
    state = load("state.json")
    topic = pick_topic(topics, state, args.slot)
    if topic is None:
        print(f"ERROR: no script-ready topic left for slot={args.slot}. "
              "Add narration scripts in topics.json — refusing to post filler.")
        return 2
    print(f"topic: {topic['id']} — {topic['title']}")

    workdir = os.path.join(ROOT, "build", f"{ist_now():%Y%m%d}-{args.slot}-{topic['id']}")
    built = make_video.build(topic, workdir)
    caption, description = texts(topics, topic)

    if args.dry_run:
        print("dry-run: skipping publish. video at", built["video"])
        return 0

    results, failures = {}, []

    def attempt(name, fn):
        try:
            results[name] = fn()
            print(f"[OK] {name}")
        except Exception as e:  # report and continue with other platforms
            failures.append(f"{name}: {e}")
            print(f"[FAIL] {name}: {e}")

    attempt("facebook", lambda: publish_fb.publish(built["video"], caption))

    rel = {}
    def ig_flow():
        rid, tag, url = gh_release.create_public_copy(built["video"])
        rel.update(id=rid, tag=tag)
        return publish_ig.publish(url, caption)
    attempt("instagram", ig_flow)
    if rel:
        try:
            gh_release.delete_public_copy(rel["id"], rel["tag"])
        except Exception as e:
            failures.append(f"release-cleanup: {e}")

    attempt("youtube", lambda: publish_yt.publish(
        built["video"], topic["title"], description,
        ["Rahasya Bharat", "Hindi Facts", "Itihaas", "Rahasya"]))

    state.setdefault("posted", {})[topic["id"]] = {
        "at": ist_now().isoformat(timespec="seconds"),
        "slot": args.slot,
        "results": {k: str(v) for k, v in results.items()},
        "failures": failures,
    }
    save("state.json", state)

    print(json.dumps({"posted": topic["id"], "ok": list(results),
                      "failures": failures}, ensure_ascii=False, indent=1))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
