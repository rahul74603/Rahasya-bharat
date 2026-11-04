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

import stock_media

W, H = 1080, 1920
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MUSIC_MANIFEST = os.path.join(ROOT, "assets", "music.json")
# 0.13 par music sunai hi nahi deta tha (Eric, 2026-11-04) — 0.20 par
# narration ke neeche saaf mehsoos hota hai, awaaz par haavi nahi hota.
MUSIC_VOLUME = os.environ.get("MUSIC_VOLUME", "0.20")
VOICE = os.environ.get("TTS_VOICE", "hi-IN-MadhurNeural")
# +6% Google Neural2 par thoda tez laga (Eric, 2026-11-04: "bilkul
# thoda sa slow karo, zyada nahi") — +1% matlab ~5% slow, bas ek halka
# sa farq. Google speakingRate bhi isi se banta hai (_rate_float).
RATE = os.environ.get("TTS_RATE", "+1%")
PITCH = os.environ.get("TTS_PITCH", "-2Hz")
UA = {"User-Agent": "RahasyaBharatBot/1.0 (educational channel automation)"}
FONT = "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf"


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


def _rate_float():
    try:
        return 1.0 + float(RATE.strip().rstrip("%")) / 100.0
    except Exception:
        return 1.0


def _tts_google(text, out_mp3):
    """Google Cloud TTS (free tier) — Neural2 Hindi voices, far more
    natural than the free default. Active only when GOOGLE_TTS_API_KEY
    is set; any failure falls through to the next provider."""
    import base64
    r = requests.post(
        "https://texttospeech.googleapis.com/v1/text:synthesize",
        params={"key": os.environ["GOOGLE_TTS_API_KEY"]},
        json={"input": {"text": text},
              "voice": {"languageCode": "hi-IN",
                        "name": os.environ.get("GOOGLE_TTS_VOICE",
                                               "hi-IN-Neural2-B")},
              "audioConfig": {"audioEncoding": "MP3",
                              "speakingRate": _rate_float()}},
        timeout=120)
    r.raise_for_status()
    with open(out_mp3, "wb") as f:
        f.write(base64.b64decode(r.json()["audioContent"]))


def _tts_azure(text, out_mp3):
    """Azure Speech free tier — same voice family as edge-tts but with
    full SSML control. Active only when AZURE_SPEECH_KEY is set."""
    from xml.sax.saxutils import escape as xml_escape
    region = os.environ.get("AZURE_SPEECH_REGION", "centralindia")
    ssml = ("<speak version='1.0' xml:lang='hi-IN'>"
            f"<voice name='{VOICE}'>"
            f"<prosody rate='{RATE}' pitch='{PITCH}'>"
            f"{xml_escape(text)}</prosody></voice></speak>")
    r = requests.post(
        f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1",
        headers={"Ocp-Apim-Subscription-Key": os.environ["AZURE_SPEECH_KEY"],
                 "Content-Type": "application/ssml+xml",
                 "X-Microsoft-OutputFormat":
                     "audio-24khz-96kbitrate-mono-mp3"},
        data=ssml.encode("utf-8"), timeout=120)
    r.raise_for_status()
    with open(out_mp3, "wb") as f:
        f.write(r.content)


async def _tts_edge(text, out_mp3):
    import edge_tts
    await edge_tts.Communicate(text, VOICE, rate=RATE, pitch=PITCH).save(out_mp3)


def tts(text, out_mp3):
    """Voice provider chain — first success wins: Google Neural2 (key
    lagi ho to) -> Azure -> edge-tts (the always-available default).
    Narration can never be blocked by one provider being down."""
    errors = []
    if os.environ.get("GOOGLE_TTS_API_KEY"):
        try:
            _tts_google(text, out_mp3)
            print("tts: Google (Neural2)")
            return
        except Exception as e:
            errors.append(f"google: {e}")
            print("tts google failed, trying next:", e)
    if os.environ.get("AZURE_SPEECH_KEY"):
        try:
            _tts_azure(text, out_mp3)
            print("tts: Azure")
            return
        except Exception as e:
            errors.append(f"azure: {e}")
            print("tts azure failed, trying next:", e)
    try:
        asyncio.run(_tts_edge(text, out_mp3))
        print("tts: edge-tts", VOICE)
    except Exception as e:
        errors.append(f"edge: {e}")
        raise RuntimeError("all TTS providers failed: " + "; ".join(errors))


