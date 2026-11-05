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
# Music sunai hi nahi deta tha — DO wajah pakdi gayi (2026-11-05):
# (1) amix ka default normalize=1 mix me har input ko aadha kar deta
# tha, matlab 0.20 asal me 0.10 bajta tha; ab normalize=0 hai, isliye
# ye number jo hai wahi bajega. (2) Track har build me Wikimedia se
# download hota tha aur wahan 429 milne par video bina music banti
# thi — ab tracks repo me hi bundled hain (assets/music/*.b64).
# 0.25 = narration ke neeche saaf maujud, awaaz par haavi nahi.
MUSIC_VOLUME = os.environ.get("MUSIC_VOLUME", "0.25")
VOICE = os.environ.get("TTS_VOICE", "hi-IN-MadhurNeural")
# +6% Google Neural2 par thoda tez laga (Eric, 2026-11-04: "bilkul
# thoda sa slow karo, zyada nahi") — +1% matlab ~5% slow, bas ek halka
# sa farq. Google speakingRate bhi isi se banta hai (_rate_float).
RATE = os.environ.get("TTS_RATE", "+1%")
PITCH = os.environ.get("TTS_PITCH", "-2Hz")
# Captions upgrade (2026-11-04): jumla-dar-jumla TTS se har jumle ka
# start/end pakka milta hai (Phase 1), phir faster-whisper se shabd-
# highlight (Phase 2, scripts/word_captions.py). SENTENCE_GAP = jumlon
# ke beech ki halki khamoshi (seconds) — bol kata-kata na lage.
SENTENCE_GAP = 0.08
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


_KOKORO_MODEL = None  # lazy singleton — jumla-dar-jumla TTS me har
# jumle par ~350MB ka model dobara load nahi hota.


def _kokoro_cache_paths():
    cache = os.environ.get(
        "KOKORO_CACHE_DIR",
        os.path.join(os.path.expanduser("~"), ".cache", "rahasya-kokoro"))
    os.makedirs(cache, exist_ok=True)
    return (os.path.join(cache, "kokoro-v1.0.onnx"),
            os.path.join(cache, "voices-v1.0.bin"))


def _kokoro_download(url, path):
    import urllib.request
    tmp = path + ".tmp"
    urllib.request.urlretrieve(url, tmp)
    os.replace(tmp, path)


def _tts_kokoro(text, out_mp3):
    """Kokoro-82M (Apache-2.0) — poori tarah OFFLINE Hindi TTS, koi API
    key nahi, CPU par chalti hai. Model pehle istemal par cache dir me
    download hota hai (~350MB, ek hi baar). Package installed na ho ya
    kuch bhi fail ho to exception uthta hai aur chain aage gir jati
    hai — video kabhi nahi rukta. Awaaz: KOKORO_TTS_VOICE
    (hm_omega/hm_psi purush, hf_alpha/hf_beta mahila)."""
    global _KOKORO_MODEL
    import soundfile as sf
    from kokoro_onnx import Kokoro
    model_path, voices_path = _kokoro_cache_paths()
    base = ("https://github.com/thewh1teagle/kokoro-onnx/releases/"
            "download/model-files-v1.0/")
    if not os.path.exists(model_path):
        _kokoro_download(base + "kokoro-v1.0.onnx", model_path)
    if not os.path.exists(voices_path):
        _kokoro_download(base + "voices-v1.0.bin", voices_path)
    if _KOKORO_MODEL is None:
        _KOKORO_MODEL = Kokoro(model_path, voices_path)
    samples, sr = _KOKORO_MODEL.create(
        text, voice=os.environ.get("KOKORO_TTS_VOICE", "hm_omega"),
        speed=_rate_float(), lang="hi")
    if samples is None or len(samples) == 0:
        raise RuntimeError("kokoro produced no audio")
    tmp_wav = out_mp3 + ".kokoro.wav"
    try:
        sf.write(tmp_wav, samples, sr)
        sh(["ffmpeg", "-y", "-v", "error", "-i", tmp_wav,
            "-codec:a", "libmp3lame", "-q:a", "3", out_mp3])
    finally:
        if os.path.exists(tmp_wav):
            os.remove(tmp_wav)


async def _tts_edge(text, out_mp3):
    import edge_tts
    await edge_tts.Communicate(text, VOICE, rate=RATE, pitch=PITCH).save(out_mp3)


def tts(text, out_mp3):
    """Voice provider chain — first success wins: Kokoro (channel ki
    FINAL awaaz — Eric ne 2026-11-05 ko dono sample sunkar pasand ki;
    default hm_omega) -> Google Neural2 (key lagi ho to) -> Azure ->
    edge-tts (the always-available default). Narration can never be
    blocked by one provider being down. KOKORO_TTS=off se Kokoro band
    ho jata hai (purani chain par wapas)."""
    errors = []
    if os.environ.get("KOKORO_TTS", "on").lower() != "off":
        try:
            _tts_kokoro(text, out_mp3)
            print("tts: Kokoro (offline)")
            return
        except Exception as e:
            errors.append(f"kokoro: {e}")
            print("tts kokoro failed, trying next:", e)
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


