#!/usr/bin/env python3
"""Rahasya Bharat — video builder.

Narration (edge-tts, Hindi) + real photos of the place (Wikimedia Commons)
+ slow zoom (Ken Burns) + burnt-in Devanagari captions -> vertical 1080x1920 MP4.

No AI video generation here: GitHub Actions cannot call Muse's video model.
If Commons returns too few photos, the builder falls back to dark title
cards so the run still produces a video instead of failing silently.
"""
import asyncio
import json
import os
import re
import subprocess
import sys
import urllib.parse

import requests

W, H = 1080, 1920
VOICE = os.environ.get("TTS_VOICE", "hi-IN-MadhurNeural")
RATE = os.environ.get("TTS_RATE", "+6%")
PITCH = os.environ.get("TTS_PITCH", "-2Hz")
UA = {"User-Agent": "RahasyaBharatBot/1.0 (educational channel automation)"}


def sh(cmd):
    print("+", " ".join(cmd[:3]), "...", flush=True)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"command failed: {cmd[0]}\n{r.stderr[-2000:]}")
    return r.stdout


def probe_duration(path):
    out = sh(["ffprobe", "-v", "error", "-show_entries", "format=duration",
              "-of", "json", path])
    return float(json.loads(out)["format"]["duration"])


async def tts(text, out_mp3):
    import edge_tts
    await edge_tts.Communicate(text, VOICE, rate=RATE, pitch=PITCH).save(out_mp3)


def split_sentences(text):
    parts = re.split(r"(?<=[।!?…])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def wrap_caption(s, width=26):
    words, lines, cur = s.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 <= width:
            cur = (cur + " " + w).strip()
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    # merge into at most 2 display lines per cue by joining in pairs
    cues = []
    i = 0
    while i < len(lines):
        cues.append(" ".join(lines[i:i + 2]))
        i += 2
    return cues


def ts(sec):
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def make_srt(text, duration, path):
    sentences = split_sentences(text)
    cues = []
    for s in sentences:
        cues.extend(wrap_caption(s))
    total_chars = sum(len(c) for c in cues) or 1
    t = 0.0
    with open(path, "w", encoding="utf-8") as f:
        for i, c in enumerate(cues, 1):
            d = max(1.2, duration * len(c) / total_chars)
            f.write(f"{i}\n{ts(t)} --> {ts(min(duration, t + d))}\n{c}\n\n")
            t += d


def fetch_images(query, outdir, want=4):
    params = {
        "action": "query", "format": "json", "generator": "search",
        "gsrnamespace": 6, "gsrsearch": f"{query} filetype:bitmap",
        "gsrlimit": 14, "prop": "imageinfo",
        "iiprop": "url|size|mime", "iiurlwidth": 1600,
    }
    url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(params)
    try:
        pages = requests.get(url, headers=UA, timeout=30).json()["query"]["pages"]
    except Exception as e:
        print(f"Commons search failed: {e}")
        return []
    got = []
    for p in sorted(pages.values(), key=lambda x: x.get("index", 99)):
        info = (p.get("imageinfo") or [{}])[0]
        if info.get("mime") not in ("image/jpeg", "image/png"):
            continue
        if (info.get("width") or 0) < 900:
            continue
        src = info.get("thumburl") or info.get("url")
        try:
            r = requests.get(src, headers=UA, timeout=40)
            r.raise_for_status()
            fp = os.path.join(outdir, f"img{len(got)}.jpg")
            with open(fp, "wb") as f:
                f.write(r.content)
            got.append(fp)
            print("image:", src)
        except Exception as e:
            print("image download failed:", e)
        if len(got) >= want:
            break
    return got


def seg_from_image(img, dur, out):
    # scale to cover 1080x1920, then slow zoom-in
    vf = (f"scale={W * 2}:{H * 2}:force_original_aspect_ratio=increase,"
          f"crop={W * 2}:{H * 2},"
          f"zoompan=z='min(zoom+0.0007,1.14)':d={int(dur * 30)}:s={W}x{H}:fps=30,"
          "setsar=1")
    sh(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", img,
        "-vf", vf, "-t", f"{dur:.2f}", "-c:v", "libx264", "-pix_fmt", "yuv420p", out])


def seg_from_card(text, dur, out):
    # fallback: dark card with the topic title in Devanagari
    safe = text.replace("'", "").replace(":", " ")
    vf = (f"drawtext=fontfile=/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf:"
          f"text='{safe}':fontcolor=0xEEC45E:fontsize=64:"
          "x=(w-text_w)/2:y=(h-text_h)/2:line_spacing=14,"
          f"format=yuv420p")
    sh(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
        "-i", f"color=c=0x0B0B10:s={W}x{H}:r=30", "-vf", vf,
        "-t", f"{dur:.2f}", "-c:v", "libx264", out])


def build(topic, workdir):
    os.makedirs(workdir, exist_ok=True)
    script = topic["script"]
    voice_mp3 = os.path.join(workdir, "voice.mp3")
    asyncio.run(tts(script, voice_mp3))
    duration = probe_duration(voice_mp3)
    print(f"narration: {duration:.1f}s")

    srt = os.path.join(workdir, "captions.srt")
    make_srt(script, duration, srt)

    images = fetch_images(topic["image_query"], workdir)
    nseg = max(2, len(images)) if images else 3
    seg_dur = duration / nseg
    segs = []
    for i in range(nseg):
        seg = os.path.join(workdir, f"seg{i}.mp4")
        if images:
            seg_from_image(images[i % len(images)], seg_dur, seg)
        else:
            label = topic["title"].split("|")[0].strip() if i == 0 else topic["hook"]
            seg_from_card(label or "रहस्य भारत", seg_dur, seg)
        segs.append(seg)

    listfile = os.path.join(workdir, "concat.txt")
    with open(listfile, "w") as f:
        for s in segs:
            f.write(f"file '{os.path.abspath(s)}'\n")
    silent = os.path.join(workdir, "silent.mp4")
    sh(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
        "-i", listfile, "-c", "copy", silent])

    out = os.path.join(workdir, "video.mp4")
    sub = (f"subtitles={srt}:force_style='FontName=Noto Sans Devanagari,"
           "FontSize=15,PrimaryColour=&HFFFFFF,OutlineColour=&H90000000,"
           "Outline=2,Alignment=2,MarginV=90'")
    sh(["ffmpeg", "-y", "-v", "error", "-i", silent, "-i", voice_mp3,
        "-vf", sub, "-map", "0:v", "-map", "1:a", "-c:v", "libx264",
        "-preset", "medium", "-crf", "20", "-c:a", "aac", "-b:a", "160k",
        "-shortest", out])
    print("video:", out, f"{os.path.getsize(out) / 1e6:.1f} MB")
    return {"video": out, "duration": duration}


if __name__ == "__main__":
    topic = json.load(open(sys.argv[1], encoding="utf-8"))
    print(json.dumps(build(topic, sys.argv[2])))
