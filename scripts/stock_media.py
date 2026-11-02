#!/usr/bin/env python3
"""Pexels stock VIDEO clips — atmosphere B-roll for the videos.

Honesty rule (channel ki shart): the REAL photos of the actual place
(Wikimedia Commons) remain the backbone of every video. Stock clips
are only mood/atmosphere (mountains, fog, birds, temple bells) mixed
between the real photos — a clip is never presented as the place
itself. Without a PEXELS_API_KEY, or on any failure, this returns []
and the builder silently uses photos only — a post never blocks.
"""
import os

API = "https://api.pexels.com/videos/search"
UA = {"User-Agent": "RahasyaBharatBot/1.0 (educational channel automation)"}
MAX_BYTES = 45 * 1024 * 1024


def pick_file(video):
    """Best downloadable mp4 for a portrait 1080x1920 render: tall
    enough to crop, but not a 4K monster. None when nothing fits."""
    files = [f for f in video.get("video_files", [])
             if f.get("file_type") == "video/mp4" and f.get("link")
             and (f.get("height") or 0) >= 720]
    if not files:
        return None
    files.sort(key=lambda f: abs((f.get("height") or 0) - 1600))
    return files[0]["link"]


def plan_media(images, clips):
    """Interleave real photos and stock clips, photo first (the hook
    frame must be the real place). Returns [(kind, path), ...]."""
    if not images:
        return [("clip", c) for c in clips]
    plan = []
    ci = 0
    for i, img in enumerate(images):
        plan.append(("image", img))
        if ci < len(clips) and i < len(images) - 1:
            plan.append(("clip", clips[ci]))
            ci += 1
    while ci < len(clips) and len(plan) < 6:
        plan.append(("clip", clips[ci]))
        ci += 1
    return plan[:6]


def fetch_clips(query, outdir, want=3):
    key = os.environ.get("PEXELS_API_KEY")
    if not key or not query:
        return []
    import requests
    try:
        r = requests.get(API, headers={"Authorization": key, **UA},
                         params={"query": query, "orientation": "portrait",
                                 "per_page": 12},
                         timeout=30)
        r.raise_for_status()
        videos = r.json().get("videos", [])
    except Exception as e:
        print(f"Pexels search failed: {e}")
        return []
    got = []
    for v in videos:
        link = pick_file(v)
        if not link:
            continue
        fp = os.path.join(outdir, f"clip{len(got)}.mp4")
        try:
            with requests.get(link, headers=UA, timeout=90, stream=True) as resp:
                resp.raise_for_status()
                size = 0
                with open(fp, "wb") as f:
                    for chunk in resp.iter_content(1 << 16):
                        size += len(chunk)
                        if size > MAX_BYTES:
                            raise RuntimeError("clip too large")
                        f.write(chunk)
            got.append(fp)
            print("clip:", link[:90])
        except Exception as e:
            print("clip download failed:", e)
            if os.path.exists(fp):
                os.remove(fp)
        if len(got) >= want:
            break
    return got