def _music_ok(path):
    """Track asal me chalegi ya nahi — size aur ffprobe duration se
    jaanch. Kharab/chhoti file ko 'music mil gaya' nahi mana jayega."""
    try:
        if os.path.getsize(path) < 50_000:
            return False
        return probe_duration(path) >= 15
    except Exception:
        return False


def _decode_bundle(b64_path, dest):
    """Repo me rakhi base64 track ko asal audio file me badlo.
    (GitHub par binary seedha nahi ja sakta tha, isliye bundle .b64
    hai — checkout ke saath aata hai, koi download nahi chahiye.)"""
    import base64
    with open(b64_path, encoding="utf-8") as f:
        raw = base64.b64decode(f.read())
    with open(dest, "wb") as f:
        f.write(raw)
    return dest


def _download(url, dest):
    """Aakhiri raasta: URL se download, 429 par Retry-After ke saath
    3 koshish. Fail ho to exception — caller agla track try karega."""
    import time
    last = None
    for _ in range(3):
        try:
            r = requests.get(url, headers=UA, timeout=120)
            if r.status_code == 429:
                wait = min(int(r.headers.get("Retry-After", 10)), 20)
                print(f"music download: 429, {wait}s ruk kar retry")
                time.sleep(wait)
                continue
            r.raise_for_status()
            with open(dest, "wb") as f:
                f.write(r.content)
            return dest
        except Exception as e:
            last = e
            time.sleep(3)
    raise RuntimeError(f"download failed: {last}")


def fetch_music(topic, workdir):
    """Slot ke hisaab se background track — pakka raasta pehle:
    (1) repo me BUNDLED track (koi download nahi, 429 ka khatra
    khatm), (2) pool ke baaki tracks ek-ek karke, (3) sabse aakhir me
    URL download. Har track _music_ok se jaancha jata hai. Kuch na
    mile to None — video fir bhi banti hai (post kabhi nahi rukti),
    par log me zor se chetaavni chhapti hai aur build() ke result me
    music=None dikhta hai — chhupa hua fail nahi hoga."""
    try:
        tracks = json.load(open(MUSIC_MANIFEST, encoding="utf-8"))["tracks"]
    except Exception:
        return None
    slot = topic.get("slot")
    pool = [t for t in tracks if slot in t.get("slots", [])] or tracks
    if not pool:
        return None
    import datetime as dt
    start = dt.datetime.now().timetuple().tm_yday % len(pool)
    ordered = pool[start:] + pool[:start]  # aaj ka rotation pehle
    for pick in ordered:
        rel = pick.get("file")
        if rel:
            bundle = os.path.join(ROOT, "assets", rel)
            if os.path.exists(bundle):
                ext = os.path.splitext(rel)[0]  # .b64 hata kar asal ext
                ext = os.path.splitext(ext)[1] or ".ogg"
                dest = os.path.join(workdir, "music" + ext)
                try:
                    _decode_bundle(bundle, dest)
                    if _music_ok(dest):
                        print("music (bundled):", pick["name"],
                              "—", pick["credit"])
                        return {"path": dest, "credit": pick["credit"]}
                    print("music: bundled track kharab nikla:", pick["name"])
                except Exception as e:
                    print("music: bundle decode fail:", pick["name"], e)
    for pick in ordered:
        if not pick.get("url"):
            continue
        ext = os.path.splitext(pick["url"].split("?")[0])[1] or ".ogg"
        dest = os.path.join(workdir, "music" + ext)
        try:
            _download(pick["url"], dest)
            if _music_ok(dest):
                print("music (download):", pick["name"],
                      "—", pick["credit"])
                return {"path": dest, "credit": pick["credit"]}
        except Exception as e:
            print("music: download fail:", pick["name"], e)
    print("⚠️ MUSIC UNAVAILABLE: saare tracks fail — "
          "video BINA music banegi")
    return None


def _mix_filter(vf, duration):
    """Voice + music ka filter. amix me normalize=0 LAZMI hai —
    default normalize=1 har input ko aadha kar deta hai (yahi purani
    'music sunai nahi deta' ki asal wajah thi). Aakhir me limiter
    hai taaki dono ke judne par awaaz phate nahi."""
    fade_out = max(0.0, duration - 4)
    return (f"[0:v]{vf}[v];"
            f"[2:a]volume={MUSIC_VOLUME},afade=t=in:st=0:d=2,"
            f"afade=t=out:st={fade_out:.1f}:d=4[mus];"
            "[1:a][mus]amix=inputs=2:duration=first:"
            "dropout_transition=0:normalize=0[mixed];"
            "[mixed]alimiter=limit=0.95[a]")


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


def _silence_mp3(path, dur):
    sh(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
        "-i", "anullsrc=r=44100:cl=mono", "-t", f"{dur:.3f}",
        "-c:a", "libmp3lame", "-q:a", "4", path])