def fetch_music(topic, workdir):
    """Pick a background track for the topic's slot from the manifest
    (rotated daily) and download it. Music is garnish, never a gate:
    returns None on any problem and the video is built without it."""
    try:
        tracks = json.load(open(MUSIC_MANIFEST, encoding="utf-8"))["tracks"]
    except Exception:
        return None
    slot = topic.get("slot")
    pool = [t for t in tracks if slot in t.get("slots", [])] or tracks
    if not pool:
        return None
    import datetime as dt
    pick = pool[dt.datetime.now().timetuple().tm_yday % len(pool)]
    ext = os.path.splitext(pick["url"].split("?")[0])[1] or ".ogg"
    dest = os.path.join(workdir, "music" + ext)
    try:
        r = requests.get(pick["url"], headers=UA, timeout=120)
        r.raise_for_status()
        with open(dest, "wb") as f:
            f.write(r.content)
        print("music:", pick["name"], "—", pick["credit"])
        return {"path": dest, "credit": pick["credit"]}
    except Exception as e:
        print("music unavailable:", e)
        return None


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


def wrap_lines(s, width=15):
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
    return lines


def hook_filter(topic, workdir):
    """Big hook text over the first ~3 seconds — the scroll-stopper.
    Returns an extra ffmpeg filter fragment ('' when unavailable)."""
    hook = (topic.get("hook") or "").strip()
    if not hook or not os.path.exists(FONT):
        return ""
    path = os.path.join(workdir, "hook.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(wrap_lines(hook)))
    return (f",drawtext=fontfile={FONT}:textfile={path}:"
            "fontcolor=white:fontsize=84:borderw=3:bordercolor=black:"
            "box=1:boxcolor=black@0.45:boxborderw=26:"
            "x=(w-text_w)/2:y=h*0.26:line_spacing=16:"
            "enable='between(t\\,0\\,3.2)'")


def seg_from_clip(clip, dur, out):
    # stock atmosphere clip: loop if short, crop-cover to 1080x1920
    vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase,"
          f"crop={W}:{H},fps=30,setsar=1")
    sh(["ffmpeg", "-y", "-v", "error", "-stream_loop", "-1", "-i", clip,
        "-vf", vf, "-t", f"{dur:.2f}", "-c:v", "libx264",
        "-pix_fmt", "yuv420p", out])


def seg_from_card(text, dur, out):
    # fallback: dark card with the topic title in Devanagari
    safe = text.replace("'", "").replace(":", " ")
    vf = (f"drawtext=fontfile={FONT}:"
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
    tts(script, voice_mp3)
    duration = probe_duration(voice_mp3)
    print(f"narration: {duration:.1f}s")

    srt = os.path.join(workdir, "captions.srt")
    make_srt(script, duration, srt)

    images = fetch_images(topic["image_query"], workdir)
    if len(images) < 2:
        # Commons par asli photos kam mili — mahaul ke liye generated
        # tasveerein (asli photos ke BAAD hi lagti hain, jagah nahi banti)
        try:
            images += stock_media.fetch_ai_images(
                topic.get("stock_query") or topic["image_query"],
                workdir, want=3 - len(images))
        except Exception as e:
            print(f"ai images unavailable: {e}")
    clips = []
    if os.environ.get("PEXELS_API_KEY") and topic.get("stock_query"):
        try:
            clips = stock_media.fetch_clips(topic["stock_query"], workdir)
        except Exception as e:
            print(f"stock clips unavailable, photos only: {e}")
            clips = []
    plan = stock_media.plan_media(images, clips)
    nseg = len(plan) if plan else 3
    seg_dur = duration / nseg
    segs = []
    for i in range(nseg):
        seg = os.path.join(workdir, f"seg{i}.mp4")
        if plan:
            kind, src = plan[i]
            if kind == "clip":
                seg_from_clip(src, seg_dur, seg)
            else:
                seg_from_image(src, seg_dur, seg)
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
    vf = sub + hook_filter(topic, workdir)
    music = fetch_music(topic, workdir)
    if music:
        fade_out = max(0.0, duration - 4)
        fc = (f"[0:v]{vf}[v];"
              f"[2:a]volume={MUSIC_VOLUME},afade=t=in:st=0:d=2,"
              f"afade=t=out:st={fade_out:.1f}:d=4[mus];"
              "[1:a][mus]amix=inputs=2:duration=first:"
              "dropout_transition=0[a]")
        sh(["ffmpeg", "-y", "-v", "error", "-i", silent, "-i", voice_mp3,
            "-stream_loop", "-1", "-i", music["path"],
            "-filter_complex", fc, "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-c:a", "aac", "-b:a", "160k", "-shortest", out])
    else:
        sh(["ffmpeg", "-y", "-v", "error", "-i", silent, "-i", voice_mp3,
            "-vf", vf, "-map", "0:v", "-map", "1:a",
            "-c:v", "libx264",
            "-preset", "medium", "-crf", "20", "-c:a", "aac", "-b:a", "160k",
            "-shortest", out])
    print("video:", out, f"{os.path.getsize(out) / 1e6:.1f} MB")
    return {"video": out, "duration": duration,
            "music": music["credit"] if music else None}


if __name__ == "__main__":
    topic = json.load(open(sys.argv[1], encoding="utf-8"))
    print(json.dumps(build(topic, sys.argv[2])))
