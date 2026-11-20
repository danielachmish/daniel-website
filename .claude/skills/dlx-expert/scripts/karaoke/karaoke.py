#!/usr/bin/env python3
"""karaoke.py - song file -> karaoke video (instrumental + word-timed lyrics, optional key change).

Pipeline (each step is cached in <out>/work, rerun is cheap):
  1. prepare   : decode to 44.1 kHz stereo float WAV
  2. separate  : vocals / instrumental with audio-separator (BS-RoFormer or MDX-Net, CPU ok)
  3. lyrics    : force-align supplied lyrics to the VOCAL stem (stable-ts + faster-whisper),
                 or transcribe a DRAFT (uncertain words marked) when no lyrics were given
  4. lines     : on-screen lines (<= max words / natural breaks), 2 slots, next-line preview
  5. ass       : karaoke subtitles. LTR: \\kf sweep per word. RTL (Hebrew): per-letter \\k so the
                 highlight walks right-to-left (libass sweeps \\kf left-to-right even in RTL text)
  6. pitch     : optional rubberband R3 (-3 -F) on instrumental (+ guide vocal): formants kept,
                 duration unchanged
  7. mix/render: -14 LUFS, true peak <= -1 dBTP, 1920x1080 and/or 1080x1920 H.264 MP4 via libass
  8. timing.json (words, lines, count-ins, settings) for qa_karaoke.py

Usage:
  python karaoke.py --audio song.mp3 [--lyrics lyrics.txt] [--lang he|en|auto] [--semitones -1]
                    [--guide-vocal 0.15] [--bg image.jpg|#101830] [--formats 16x9,9x16] --out out_dir
Exit codes: 0 ok, 2 bad input / missing tool, 3 lyrics transcribed as draft and need confirmation.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent.parent
FONT_DIR = SKILL / "templates" / "documents" / "fonts"
FONT_NAME = "Heebo"
FONT_FILE = FONT_DIR / "Heebo-Bold.ttf"
MODEL_DIR = Path(os.environ.get("KARAOKE_MODELS", Path.home() / ".cache" / "karaoke-models"))

SEP_PRESETS = {
    # name: (model file, extra CLI args)
    "fast": ("UVR-MDX-NET-Inst_HQ_3.onnx", []),                                   # ~0.7x realtime on 4 CPU cores
    "best": ("model_bs_roformer_ep_317_sdr_12.9755.ckpt", ["--mdxc_overlap", "2"]),  # cleanest, slow on CPU
    "melband": ("mel_band_roformer_kim_ft_unwa.ckpt", ["--mdxc_overlap", "2"]),
}
ASR_DEFAULT = {"he": "ivrit-ai/whisper-large-v3-turbo-ct2", "en": "large-v3-turbo", "auto": "large-v3-turbo"}

HEB_RE = re.compile(r"[֐-׿]")
SECTION_RE = re.compile(r"^\s*[\[(].*[\])]\s*$")  # [Chorus], (x2) ...

# visual constants
SUNG = "#FFD23F"      # highlight (already sung)
UNSUNG = "#FFFFFF"
OUTLINE = "#0B1020"
LEAD_MAX = 4.0        # a line never appears more than this before it is sung
GAP_COUNTIN = 4.0     # silence before a line that triggers count-in dots
HOLD_AFTER = 0.45     # a line stays this long after its last word


def log(msg):
    print(f"[karaoke] {msg}", flush=True)


def die(msg, code=2):
    print(f"[karaoke] ERROR: {msg}", file=sys.stderr, flush=True)
    sys.exit(code)


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        die(f"command failed ({r.returncode}): {' '.join(map(str, cmd))[:300]}\n{r.stderr[-2000:]}")
    return r


def ffprobe_duration(p):
    r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)])
    return float(r.stdout.strip())


def need(tool):
    if not shutil.which(tool):
        die(f"'{tool}' not found. See scripts/karaoke/README.md (install section).")


# --------------------------------------------------------------------------------------------
# 1-2. prepare + separate
# --------------------------------------------------------------------------------------------
def prepare(audio: Path, work: Path) -> Path:
    mix = work / "mix.wav"
    if not mix.exists():
        run(["ffmpeg", "-v", "error", "-y", "-i", str(audio), "-vn", "-ac", "2", "-ar", "44100",
             "-c:a", "pcm_f32le", str(mix)])
    return mix


def separate(mix: Path, work: Path, preset: str) -> tuple[Path, Path, str]:
    voc, inst = work / "vocals.wav", work / "instrumental.wav"
    model, extra = SEP_PRESETS.get(preset, (preset, []))
    stamp = work / "separation_model.txt"
    if voc.exists() and inst.exists() and stamp.exists() and stamp.read_text().strip() == model:
        return voc, inst, model
    exe = shutil.which("audio-separator") or str(Path(sys.executable).parent / "audio-separator")
    if not Path(exe).exists():
        die("audio-separator not installed (pip install 'audio-separator[cpu]')")
    sep_dir = work / "sep"
    shutil.rmtree(sep_dir, ignore_errors=True)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    log(f"separating with {model} (CPU can take several minutes per minute of audio)...")
    run([exe, str(mix), "-m", model, "--model_file_dir", str(MODEL_DIR), "--output_dir", str(sep_dir),
         "--output_format", "WAV", *extra])
    outs = list(sep_dir.glob("*.wav"))
    v = [p for p in outs if "(Vocals)" in p.name]
    o = [p for p in outs if "(Vocals)" not in p.name]
    if not v or not o:
        die(f"unexpected separator outputs: {[p.name for p in outs]}")
    # float32 copies (rubberband / analysis friendly)
    run(["ffmpeg", "-v", "error", "-y", "-i", str(v[0]), "-c:a", "pcm_f32le", "-ar", "44100", str(voc)])
    if len(o) == 1:
        run(["ffmpeg", "-v", "error", "-y", "-i", str(o[0]), "-c:a", "pcm_f32le", "-ar", "44100", str(inst)])
    else:  # multi-stem model (e.g. demucs): instrumental = sum of non-vocal stems
        ins = sum([["-i", str(p)] for p in o], [])
        run(["ffmpeg", "-v", "error", "-y", *ins, "-filter_complex",
             f"amix=inputs={len(o)}:normalize=0", "-c:a", "pcm_f32le", "-ar", "44100", str(inst)])
    stamp.write_text(model)
    log(f"separation done in {time.time() - t0:.0f}s")
    return voc, inst, model


# --------------------------------------------------------------------------------------------
# 3. lyrics: parse / align / transcribe
# --------------------------------------------------------------------------------------------
def parse_lyrics(text: str):
    """-> list of lines; each line is a list of display words. None = section break."""
    out = []
    for raw in text.replace("\r", "").split("\n"):
        line = raw.strip().replace("‏", "").replace("‎", "")
        if not line or SECTION_RE.match(line):
            if out and out[-1] is not None:
                out.append(None)
            continue
        words = line.split()
        if words:
            out.append(words)
    while out and out[-1] is None:
        out.pop()
    return out


def norm_chars(s: str) -> str:
    """characters used to map aligned tokens back to our words: letters/digits only, no niqqud."""
    s = unicodedata.normalize("NFD", s.lower())
    return "".join(c for c in s if (c.isalnum()) and not unicodedata.combining(c))


def detect_lang(lyrics_text: str | None, vocals: Path) -> str:
    if lyrics_text:
        return "he" if len(HEB_RE.findall(lyrics_text)) > 10 else "en"
    from faster_whisper import WhisperModel
    m = WhisperModel("large-v3-turbo", device="cpu", compute_type="int8")
    _, info = m.transcribe(load16k(vocals), beam_size=1, without_timestamps=True, vad_filter=True)
    log(f"detected language {info.language} (p={info.language_probability:.2f})")
    return "he" if info.language == "he" else "en"


def load16k(path: Path):
    """16 kHz mono float32 array: passed to whisper directly (avoids PyAV version issues)."""
    import librosa
    y, _ = librosa.load(str(path), sr=16000, mono=True)
    return y.astype("float32")


def load_asr(name: str):
    import stable_whisper
    threads = max(1, os.cpu_count() or 1)
    return stable_whisper.load_faster_whisper(name, device="cpu", compute_type="int8", cpu_threads=threads)


def map_tokens(lines, aligned):
    """Assign aligned (text,start,end,prob) tokens onto our display words by character stream."""
    flat = [w for ln in lines if ln for w in ln]
    targets = [norm_chars(w) for w in flat]
    # char -> word index
    owner = []
    for i, t in enumerate(targets):
        owner += [i] * len(t)
    starts, ends, probs = [None] * len(flat), [None] * len(flat), [[] for _ in flat]
    pos = 0
    for tok, s, e, p in aligned:
        n = len(norm_chars(tok))
        if n == 0:
            continue
        idxs = set(owner[pos:pos + n]) if pos < len(owner) else set()
        for i in idxs:
            starts[i] = s if starts[i] is None else min(starts[i], s)
            ends[i] = e if ends[i] is None else max(ends[i], e)
            probs[i].append(p)
        pos += n
    if pos != len(owner):
        log(f"WARNING: aligned text length {pos} != lyrics length {len(owner)} (check lyrics vs. audio)")
    words = []
    for i, w in enumerate(flat):
        words.append({"text": w, "start": starts[i], "end": ends[i],
                      "prob": round(min(probs[i]), 3) if probs[i] else None})
    fix_word_times(words)
    return words


def fix_word_times(words):
    """interpolate missing times, enforce monotonic, min 80 ms, no overlap."""
    n = len(words)
    known = [i for i, w in enumerate(words) if w["start"] is not None and w["end"] is not None]
    if not known:
        die("alignment produced no timestamps")
    for i, w in enumerate(words):
        if w["start"] is None:
            prev = max([k for k in known if k < i], default=None)
            nxt = min([k for k in known if k > i], default=None)
            a = words[prev]["end"] if prev is not None else max(0.0, words[nxt]["start"] - 0.5)
            b = words[nxt]["start"] if nxt is not None else a + 0.5
            span_n = (nxt if nxt is not None else n) - (prev if prev is not None else -1) - 1
            k = i - (prev if prev is not None else -1) - 1
            step = (b - a) / max(span_n, 1)
            w["start"], w["end"], w["interpolated"] = a + k * step, a + (k + 1) * step, True
    for i, w in enumerate(words):
        if i and w["start"] < words[i - 1]["end"]:
            mid = (w["start"] + words[i - 1]["end"]) / 2
            words[i - 1]["end"] = max(words[i - 1]["start"] + 0.05, mid)
            w["start"] = words[i - 1]["end"]
        w["end"] = max(w["end"], w["start"] + 0.08)
        w["start"], w["end"] = round(w["start"], 3), round(w["end"], 3)


def align_lyrics(vocals: Path, lines, lang: str, asr: str):
    model = load_asr(asr)
    text = "\n".join(" ".join(ln) for ln in lines if ln)
    t0 = time.time()
    res = model.align(load16k(vocals), text, language=lang, original_split=True)
    if res is None:
        die("alignment failed - lyrics may not match this recording")
    toks = [(w.word, w.start, w.end, float(getattr(w, "probability", 0) or 0)) for w in res.all_words()]
    log(f"aligned {len(toks)} tokens in {time.time() - t0:.0f}s")
    return map_tokens(lines, toks)


def transcribe_draft(vocals: Path, lang: str, asr: str, work: Path):
    # faster-whisper directly: its bundled Silero VAD (ONNX, no download) skips the instrumental parts, and
    # condition_on_previous_text=False stops the "Thank you." loop whisper produces on long silences.
    from faster_whisper import WhisperModel
    model = WhisperModel(asr, device="cpu", compute_type="int8", cpu_threads=max(1, os.cpu_count() or 1))
    t0 = time.time()
    segs, _ = model.transcribe(load16k(vocals), language=lang, word_timestamps=True, vad_filter=True,
                               beam_size=5, condition_on_previous_text=False)
    allw = [w for s in segs for w in (s.words or []) if w.word.strip()]
    log(f"transcribed in {time.time() - t0:.0f}s")
    lines, words, cur = [], [], []
    for w in allw:
        if words and (w.start - words[-1]["end"] > 0.8 or re.search(r"[,.?!]$", words[-1]["text"])):
            if cur:
                lines.append(cur); cur = []
            if w.start - words[-1]["end"] > GAP_COUNTIN:
                lines.append(None)
        cur.append(w.word.strip())
        words.append({"text": w.word.strip(), "start": w.start, "end": w.end, "prob": round(float(w.probability), 3)})
    if cur:
        lines.append(cur)
    if not words:
        die("no singing detected in the vocal stem")
    fix_word_times(words)
    # draft text for the user: uncertain words wrapped in [? ]
    out, k = [], 0
    for ln in lines:
        if ln is None:
            out.append("")
            continue
        row = []
        for _ in ln:
            w = words[k]; k += 1
            row.append(f"[?{w['text']}]" if (w["prob"] or 0) < 0.5 else w["text"])
        out.append(" ".join(row))
    (work.parent / "lyrics_draft.txt").write_text("\n".join(out) + "\n", encoding="utf-8")
    return lines, words


# --------------------------------------------------------------------------------------------
# 4. lines + layout
# --------------------------------------------------------------------------------------------
def split_long(words_idx, words, max_words):
    """split a lyric line into display chunks of <= max_words, preferring punctuation / pauses."""
    if len(words_idx) <= max_words:
        return [words_idx]
    nchunks = math.ceil(len(words_idx) / max_words)
    target = len(words_idx) / nchunks
    best, best_score = None, -1e9
    for cut in range(2, len(words_idx) - 1):
        left = words_idx[:cut]
        w = words[left[-1]]
        gap = words[words_idx[cut]]["start"] - w["end"]
        score = -abs(cut - target) * 1.0 + (2.0 if re.search(r"[,.;:!?־]$", w["text"]) else 0) + min(gap, 1.0) * 3
        if score > best_score:
            best, best_score = cut, score
    return split_long(words_idx[:best], words, max_words) + split_long(words_idx[best:], words, max_words)


def build_lines(lyric_lines, words, max_words):
    disp, k, section = [], 0, 0
    for ln in lyric_lines:
        if ln is None:
            section += 1
            continue
        idx = list(range(k, k + len(ln)))
        k += len(ln)
        # also break on a long internal pause (> 2.5 s)
        cur = [idx[0]]
        groups = []
        for a, b in zip(idx, idx[1:]):
            if words[b]["start"] - words[a]["end"] > 2.5:
                groups.append(cur); cur = []
            cur.append(b)
        groups.append(cur)
        for g in groups:
            for chunk in split_long(g, words, max_words):
                disp.append({"words": chunk, "section": section})
    for i, L in enumerate(disp):
        L["start"] = words[L["words"][0]]["start"]
        L["end"] = words[L["words"][-1]]["end"]
        L["text"] = " ".join(words[j]["text"] for j in L["words"])
    return disp


def schedule(lines, beat):
    """slots (0 top / 1 bottom), appear/disappear times, count-ins."""
    countins = []
    slot = 0
    for i, L in enumerate(lines):
        gap = L["start"] - (lines[i - 1]["end"] if i else 0.0)
        if i == 0 or gap >= GAP_COUNTIN:
            slot = 0  # a new passage always starts on the top line
            n = 3 if L["start"] >= 3 * beat + 0.3 else max(1, int((L["start"] - 0.2) // beat))
            countins.append({"line": i, "beat": round(beat, 3), "dots": n,
                             "start": round(L["start"] - n * beat, 3), "end": L["start"]})
            L["countin"] = True
        L["slot"] = slot
        slot ^= 1
    for i, L in enumerate(lines):
        L["disappear"] = L["end"] + HOLD_AFTER
        if i + 1 < len(lines):  # do not linger into the next passage
            L["disappear"] = min(L["disappear"], max(L["end"] + 0.1, lines[i + 1]["start"]))
    for i, L in enumerate(lines):
        appear = L["start"] - LEAD_MAX
        if L.get("countin"):
            ci = next(c for c in countins if c["line"] == i)
            appear = min(appear, ci["start"]) if ci["start"] > appear else ci["start"] - 0.5
            appear = max(appear, L["start"] - LEAD_MAX - 0.5)
        # previous line in the same slot must be gone; previous passage must be finished
        prev_same = [lines[j] for j in range(i) if lines[j]["slot"] == L["slot"]]
        if prev_same:
            appear = max(appear, prev_same[-1]["disappear"] + 0.04)
        if i and L.get("countin"):
            appear = max(appear, lines[i - 1]["disappear"] + 0.04)
        appear = max(0.0, min(appear, L["start"] - 0.25))
        L["appear"] = round(appear, 3)
        L["disappear"] = round(max(L["disappear"], L["appear"] + 0.5), 3)
        # partner line (other slot) shown while this one is sung = next-line preview
    return countins


def estimate_beat(inst: Path) -> float:
    try:
        import librosa
        y, sr = librosa.load(str(inst), sr=22050, mono=True, duration=240)
        tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
        tempo = float(tempo if not hasattr(tempo, "__len__") else tempo[0])
        b = 60.0 / tempo if tempo > 0 else 0.75
    except Exception as e:  # noqa
        log(f"beat estimate failed ({e}); using 0.75s")
        b = 0.75
    while b < 0.5:
        b *= 2
    while b > 1.1:
        b /= 2
    return b


# --------------------------------------------------------------------------------------------
# 5. ASS
# --------------------------------------------------------------------------------------------
def ass_color(hex_rgb, alpha=0):
    h = hex_rgb.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def ass_time(t):
    t = max(0.0, t)
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def graphemes(word):
    out = []
    for ch in word:
        if out and unicodedata.combining(ch):
            out[-1] += ch
        else:
            out.append(ch)
    return out


class Measure:
    """text width in libass pixels (libass font size = ascent+descent cell height, VSFilter compatible)."""

    def __init__(self):
        from PIL import ImageFont
        self.font = ImageFont.truetype(str(FONT_FILE), 200)
        a, d = self.font.getmetrics()
        self.k = 200.0 / (a + d)

    def width(self, text, fs):
        return self.font.getlength(text) * self.k * fs / 200.0


def esc(t):
    return t.replace("\\", "\\\\").replace("{", "(").replace("}", ")")


def build_ass(lines, words, countins, W, H, rtl, title, artist, draft):
    vertical = H > W
    base_fs = 86 if not vertical else 80
    max_w = W * (0.88 if not vertical else 0.86)
    ys = [H * 0.62, H * 0.78] if not vertical else [H * 0.47, H * 0.57]
    meas = Measure()
    RLM = "‏" if rtl else ""
    hdr = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Lyric,{FONT_NAME},{base_fs},{ass_color(SUNG)},{ass_color(UNSUNG)},{ass_color(OUTLINE)},{ass_color('#000000', 0x80)},-1,0,0,0,100,100,0,0,1,{5 if not vertical else 5},2,5,0,0,0,-1
Style: Dots,DejaVu Sans,{int(base_fs * 0.5)},{ass_color(SUNG)},{ass_color(SUNG)},{ass_color(OUTLINE)},{ass_color('#000000', 0x80)},0,0,0,0,100,100,0,0,1,3,0,5,0,0,0,-1
Style: Title,{FONT_NAME},{int(base_fs * 1.15)},{ass_color(UNSUNG)},{ass_color(UNSUNG)},{ass_color(OUTLINE)},{ass_color('#000000', 0x80)},-1,0,0,0,100,100,0,0,1,4,2,5,0,0,0,-1
Style: Sub,{FONT_NAME},{int(base_fs * 0.6)},{ass_color('#C9D2E8')},{ass_color('#C9D2E8')},{ass_color(OUTLINE)},{ass_color('#000000', 0x80)},0,0,0,0,100,100,0,0,1,3,1,5,0,0,0,-1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev = []
    cx = W / 2
    geo = []
    for L in lines:
        txt = " ".join(words[j]["text"] for j in L["words"])
        fs = base_fs
        while meas.width(txt, fs) > max_w and fs > 40:
            fs -= 2
        L["font_size"] = fs
        L["width_px"] = round(meas.width(txt, fs))
        y = ys[L["slot"]]
        geo.append((fs, y))
        parts = []
        t = L["appear"]
        lead = max(0.0, L["start"] - t)
        parts.append(f"{{\\k{int(round(lead * 100))}}}{RLM}")
        cursor = L["start"]
        for n, j in enumerate(L["words"]):
            w = words[j]
            # gap before word (absorbed by an unsung space syllable)
            if n:
                gap_cs = int(round((w["start"] - cursor) * 100))
                parts.append(f"{{\\k{max(0, gap_cs)}}} ")
                cursor = w["start"]
            dur_cs = max(1, int(round((w["end"] - cursor) * 100)))
            text = esc(w["text"])
            mark = "{\\u1}" if draft and (w.get("prob") or 0) < 0.5 else ""
            unmark = "{\\u0}" if mark else ""
            if rtl:
                g = graphemes(text)
                # letters highlight one after another (right-to-left after bidi), total = word duration
                acc, per = 0, dur_cs / len(g)
                for gi, ch in enumerate(g):
                    nxt = int(round(per * (gi + 1)))
                    parts.append(f"{{\\k{nxt - acc}}}{mark if gi == 0 else ''}{ch}")
                    acc = nxt
                parts.append(unmark)
            else:
                parts.append(f"{{\\kf{dur_cs}}}{mark}{text}{unmark}")
            cursor = cursor + dur_cs / 100.0
        body = "".join(parts) + RLM
        fade = "{\\fad(180,220)}"
        ev.append(f"Dialogue: 1,{ass_time(L['appear'])},{ass_time(L['disappear'])},Lyric,,0,0,0,,"
                  f"{fade}{{\\an5\\pos({cx:.0f},{y:.0f})\\fs{fs}}}{body}")
    # count-in dots: above the upcoming line, on the side where reading starts
    for c in countins:
        L = lines[c["line"]]
        fs, y = geo[c["line"]]
        half = L["width_px"] / 2
        x = cx + half - fs * 0.6 if rtl else cx - half + fs * 0.6
        dy = y - fs * 0.95
        an = 6 if rtl else 4  # anchor right (RTL) / left (LTR)
        for k in range(c["dots"], 0, -1):
            a = c["end"] - k * c["beat"]
            b = a + c["beat"]
            dots = " ".join(["●"] * k)
            ev.append(f"Dialogue: 2,{ass_time(a)},{ass_time(b)},Dots,,0,0,0,,{{\\an{an}\\pos({x:.0f},{dy:.0f})}}{dots}")
    # title card during the intro
    if title and lines and lines[0]["appear"] > 2.0:
        end = lines[0]["appear"] - 0.1
        ty = H * (0.40 if not vertical else 0.38)
        ev.append(f"Dialogue: 0,{ass_time(0.3)},{ass_time(end)},Title,,0,0,0,,{{\\fad(400,400)\\an5\\pos({cx:.0f},{ty:.0f})}}{RLM if HEB_RE.search(title) else ''}{esc(title)}")
        if artist:
            ev.append(f"Dialogue: 0,{ass_time(0.3)},{ass_time(end)},Sub,,0,0,0,,{{\\fad(400,400)\\an5\\pos({cx:.0f},{ty + base_fs * 1.1:.0f})}}{RLM if HEB_RE.search(artist) else ''}{esc(artist)}")
    return hdr + "\n".join(ev) + "\n"


# --------------------------------------------------------------------------------------------
# 6-7. pitch, mix, render
# --------------------------------------------------------------------------------------------
def pitch_shift(src: Path, dst: Path, semis: float):
    if dst.exists() and dst.stat().st_mtime > src.stat().st_mtime:
        return dst
    need("rubberband")
    # R3 engine (-3), formant preservation (-F); with no time option the duration is unchanged
    run(["rubberband", "-q", "-3", "-F", "-p", f"{semis:g}", str(src), str(dst)])
    return dst


def measure_loudness(path):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-af",
                        "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True)
    j = json.loads(r.stderr[r.stderr.rfind("{"):r.stderr.rfind("}") + 1])
    return j


def make_mix(inst: Path, voc: Path | None, guide: float, out: Path):
    tmp = out.with_suffix(".pre.wav")
    if voc is not None and guide > 0:
        run(["ffmpeg", "-v", "error", "-y", "-i", str(inst), "-i", str(voc), "-filter_complex",
             f"[1:a]volume={guide}[g];[0:a][g]amix=inputs=2:normalize=0:duration=first",
             "-c:a", "pcm_f32le", str(tmp)])
    else:
        shutil.copy(inst, tmp)
    m = measure_loudness(tmp)
    # pass 2: linear gain to -14 LUFS; true-peak limiter keeps <= -1.5 dBTP
    gain = -14.0 - float(m["input_i"])
    run(["ffmpeg", "-v", "error", "-y", "-i", str(tmp), "-af",
         f"volume={gain:.2f}dB,aresample=192000,alimiter=limit={10 ** (-1.6 / 20):.4f}:level=disabled:attack=1:release=60,aresample=44100",
         "-c:a", "pcm_f32le", str(out)])
    tmp.unlink(missing_ok=True)
    return measure_loudness(out)


def background_input(bg: str | None, W, H):
    if bg and Path(bg).exists():
        vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=12:2,"
              f"eq=brightness=-0.18:saturation=0.85,vignette=PI/4")
        return ["-loop", "1", "-framerate", "30", "-i", bg], vf
    color = bg if bg and re.match(r"^#?[0-9a-fA-F]{6}$", bg) else "#14193A"
    color = "0x" + color.lstrip("#")
    return ["-f", "lavfi", "-i", f"color=c={color}:s={W}x{H}:r=30"], "vignette=PI/3.2"


def render(ass: Path, audio: Path, bg, W, H, out: Path, dur: float):
    inp, vf = background_input(bg, W, H)
    ass_arg = str(ass).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
    fonts = str(FONT_DIR).replace(":", "\\:")
    vf = f"{vf},format=yuv420p,ass='{ass_arg}':fontsdir='{fonts}'"
    run(["ffmpeg", "-v", "error", "-y", *inp, "-i", str(audio), "-t", f"{dur:.3f}",
         "-vf", vf, "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "medium", "-crf", "19",
         "-tune", "animation", "-r", "30", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "256k",
         "-movflags", "+faststart", str(out)])


# --------------------------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--audio", required=True)
    ap.add_argument("--lyrics", help="plain text, one sung line per row; blank row = new passage")
    ap.add_argument("--lang", default="auto", choices=["he", "en", "auto"])
    ap.add_argument("--semitones", type=float, default=0.0, help="-1 = half tone down, -2 = whole tone down")
    ap.add_argument("--guide-vocal", type=float, default=0.0, help="0..1 gain of the original vocal (0 = none)")
    ap.add_argument("--bg", default=None, help="background image path or #RRGGBB color")
    ap.add_argument("--formats", default="16x9", help="16x9, 9x16 or 16x9,9x16")
    ap.add_argument("--sep", default="best", help="fast | best | melband | <audio-separator model file>")
    ap.add_argument("--asr-model", default=None, help="faster-whisper model (default by language)")
    ap.add_argument("--max-words", type=int, default=6)
    ap.add_argument("--title", default=None)
    ap.add_argument("--artist", default=None)
    ap.add_argument("--name", default=None, help="output file base name")
    ap.add_argument("--draft-ok", action="store_true", help="render even if lyrics are an unconfirmed transcription")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    for t in ("ffmpeg", "ffprobe"):
        need(t)
    audio = Path(a.audio).resolve()
    if not audio.exists():
        die(f"audio not found: {audio}")
    if not FONT_FILE.exists():
        die(f"font missing: {FONT_FILE}")
    out = Path(a.out).resolve()
    work = out / "work"
    work.mkdir(parents=True, exist_ok=True)
    T = {}
    t0 = time.time()

    mix = prepare(audio, work)
    dur = ffprobe_duration(mix)
    log(f"input {audio.name}: {dur:.1f}s")
    t = time.time(); voc, inst, sep_model = separate(mix, work, a.sep); T["separate_s"] = round(time.time() - t, 1)

    lyrics_text = Path(a.lyrics).read_text(encoding="utf-8") if a.lyrics else None
    lang = a.lang if a.lang != "auto" else detect_lang(lyrics_text, voc)
    rtl = lang == "he"
    asr = a.asr_model or ASR_DEFAULT[lang]
    t = time.time()
    if lyrics_text:
        lyric_lines = parse_lyrics(lyrics_text)
        if not any(lyric_lines):
            die("lyrics file is empty")
        words = align_lyrics(voc, lyric_lines, lang, asr)
        lyrics_source = "supplied"
    else:
        log("no lyrics supplied: transcribing the vocal stem as a DRAFT (never invented, must be confirmed)")
        lyric_lines, words = transcribe_draft(voc, lang, asr, work)
        lyrics_source = "transcribed_unconfirmed"
        unsure = sum(1 for w in words if (w.get("prob") or 0) < 0.5)
        log(f"DRAFT lyrics written: {out / 'lyrics_draft.txt'} ({len(words)} words, {unsure} uncertain marked [?word])")
        if not a.draft_ok:
            log("Send the draft to the user to confirm/correct, then rerun with --lyrics <confirmed file>. "
                "(--draft-ok renders a preview with uncertain words underlined)")
            sys.exit(3)
    T["lyrics_s"] = round(time.time() - t, 1)

    beat = estimate_beat(inst)
    lines = build_lines(lyric_lines, words, a.max_words)
    countins = schedule(lines, beat)
    draft = lyrics_source != "supplied"

    # audio
    t = time.time()
    if a.semitones:
        inst_use = pitch_shift(inst, work / f"instrumental_{a.semitones:+g}st.wav", a.semitones)
        voc_use = pitch_shift(voc, work / f"vocals_{a.semitones:+g}st.wav", a.semitones) if a.guide_vocal > 0 else None
    else:
        inst_use, voc_use = inst, (voc if a.guide_vocal > 0 else None)
    T["pitch_s"] = round(time.time() - t, 1)
    tag = f"{a.semitones:+g}st" if a.semitones else "orig"
    final_audio = work / f"karaoke_mix_{tag}.wav"
    loud = make_mix(inst_use, voc_use, a.guide_vocal, final_audio)
    log(f"mix: {loud['input_i']} LUFS, {loud['input_tp']} dBTP")

    base = a.name or re.sub(r"[^\w֐-׿-]+", "_", audio.stem)[:40]
    outputs = []
    t = time.time()
    for f in [x.strip() for x in a.formats.split(",") if x.strip()]:
        W, H = (1920, 1080) if f == "16x9" else (1080, 1920)
        ass_txt = build_ass(lines, words, countins, W, H, rtl, a.title, a.artist, draft)
        ass_path = out / f"{base}-{f}.ass"
        ass_path.write_text(ass_txt, encoding="utf-8-sig")
        mp4 = out / f"{base}-karaoke-{tag}-{f}{'-DRAFT' if draft else ''}.mp4"
        log(f"rendering {mp4.name} ...")
        render(ass_path, final_audio, a.bg, W, H, mp4, dur)
        outputs.append({"format": f, "mp4": str(mp4), "ass": str(ass_path), "width": W, "height": H})
    T["render_s"] = round(time.time() - t, 1)
    T["total_s"] = round(time.time() - t0, 1)

    timing = {
        "source": str(audio), "duration": round(dur, 3), "lang": lang, "rtl": rtl,
        "lyrics_source": lyrics_source, "semitones": a.semitones, "guide_vocal": a.guide_vocal,
        "separation_model": sep_model, "asr_model": asr, "model_dir": str(MODEL_DIR), "beat_s": round(beat, 3),
        "stems": {"mix": str(mix), "vocals": str(voc), "instrumental": str(inst),
                  "instrumental_used": str(inst_use), "final_audio": str(final_audio)},
        "colors": {"sung": SUNG, "unsung": UNSUNG},
        "loudness": {"lufs": float(loud["input_i"]), "true_peak": float(loud["input_tp"])},
        "words": words,
        "lines": [{k: L[k] for k in ("text", "words", "start", "end", "appear", "disappear", "slot", "section",
                                     "font_size", "width_px") if k in L} for L in lines],
        "countins": countins, "outputs": outputs, "timings_s": T,
        "uncertain_words": [dict(i=i, **w) for i, w in enumerate(words) if (w.get("prob") or 0) < 0.5],
    }
    (out / f"{base}-timing-{tag}.json").write_text(json.dumps(timing, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"done in {T['total_s']}s -> {out}")
    if draft:
        log("DRAFT render (unconfirmed lyrics, uncertain words underlined) - not a deliverable until confirmed.")


if __name__ == "__main__":
    main()
