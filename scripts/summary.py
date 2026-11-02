#!/usr/bin/env python3
"""Write a human-readable run summary to the GitHub Actions run page
($GITHUB_STEP_SUMMARY): what got posted, what is pending/quarantined in
the vault, and how much script-ready topic bank is left. Never fails the
run — on any error it writes what it could and exits 0.
"""
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(name, default):
    try:
        with open(os.path.join(ROOT, name), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def main():
    ist = dt.timezone(dt.timedelta(hours=5, minutes=30))
    lines = ["## Rahasya Bharat — run summary",
             f"_{dt.datetime.now(ist):%d %b %Y, %I:%M %p IST}_", ""]
    state = load("state.json", {"posted": {}})
    topics = load("topics.json", {"topics": []})
    posted = state.get("posted", {})

    manifest = None
    if os.environ.get("GH_TOKEN") and os.environ.get("GITHUB_REPOSITORY"):
        try:
            import vault
            manifest = vault.load_manifest()
        except Exception as e:
            lines.append(f"_(vault read failed: {e})_")
    pending = manifest.get("pending", {}) if manifest else {}
    quarantined = manifest.get("quarantined", {}) if manifest else {}

    if posted:
        last_id = max(posted, key=lambda k: posted[k].get("at", ""))
        last = posted[last_id]
        r = last.get("results", {})
        lines += [f"**Latest post:** `{last_id}` ({last.get('slot')}, {last.get('at')})"]
        if r.get("youtube"):
            lines.append(f"- YouTube: https://youtu.be/{r['youtube']}")
        if r.get("facebook"):
            lines.append(f"- Facebook post id: {r['facebook']}")
        if r.get("instagram"):
            lines.append(f"- Instagram media id: {r['instagram']}")
    lines.append(f"**Total videos posted:** {len(posted)}")

    if pending:
        lines.append("")
        lines.append("**⏳ Pending in vault:**")
        for tid, e in pending.items():
            missing = [p for p, s in e["platforms"].items() if s["status"] != "done"]
            lines.append(f"- `{tid}` — attempts {e.get('attempts', 0)}/3, missing: {', '.join(missing)}")
    if quarantined:
        lines.append("")
        lines.append("**🚨 QUARANTINED (needs manual review):**")
        for tid, e in quarantined.items():
            lines.append(f"- `{tid}` — {e.get('quarantine_reason', '')}")

    done_ids = set(posted) | set(pending) | set(quarantined)
    if manifest:
        done_ids |= set(manifest.get("done", {}))
    lines.append("")
    for slot in ("morning", "evening"):
        left = sum(1 for t in topics["topics"]
                   if t["slot"] == slot and t["id"] not in done_ids and t.get("script"))
        flag = " ⚠️ TOPIC BANK LOW" if left <= 3 else ""
        lines.append(f"**{slot}:** {left} script-ready topic(s) left{flag}")

    out = "\n".join(lines) + "\n"
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if target:
        with open(target, "a", encoding="utf-8") as f:
            f.write(out)
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
