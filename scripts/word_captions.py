#!/usr/bin/env python3
"""Rahasya Bharat — shabd-dar-shabd (karaoke) captions, Phase 2.

faster-whisper taiyaar narration ko sunkar har shabd ka samay deta hai;
screen par shabd HAMESHA script ke hi dikhte hain — whisper se sirf
timing li jati hai, uske pehchane hue shabd kabhi nahi. Isiliye pehchan
(recognition) ki galti screen par aa hi nahi sakti.

make_word_captions() kabhi raise nahi karta: faster-whisper na ho,
model download fail ho, alignment bigde — har haal me False lautata
hai aur caller (make_video.choose_captions) purani seedhi par gir
jata hai (sentence SRT -> legacy SRT). Video captions ki wajah se
kabhi nahi rukti.

Model: env WHISPER_MODEL (default "small"), CPU + int8 — GitHub
Actions ke runner par bina GPU ke chalne ke liye.
"""
import difflib
import os
import re

# Channel ka sunehra rang #EEC45E (RGB). ASS override tags me rang
# &HBBGGRR (BGR) kram me likha jata hai: EE C4 5E -> 5E C4 EE.
GOLD_RGB = "EEC45E"
WHITE_RGB = "FFFFFF"
PHRASE_MAX = 5          # ek phrase me zyada se zyada shabd
MIN_SCRIPT_WORDS = 3    # isse chhoti script par karaoke ka matlab nahi
DEFAULT_MODEL = os.environ.get("WHISPER_MODEL", "small")

_PUNCT = "।॥.,!?;:\"'()[]{}<>|/\\—–-…*•·ʼ'‚„“”‘’"


def rgb_to_ass_bgr(rgb):
    """'EEC45E' (RGB hex) -> '5EC4EE' (ASS ka BGR kram)."""
    rgb = rgb.strip().lstrip("#").upper()
    r, g, b = rgb[0:2], rgb[2:4], rgb[4:6]
    return f"{b}{g}{r}"


GOLD_ASS = rgb_to_ass_bgr(GOLD_RGB)      # '5EC4EE'
WHITE_ASS = rgb_to_ass_bgr(WHITE_RGB)    # 'FFFFFF'