def synthesize_sentences(script, out_mp3, workdir):
    """Phase 1: jumla-dar-jumla TTS — har jumla EXISTING provider chain
    (tts()) se alag banta hai, beech me ~80ms khamoshi, phir sab jud kar
    ek voice file. Har jumle ki asal lambai probe ki jati hai, isiliye
    uska start/end BILKUL pakka hota hai — captions ka drift khatam.
    Returns (total_duration, [(sentence, start, end), ...]).
    Ek bhi jumla fail ho to raise — caller poori-script TTS par girta hai."""
    sentences = split_sentences(script)
    if len(sentences) < 2:
        # ek hi jumla: alag-alag banane se koi fayda nahi
        tts(script, out_mp3)
        return probe_duration(out_mp3), None
    gap = os.path.join(workdir, "gap.mp3")
    _silence_mp3(gap, SENTENCE_GAP)
    parts, timings, t = [], [], 0.0
    for i, s in enumerate(sentences):
        if i:
            parts.append(gap)
            t += SENTENCE_GAP
        p = os.path.join(workdir, f"sent{i}.mp3")
        tts(s, p)
        d = probe_duration(p)
        parts.append(p)
        timings.append((s, t, t + d))
        t += d
    listfile = os.path.join(workdir, "voice-parts.txt")
    with open(listfile, "w") as f:
        for p in parts:
            f.write(f"file '{os.path.abspath(p)}'\n")
    sh(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
        "-i", listfile, "-c:a", "libmp3lame", "-q:a", "3", out_mp3])
    return probe_duration(out_mp3), timings


def make_srt_from_timings(timings, path):
    """Phase-1 captions: EXACT jumla timings wali SRT. Har jumle ka samay
    usi ke phrase cues me akshar-share se banta hai — isiliye andaza
    kabhi jumle ki sarhad paar nahi kar sakta (drift impossible).
    Returns cues ki list [(start, end, text), ...]."""
    cues = []
    for sentence, start, end in timings:
        parts = wrap_caption(sentence)
        if not parts:
            continue
        total = sum(len(p) for p in parts) or 1
        t = start
        for p in parts:
            d = (end - start) * len(p) / total
            cues.append((t, t + d, p))
            t += d
        # aakhri cue ko jumle ke end par pin karo (float rounding safai)
        cues[-1] = (cues[-1][0], end, cues[-1][2])
    with open(path, "w", encoding="utf-8") as f:
        for i, (a, b, c) in enumerate(cues, 1):
            f.write(f"{i}\n{ts(a)} --> {ts(b)}\n{c}\n\n")
    return cues


def choose_captions(script, duration, voice_mp3, workdir, sent_timings):
    """Caption fallback seedhi — kabhi raise nahi karti:
      word     : faster-whisper karaoke ASS (Phase 2)
      sentence : exact jumla-timing SRT (Phase 1)
      legacy   : andaza-char-share SRT (make_srt, sabse purana raasta)
    CAPTIONS_MODE = word (default) | sentence | legacy — kill switch.
    Returns (path, is_ass)."""
    mode = os.environ.get("CAPTIONS_MODE", "word").strip().lower()
    if mode == "word":
        try:
            import word_captions
            ass = os.path.join(workdir, "captions.ass")
            if word_captions.make_word_captions(voice_mp3, script, ass):
                print("captions: word (ASS karaoke)")
                return ass, True
        except Exception as e:
            print("word captions unavailable, sentence par giro:", e)
    if mode in ("word", "sentence") and sent_timings:
        try:
            srt = os.path.join(workdir, "captions.srt")
            make_srt_from_timings(sent_timings, srt)
            print("captions: sentence (exact-timing SRT)")
            return srt, False
        except Exception as e:
            print("sentence captions failed, legacy par giro:", e)
    srt = os.path.join(workdir, "captions.srt")
    make_srt(script, duration, srt)
    print("captions: legacy (andaza SRT)")
    return srt, False


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
    # Phase 1: jumla-dar-jumla awaaz taaki har jumle ka samay pakka ho.
    # Kuch bhi gadbad ho to purani poori-script wali awaaz par giro —
    # narration kabhi captions-upgrade ki wajah se nahi rukti.
    sent_timings = None
    try:
        duration, sent_timings = synthesize_sentences(script, voice_mp3,
                                                      workdir)
    except Exception as e:
        print("sentence TTS failed, whole-script fallback:", e)
        tts(script, voice_mp3)
        duration = probe_duration(voice_mp3)
    print(f"narration: {duration:.1f}s")

    sub_path, sub_is_ass = choose_captions(script, duration, voice_mp3,
                                           workdir, sent_timings)

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
    if sub_is_ass:
        # ASS ke andar apni style pehle se hai (karaoke highlight) —
        # force_style lagana usey bigaad dega, isiliye saaf raasta.
        sub = f"subtitles={sub_path}"
    else:
        sub = (f"subtitles={sub_path}:force_style='FontName=Noto Sans "
               "Devanagari,FontSize=15,PrimaryColour=&HFFFFFF,"
               "OutlineColour=&H90000000,Outline=2,Alignment=2,MarginV=90'")
    vf = sub + hook_filter(topic, workdir)
    music = fetch_music(topic, workdir)
    if music:
        fc = _mix_filter(vf, duration)
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