def ass_ts(sec):
    """ASS samay format: H:MM:SS.cc (centiseconds)."""
    cs = int(round(max(0.0, sec) * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def normalize(word):
    """Alignment ke liye token ki safai: lowercase + aas-paas ke
    punctuation/danda hatao. Devanagari ke andar ke nishan (matra,
    nukta, halant) bilkul nahi chhedte — woh shabd ka hissa hain."""
    w = word.strip().lower()
    w = w.strip(_PUNCT)
    w = re.sub(r"^[^\w]+|[^\w]+$", "", w, flags=re.UNICODE)
    return w


def transcribe_words(audio_path, model_name=None, _transcriber=None):
    """[(word, start, end), ...] — faster-whisper word timestamps.
    _transcriber sirf tests ke liye hook hai: callable(audio_path) ->
    iterable of (word, start, end); asli raaste par None rehta hai."""
    if _transcriber is not None:
        return [(str(w).strip(), float(s), float(e))
                for w, s, e in _transcriber(audio_path) if str(w).strip()]
    from faster_whisper import WhisperModel
    model = WhisperModel(model_name or DEFAULT_MODEL,
                         device="cpu", compute_type="int8")
    segments, _info = model.transcribe(audio_path, language="hi",
                                       word_timestamps=True, beam_size=1)
    words = []
    for seg in segments:
        for w in (seg.words or []):
            token = (w.word or "").strip()
            if token:
                words.append((token, float(w.start), float(w.end)))
    return words


def align_words(script_words, heard):
    """Script ke har shabd ko monotonic samay do.

    heard: [(word, start, end), ...] (whisper ke pehchane shabd).
    Lautata hai [(script_word, start, end), ...] — kram aur shabd
    HAMESHA script ke; samay whisper ke matched shabdon se, aur jahan
    match na mile wahan padosiyon ke beech barabar baant kar
    (interpolation). Ek bhi anchor na mile to None (caller fallback
    par jayega)."""
    if not script_words or not heard:
        return None
    heard = sorted(heard, key=lambda x: x[1])
    sn = [normalize(w) for w in script_words]
    hn = [normalize(w) for w, _, _ in heard]
    sm = difflib.SequenceMatcher(a=sn, b=hn, autojunk=False)
    times = [None] * len(script_words)
    anchored = False
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            anchored = True
            for k in range(i2 - i1):
                times[i1 + k] = [float(heard[j1 + k][1]),
                                 float(heard[j1 + k][2])]
        elif tag == "replace" and j2 > j1:
            # block-ke-block badlav: tabhi samay baanto jab dono block
            # aakar me aas-paas hon — warna ye asal match nahi hai.
            ni, nj = i2 - i1, j2 - j1
            if 0.34 <= nj / ni <= 3.0:
                anchored = True
                t0 = float(heard[j1][1])
                t1 = float(heard[j2 - 1][2])
                if t1 <= t0:
                    t1 = t0 + 0.3 * ni
                for k in range(ni):
                    times[i1 + k] = [t0 + (t1 - t0) * k / ni,
                                     t0 + (t1 - t0) * (k + 1) / ni]
    if not anchored:
        return None
    # --- khaali jagahen padosiyon se bharo (interpolation) ---
    known = [i for i, t in enumerate(times) if t is not None]
    first = known[0]
    if first > 0:  # shuru ke bina-match shabd: pehle anchor se pehle
        end0 = times[first][0]
        start0 = max(0.0, end0 - 0.3 * first)
        step = (end0 - start0) / first
        for k in range(first):
            times[k] = [start0 + step * k, start0 + step * (k + 1)]
    last = known[-1]
    if last < len(times) - 1:  # aakhir ke bina-match shabd
        t0 = times[last][1]
        for k in range(last + 1, len(times)):
            times[k] = [t0 + 0.3 * (k - last - 1), t0 + 0.3 * (k - last)]
    known = [i for i, t in enumerate(times) if t is not None]
    for a, b in zip(known, known[1:]):  # beech ke gap
        n = b - a - 1
        if n > 0:
            t0, t1 = times[a][1], max(times[b][0], times[a][1])
            step = (t1 - t0) / n
            for k in range(1, n + 1):
                times[a + k] = [t0 + step * (k - 1), t0 + step * k]
    # --- monotonic safai: har start >= pichla end, har end > start ---
    out, prev_end = [], 0.0
    for w, (s, e) in zip(script_words, times):
        s = max(float(s), prev_end)
        e = max(float(e), s + 0.05)
        out.append((w, s, e))
        prev_end = e
    return out


def group_phrases(timed_words, max_words=PHRASE_MAX):
    """Timed shabdon ko santulit phrase samoohon me baanto — har
    phrase 3–5 shabdon ka (kul ginati kam ho to chhota bhi chalega).
    Lautata hai [[(word, start, end), ...], ...]."""
    n = len(timed_words)
    if n == 0:
        return []
    nphr = max(1, -(-n // max_words))  # ceil
    base, rem = divmod(n, nphr)
    phrases, i = [], 0
    for p in range(nphr):
        size = base + (1 if p < rem else 0)
        phrases.append(list(timed_words[i:i + size]))
        i += size
    return phrases


def _clean(word):
    # ASS ke khaas nishan text me ghus aayein to style bigad jayega
    return word.replace("{", "").replace("}", "").replace("\\", "")


def build_ass(timed_words):
    """Pura ASS document banao: phrase ek baar me dikhta hai, bola ja
    raha shabd sunehra hota hai (har shabd-step par ek naya cue).
    Style metrics jaan-boojh kar SRT wale force_style jaise rakhe
    hain (PlayRes 384x288, FontSize 15, MarginV 90) taaki screen par
    aakar/jagah pehle jaisi hi lage — sirf rang badalta hai."""
    lines = [
        "[Script Info]",
        "Title: Rahasya Bharat word captions",
        "ScriptType: v4.00+",
        "PlayResX: 384",
        "PlayResY: 288",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        ("Format: Name, Fontname, Fontsize, PrimaryColour, "
         "SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
         "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
         "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, "
         "MarginV, Encoding"),
        ("Style: RB,Noto Sans Devanagari,15,&H00FFFFFF,&H00FFFFFF,"
         "&H90000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,10,10,90,1"),
        "",
        "[Events]",
        ("Format: Layer, Start, End, Style, Name, MarginL, MarginR, "
         "MarginV, Effect, Text"),
    ]
    for phrase in group_phrases(timed_words):
        for j, (word, s, e) in enumerate(phrase):
            end = phrase[j + 1][1] if j + 1 < len(phrase) else e
            end = max(end, s + 0.08)
            parts = []
            for k, (w2, _, _) in enumerate(phrase):
                w2 = _clean(w2)
                if k == j:
                    parts.append("{\\c&H" + GOLD_ASS + "&}" + w2 +
                                 "{\\c&H" + WHITE_ASS + "&}")
                else:
                    parts.append(w2)
            lines.append(
                f"Dialogue: 0,{ass_ts(s)},{ass_ts(end)},RB,,0,0,0,,"
                + " ".join(parts))
    return "\n".join(lines) + "\n"


def make_word_captions(audio_path, script, out_path, _transcriber=None):
    """voice.mp3 + script -> karaoke ASS file. Safal ho to True,
    kisi bhi gadbad par False (KABHI raise nahi) — caller apni
    fallback seedhi par gir jata hai."""
    try:
        script_words = script.split()
        if len(script_words) < MIN_SCRIPT_WORDS:
            print("word captions skipped: script bahut chhoti hai")
            return False
        heard = transcribe_words(audio_path, _transcriber=_transcriber)
        if not heard:
            print("word captions skipped: whisper se koi shabd nahi mila")
            return False
        timed = align_words(script_words, heard)
        if not timed:
            print("word captions skipped: alignment nahi ban payi")
            return False
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(build_ass(timed))
        print(f"captions: word-karaoke ASS taiyaar ({len(timed)} shabd)")
        return True
    except Exception as e:
        print("word captions failed:", e)
        return False


if __name__ == "__main__":
    import sys
    ok = make_word_captions(sys.argv[1],
                            open(sys.argv[2], encoding="utf-8").read(),
                            sys.argv[3])
    print("OK" if ok else "FALLBACK")
