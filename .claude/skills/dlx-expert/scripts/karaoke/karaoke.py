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
LEAD_MAX = 4.0        # first line of a passage appears at most this long before it is sung
LEAD_NEXT = 8.0       # inside a passage the next line appears as soon as its slot is free (up to this early)
GAP_COUNTIN = 4.0     # silence before a line that triggers count-in dots
ALIGN_VERSION = "hybrid-ctc-11"  # part of the alignment cache key
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
        # a maqaf (Hebrew hyphen) joins two sung words: split for timing, keep it on the first for display
        words = [p for w in line.split() for p in re.findall(r"[^\u05be]+\u05be?|\u05be", w)]
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


# Hebrew -> latin for the MMS aligner (consonantal, like uroman; vowels are absorbed by CTC blanks)
HEB2LAT = {"א": "a", "ב": "b", "ג": "g", "ד": "d", "ה": "h", "ו": "v", "ז": "z", "ח": "h", "ט": "t", "י": "y",
           "כ": "k", "ך": "k", "ל": "l", "מ": "m", "ם": "m", "נ": "n", "ן": "n", "ס": "s", "ע": "a", "פ": "p",
           "ף": "f", "צ": "ts", "ץ": "ts", "ק": "k", "ר": "r", "ש": "sh", "ת": "t"}


NIQQUD = {"\u05b7": "a", "\u05b8": "a", "\u05b2": "a", "\u05b6": "e", "\u05b5": "e", "\u05b1": "e",
          "\u05b4": "i", "\u05b9": "o", "\u05ba": "o", "\u05b3": "o", "\u05bb": "u"}


def romanize(word: str) -> str:
    """latin letters for the MMS aligner. Hebrew: consonants + niqqud vowels when the lyrics have them."""
    w = unicodedata.normalize("NFD", word.lower())
    voweled = any(c in NIQQUD for c in w)
    out = []
    i = 0
    while i < len(w):
        c = w[i]
        marks = ""
        j = i + 1
        while j < len(w) and unicodedata.combining(w[j]):
            marks += w[j]
            j += 1
        if c == "\u05d5" and "\u05bc" in marks and not any(m in NIQQUD for m in marks):
            out.append("u")                      # shuruk
        elif c == "\u05d5" and "\u05b9" in marks:
            out.append("o")                      # holam male
        else:
            vowel = [NIQQUD[m] for m in marks if m in NIQQUD]
            silent = voweled and not vowel and (c in "\u05d0\u05e2" or (c == "\u05d9" and out and out[-1] in ("i", "e")))
            guttural_vowel = voweled and vowel and c in "\u05d0\u05e2"  # alef/ayin carry only their vowel
            out.append("" if silent or guttural_vowel else HEB2LAT.get(c, c if not unicodedata.combining(c) else ""))
            out += vowel
        i = j
    return "".join(ch for ch in "".join(out) if ch in "abcdefghijklmnopqrstuvwxyz'")


def ctc_emissions(y16, model, chunk_s=30.0, ctx_s=1.5):
    """MMS emissions for a whole song: 30 s chunks with 1.5 s context on each side, centre frames kept."""
    import torch
    sr, hop = 16000, 320
    n = y16.shape[1]
    step, ctx = int(chunk_s * sr), int(ctx_s * sr)
    outs = []
    for s0 in range(0, n, step):
        a, b = max(0, s0 - ctx), min(n, s0 + step + ctx)
        with torch.inference_mode():
            em, _ = model(y16[:, a:b])
        f0 = (s0 - a) // hop
        f1 = f0 + (min(n, s0 + step) - s0) // hop
        outs.append(em[0, f0:f1])
    return torch.cat(outs, 0), hop / sr


def ctc_segments(words, line_idx, dur):
    """Where the recogniser reliably found the lyrics (exact matches in runs of >= 3 words, p >= 0.5), its
    times bound each passage, so the CTC aligner cannot drift into an instrumental break. Otherwise one
    segment = the whole song. Returns [(lo, hi, [line, ...])], mode."""
    rel = [w.get("src") == "asr" and (w.get("prob") or 0) >= 0.3 and w.get("run", 0) >= 3 for w in words]
    if sum(rel) < 0.6 * len(words):
        return [(0.0, dur, line_idx)], "full-song"
    # a line is anchored when most of its words were reliably recognised (measured: requiring the first and
    # last word left lines like "Am I gonna..." (p=0.45 on "Am") unanchored, and CTC drifted 4 s there)
    anch = [sum(rel[k] for k in ln) >= 0.6 * len(ln) for ln in line_idx]
    cuts = []  # every boundary between two anchored lines (whisper stretches word ends, so no pause is needed)
    for i in range(len(line_idx) - 1):
        if anch[i] and anch[i + 1]:
            e, s_ = words[line_idx[i][-1]]["end"], words[line_idx[i + 1][0]]["start"]
            cuts.append((i, (e + s_) / 2 if s_ > e else s_))
    segs, start_line, lo = [], 0, 0.0
    for i, t in cuts:
        segs.append((lo, t + 0.4, line_idx[start_line:i + 1]))  # 0.4 s overlap: whisper boundaries are coarse
        start_line, lo = i + 1, t - 0.4
    segs.append((lo, dur, line_idx[start_line:]))
    # an anchored passage gets at most 1.5 s of slack before its first / after its last recognised word
    out = []
    for lo, hi, lines in segs:
        f, l = words[lines[0][0]], words[lines[-1][-1]]
        if rel[lines[0][0]]:
            lo = max(lo, f["start"] - 1.5)
        if rel[lines[-1][-1]]:
            hi = min(hi, l["end"] + 1.5)
        out.append((max(0.0, lo), min(dur, hi), lines))
    return out, "anchored"


def ctc_align(vocals: Path, words, line_idx, work: Path):
    """Word times for SUPPLIED lyrics with a CTC forced aligner (torchaudio MMS_FA, 1100+ languages, ~1.2 GB
    once). Each segment (see ctc_segments) gets its own emissions and Viterbi alignment.
    Returns (words, ok). Words keep their text; only times change."""
    try:
        import torch
        from torchaudio.pipelines import MMS_FA as bundle
    except Exception as e:  # noqa
        log(f"CTC alignment unavailable ({e}); using whisper times")
        return words, False
    t0 = time.time()
    try:
        model = bundle.get_model(with_star=False)
        tok = bundle.get_tokenizer()
        aligner = bundle.get_aligner()
        y = torch.from_numpy(load16k(vocals)).unsqueeze(0)
    except Exception as e:  # noqa
        log(f"CTC alignment failed ({e}); using whisper times")
        return words, False
    dur = y.shape[1] / 16000
    segs, mode = ctc_segments(words, line_idx, dur)
    done = 0
    for lo, hi, lines in segs:
        # no '*' wildcard tokens: measured, a wildcard at a segment edge swallowed a whole sung line (its words
        # were crammed into 0.4 s); CTC blanks already absorb silence and instrumental parts
        seq, owner = [], []
        for ln in lines:
            for k in ln:
                r = romanize(words[k]["text"])
                if r:
                    seq.append(r)
                    owner.append(k)
        if not seq:
            continue
        # emissions computed on THIS segment (+1 s context): measured on a 4-min song, emissions taken from
        # 30 s whole-song chunks crammed a 3-line passage into 3 s; per-segment emissions placed it correctly.
        try:
            a0 = max(0.0, lo - 1.0)
            b0 = min(dur, hi + 1.0)
            em, fr = ctc_emissions(y[:, int(a0 * 16000):int(b0 * 16000)], model)
            f0, f1 = int((lo - a0) / fr), min(em.shape[0], int((hi - a0) / fr))
            if f1 - f0 < len("".join(seq)) + len(seq):
                continue  # window too short for the text: keep recogniser times
            spans = aligner(em[f0:f1], tok(seq))
        except Exception as e:  # noqa
            log(f"CTC segment {lo:.1f}-{hi:.1f}s failed ({e}); keeping recogniser times")
            continue
        for k, sp in zip(owner, spans):
            if k is None or not sp:
                continue
            s_, e_ = lo + sp[0].start * fr, lo + sp[-1].end * fr
            sc = float(sum(t.score * (t.end - t.start) for t in sp) / max(1, sum(t.end - t.start for t in sp)))
            words[k].pop("interpolated", None)
            words[k].update(start=round(s_, 3), end=round(max(e_, s_ + 0.06), 3), ctc_score=round(sc, 3),
                            whisper_start=words[k].get("start") if words[k].get("src") == "asr" else None,
                            whisper_end=words[k].get("end") if words[k].get("src") == "asr" else None,
                            src="ctc")
            done += 1
    # guard: where the recogniser was confident about the exact word (p >= 0.8) and CTC lands > 1 s away (or
    # > 0.3 s with an almost-zero CTC score, typical for a lone "I"), CTC has drifted -> keep the recogniser's
    # time (its own error is 0.3-0.6 s at phrase starts, refined below)
    guarded = 0
    # only where whisper actually covers the lyrics (anchored mode). In full-song mode its few matches are
    # unreliable: measured, a guarded word pulled the last line of Yigdal into 0.2 s.
    for w in (words if mode == "anchored" else []):
        ws_ = w.get("whisper_start")
        far = abs(w["start"] - ws_) > 1.0 if ws_ is not None else False
        weak = ws_ is not None and (w.get("ctc_score") or 0) < 0.05 and abs(w["start"] - ws_) > 0.3
        if ws_ is not None and (w.get("prob") or 0) >= 0.8 and (far or weak):
            w["end"] = round(w["whisper_end"], 3) if w.get("whisper_end") else round(ws_ + 0.3, 3)
            w["start"] = round(ws_, 3)
            w["src"] = "asr-guard"
            guarded += 1
    if guarded:
        log(f"CTC guard: {guarded} words kept the recogniser's time (CTC was far away or unsure)")
    refine_lines(vocals, words, line_idx)
    extend_sustained(vocals, words)
    fix_word_times(words)
    log(f"CTC alignment ({mode}, {len(segs)} segments): {done}/{len(words)} words placed in {time.time() - t0:.0f}s")
    return words, done >= 0.9 * len(words)


def refine_lines(vocals: Path, words, line_idx):
    """Two rules a singer would agree with. (1) A line is sung in one go: a first/last word left > 2.5 s away
    from the rest of its line was misplaced -> put it next to its neighbour. (2) A phrase starts on its attack:
    when a sharp vocal attack (>= 15 dB rise in ~70 ms) lies within -0.8/+1.0 s of a phrase-initial word, the
    word starts there. Measured: both aligners put such words inside the decaying tail of the previous phrase."""
    import numpy as np
    import librosa
    for ln in line_idx:
        if len(ln) >= 2:
            a, b = words[ln[0]], words[ln[1]]
            if b["start"] - a["end"] > 2.5:
                d = min(0.4, a["end"] - a["start"])
                a["start"], a["end"], a["src"] = round(b["start"] - d, 3), round(b["start"], 3), a.get("src", "") + "+line"
            y_, z = words[ln[-2]], words[ln[-1]]
            if z["start"] - y_["end"] > 2.5:
                d = min(0.6, z["end"] - z["start"])
                z["start"], z["end"], z["src"] = round(y_["end"], 3), round(y_["end"] + d, 3), z.get("src", "") + "+line"
    sr, hop = 22050, 256
    fps = sr / hop
    y, _ = librosa.load(str(vocals), sr=sr, mono=True)
    db = 20 * np.log10(librosa.feature.rms(y=y, frame_length=1024, hop_length=hop)[0] + 1e-9)
    ref = np.percentile(db, 95)
    # sharp vocal attacks: >= 15 dB rise within ~70 ms, landing within 15 dB of the song's loud singing
    rise = np.full(len(db), -99.0)
    for k in range(6, len(db)):
        rise[k] = db[k] - db[k - 6:k].min()
    attacks = np.nonzero((rise >= 15) & (db >= ref - 15))[0]
    # keep the first frame of each attack
    attacks = [k for j, k in enumerate(attacks) if j == 0 or k - attacks[j - 1] > 6]
    att_t = np.array([max(0, k - 3) / fps for k in attacks])  # back up to where the rise began
    first = {ln[0] for ln in line_idx}
    moved = 0
    for i, w in enumerate(words):
        cand = i in first or (i and (w["start"] - words[i - 1]["end"] >= 0.25
                                     or re.search(r"[,.;:!?]$", words[i - 1]["text"])))
        if not cand or not len(att_t):
            continue
        lo = max(w["start"] - 0.8, (words[i - 1]["start"] + 0.1) if i else 0.0)
        hi = min(w["start"] + 1.0, w["end"] - 0.05)
        near = att_t[(att_t >= lo) & (att_t <= hi)]
        if not len(near):
            continue
        t = float(near[np.argmin(np.abs(near - w["start"]))])
        if abs(t - w["start"]) <= 0.08:
            continue
        w["start"] = round(t, 3)
        if i and words[i - 1]["end"] > w["start"]:
            words[i - 1]["end"] = round(max(words[i - 1]["start"] + 0.05, w["start"]), 3)
        moved += 1
    if moved:
        log(f"refine: {moved} phrase-initial words moved to the vocal attack")


def trim_silent_tails(vocals: Path, words):
    """A word's highlight must not crawl on after the voice has stopped: for words longer than 1.5 s, the word
    ends where the (smoothed) level stays 15 dB under that word's own peak for >= 0.8 s. Measured: CTC stretched
    the last word of Yigdal over a 26 s outro where the vocal stem only holds bleed 15-20 dB down."""
    import numpy as np
    import librosa
    from scipy.ndimage import uniform_filter1d
    sr, hop = 22050, 256
    fps = sr / hop
    y, _ = librosa.load(str(vocals), sr=sr, mono=True)
    db = uniform_filter1d(20 * np.log10(librosa.feature.rms(y=y, frame_length=1024, hop_length=hop)[0] + 1e-9),
                          int(0.3 * fps))
    need = int(0.8 * fps)
    n = 0
    for w in words:
        if w["end"] - w["start"] <= 1.5:
            continue
        a, b = int(w["start"] * fps), min(len(db), int(w["end"] * fps))
        peak = db[a:min(b, a + int(3 * fps))].max()
        run = 0
        for k in range(a + int(0.3 * fps), b):
            run = run + 1 if db[k] < peak - 15 else 0
            if run >= need:
                w["end"] = round(max(w["start"] + 0.3, (k - run + 1) / fps), 3)
                n += 1
                break
    if n:
        log(f"trim: {n} long words ended where the voice stops (no highlight crawling through silence)")


def extend_sustained(vocals: Path, words):
    """CTC marks a word where its letters are recognised; a held note goes on after that. Extend each word's
    end while the voice is still sounding (level within 15 dB of the word's peak), up to the next word."""
    import numpy as np
    import librosa
    sr, hop = 22050, 256
    y, _ = librosa.load(str(vocals), sr=sr, mono=True)
    db = 20 * np.log10(librosa.feature.rms(y=y, frame_length=1024, hop_length=hop)[0] + 1e-9)
    fps = sr / hop
    for i, w in enumerate(words):
        nxt = words[i + 1]["start"] if i + 1 < len(words) else w["end"] + 2.0
        a, b = int(w["start"] * fps), int(w["end"] * fps)
        if b <= a or b >= len(db):
            continue
        peak = db[a:b + 1].max()
        k = b
        lim = int(min(nxt - 0.04, w["end"] + 4.0) * fps)
        while k < lim and k < len(db) and db[k] > peak - 15:
            k += 1
        w["end"] = round(max(w["end"], min(k / fps, nxt - 0.04)), 3)
        if 0 < nxt - w["end"] < 0.25:  # tiny gap: keep the word lit until the next one starts
            w["end"] = round(nxt, 3)


def asr_words(vocals: Path, lang: str, asr: str, work: Path):
    """Word-timestamped transcription of the VOCAL stem (cached). faster-whisper directly: its bundled
    Silero VAD (ONNX, no download) skips instrumental parts, and condition_on_previous_text=False stops the
    "Thank you." loop whisper produces on long silences."""
    cache = work / f"asr_{re.sub(r'[^A-Za-z0-9]+', '_', asr)}_{lang}.json"
    if cache.exists() and cache.stat().st_mtime > vocals.stat().st_mtime:
        return json.loads(cache.read_text(encoding="utf-8"))
    from faster_whisper import WhisperModel
    model = WhisperModel(asr, device="cpu", compute_type="int8", cpu_threads=max(1, os.cpu_count() or 1))
    t0 = time.time()
    segs, _ = model.transcribe(load16k(vocals), language=lang, word_timestamps=True, vad_filter=True,
                               beam_size=5, condition_on_previous_text=False)
    out = [{"text": w.word.strip(), "start": round(w.start, 3), "end": round(w.end, 3),
            "prob": round(float(w.probability), 3)} for s_ in segs for w in (s_.words or []) if w.word.strip()]
    log(f"transcribed vocal stem in {time.time() - t0:.0f}s ({len(out)} words)")
    cache.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out


def local_align(vocals_16k, text, lang, asr, t0, t1, model_box):
    """stable-ts forced alignment on a SHORT clip (no long silences to confuse it). -> [(s,e,p)] or None"""
    try:
        if model_box.get("m") is None:
            model_box["m"] = load_asr(asr)
        a, b = int(max(0, t0) * 16000), int(t1 * 16000)
        res = model_box["m"].align(vocals_16k[a:b], text, language=lang)
        if res is None:
            return None
        ws = [w for w in res.all_words() if norm_chars(w.word)]
        return [(max(0, t0) + w.start, max(0, t0) + w.end, float(getattr(w, "probability", 0) or 0)) for w in ws]
    except Exception as e:  # noqa
        log(f"local alignment failed ({e}); interpolating")
        return None


def align_lyrics(vocals: Path, lines, lang: str, asr: str, work: Path, local: bool = True):
    """Supplied lyrics -> word times. 1) transcribe the vocal stem with word timestamps; 2) sequence-match
    lyric words to recognised words (equal / substituted words take the recognised times); 3) runs of
    lyric words the recogniser missed are force-aligned on the short clip between their anchors
    (stable-ts), or spread / interpolated. Words always come from the lyrics - only times come from audio."""
    import difflib
    flat = [w for ln in lines if ln for w in ln]
    rec = asr_words(vocals, lang, asr, work)
    if not rec:
        die("no singing recognised in the vocal stem")
    A = [norm_chars(w) for w in flat]
    B = [norm_chars(w["text"]) for w in rec]
    words = [{"text": w, "start": None, "end": None, "prob": None, "src": None} for w in flat]
    sm = difflib.SequenceMatcher(None, A, B, autojunk=False)
    gaps = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal" or (op == "replace" and i2 - i1 == j2 - j1):
            for k in range(i2 - i1):
                r = rec[j1 + k]
                words[i1 + k].update(start=r["start"], end=r["end"], prob=r["prob"], run=i2 - i1,
                                     src="asr" if op == "equal" else "asr-substituted")
        elif op in ("replace", "delete"):
            gaps.append((i1, i2, j1, j2))
    n_eq = sum(1 for w in words if w["src"] == "asr")
    n_sub = sum(1 for w in words if w["src"] == "asr-substituted")
    log(f"lyrics vs recognised words: {n_eq}/{len(words)} exact, {n_sub} substituted, {len(gaps)} gaps")
    y16 = load16k(vocals) if gaps and local else None
    box = {}
    for i1, i2, j1, j2 in gaps:
        prev_t = next((words[k]["end"] for k in range(i1 - 1, -1, -1) if words[k]["end"] is not None), 0.0)
        next_t = next((words[k]["start"] for k in range(i2, len(words)) if words[k]["start"] is not None), None)
        if next_t is None:
            next_t = (rec[j2 - 1]["end"] + 1.0) if j2 > j1 else prev_t + 0.6 * (i2 - i1) + 1.0
        got = None
        if local and 0.3 < next_t - prev_t < 40:
            got = local_align(y16, " ".join(flat[i1:i2]), lang, asr, prev_t - 0.1, next_t + 0.1, box)
        if got and len(got) == i2 - i1:
            for k, (s_, e_, p_) in enumerate(got):
                words[i1 + k].update(start=max(prev_t, s_), end=min(next_t, max(e_, s_ + 0.05)),
                                     prob=round(p_, 3), src="local-align")
        elif j2 > j1:  # spread the recognised span over the lyric words (by length)
            t0, t1 = rec[j1]["start"], rec[j2 - 1]["end"]
            lens = [max(1, len(A[k])) for k in range(i1, i2)]
            acc = 0
            for k, n in enumerate(lens):
                a = t0 + (t1 - t0) * acc / sum(lens)
                acc += n
                words[i1 + k].update(start=a, end=t0 + (t1 - t0) * acc / sum(lens), prob=0.0, src="spread")
        # else: left None -> interpolated by fix_word_times
    fix_word_times(words)
    for w in words:
        if w.get("interpolated"):
            w["src"] = "interpolated"
    return words


def transcribe_draft(vocals: Path, lang: str, asr: str, work: Path):
    allw = asr_words(vocals, lang, asr, work)
    lines, words, cur = [], [], []
    for w in allw:
        if words and (w["start"] - words[-1]["end"] > 0.8 or re.search(r"[,.?!]$", words[-1]["text"])):
            if cur:
                lines.append(cur)
                cur = []
            if w["start"] - words[-1]["end"] > GAP_COUNTIN:
                lines.append(None)
        cur.append(w["text"])
        words.append(dict(w))
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
    # one word over the limit and no natural break inside (comma / pause): splitting would cut a phrase in
    # half ("I'm not gonna / work at this time") - keep it whole; the font shrinks to fit if needed
    if len(words_idx) == max_words + 1:
        inner = words_idx[1:-2]  # break points that leave >= 2 words on each side (no orphan "no")
        punct = any(re.search(r"[,.;:!?]$", words[j]["text"]) for j in inner)
        # only a real rest splits a phrase (a held note / breath inside it does not: critic round 3 caught
        # "I'm not" / "gonna work it with you" shown as two lines, read bottom-to-top)
        pause = any(words[b]["start"] - words[a]["end"] > 1.5 for a, b in zip(words_idx[1:-2], words_idx[2:-1]))
        if not punct and not pause:
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
        L["text"] = join_words(words[j]["text"] for j in L["words"])
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
        appear = L["start"] - (LEAD_MAX if L.get("countin") else LEAD_NEXT)
        if L.get("countin"):
            ci = next(c for c in countins if c["line"] == i)
            appear = min(appear, ci["start"]) if ci["start"] > appear else ci["start"] - 0.5
            appear = max(appear, L["start"] - LEAD_MAX - 0.5)
        # one line per slot at any time: wait for the previous line in this slot to leave; if that is too late
        # (fast singing), cut the previous line short - it is already fully sung (the other slot lies between).
        prev_same = next((lines[j] for j in range(i - 1, -1, -1) if lines[j]["slot"] == L["slot"]), None)
        if prev_same is not None:
            appear = max(appear, prev_same["disappear"] + 0.04)
        if i and L.get("countin"):
            appear = max(appear, lines[i - 1]["disappear"] + 0.04)
        appear = max(0.0, min(appear, L["start"] - 0.25))
        if prev_same is not None:
            appear = max(appear, prev_same["end"] + 0.06)  # never before the old line is sung
            prev_same["disappear"] = round(min(prev_same["disappear"], appear - 0.04), 3)
        if i:  # reading order: a line never appears before the line that is sung before it
            appear = max(appear, lines[i - 1]["appear"] + 0.3)
            appear = min(appear, L["start"] - 0.25) if appear > L["start"] - 0.25 else appear
        L["appear"] = round(appear, 3)
        L["disappear"] = round(max(L["disappear"], L["end"] + 0.05), 3)
    # hard guarantee (QA re-checks it in the .ass): no two lines share a slot at the same time
    for i, L in enumerate(lines):
        nxt = next((M for M in lines[i + 1:] if M["slot"] == L["slot"]), None)
        if nxt is not None and L["disappear"] > nxt["appear"] - 0.02:
            L["disappear"] = round(max(L["end"], nxt["appear"] - 0.04), 3)
    return countins


def global_lag(vocals: Path, words) -> float:
    """seconds the word starts are LATE (+) / EARLY (-) vs. the vocal onset envelope (cross-correlation)."""
    import numpy as np
    import librosa
    sr, hop = 22050, 256
    fps = sr / hop
    y, _ = librosa.load(str(vocals), sr=sr, mono=True)
    env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop)
    n = len(env)
    imp = np.zeros(n)
    for w in words:
        k = int(round(w["start"] * fps))
        if 0 <= k < n:
            imp[k] = 1
    imp = np.convolve(imp, np.exp(-0.5 * (np.arange(-6, 7) / 2.0) ** 2), "same")
    e = (env - env.mean()) / (env.std() + 1e-9)
    L = int(0.5 * fps)
    xc = [np.dot(imp[max(0, -l):n - max(0, l)], e[max(0, l):n - max(0, -l)]) for l in range(-L, L + 1)]
    return -(int(np.argmax(xc)) - L) / fps


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


def join_words(texts):
    """display join: a word ending in a maqaf (Hebrew hyphen) is glued to the next word, like in print"""
    out = ""
    for t in texts:
        out += t if (not out or out.endswith("\u05be")) else " " + t
    return out


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


def key_label(semis: float, rtl: bool) -> str:
    """'Karaoke · original key' / 'קריוקי · חצי טון למטה' - what a singer needs to know on the title card."""
    if not semis:
        return "קריוקי · טונליות מקורית" if rtl else "Karaoke · original key"
    n, up = abs(semis), semis > 0
    if rtl:
        words_he = {1: "חצי טון", 2: "טון", 3: "טון וחצי", 4: "שני טונים"}
        amt = words_he.get(int(n), f"{n:g} חצאי טונים") if float(n).is_integer() else f"{n:g} חצאי טונים"
        return f"קריוקי · {amt} {'למעלה' if up else 'למטה'}"
    unit = "semitone" if n == 1 else "semitones"
    step = {1: " (half step)", 2: " (whole step)"}.get(int(n), "") if float(n).is_integer() else ""
    return f"Karaoke · {n:g} {unit} {'up' if up else 'down'}{step}"


def build_ass(lines, words, countins, W, H, rtl, title, artist, draft, semis=0.0, dur=None, credit=None):
    vertical = H > W
    base_fs = 124 if not vertical else 100  # cap height ~75 px at 1080p (critic: 86 and 108 still small)
    max_w = W * (0.88 if not vertical else 0.90)
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
Style: Sub,{FONT_NAME},{int(base_fs * 0.75)},{ass_color('#C9D2E8')},{ass_color('#C9D2E8')},{ass_color(OUTLINE)},{ass_color('#000000', 0x80)},0,0,0,0,100,100,0,0,1,3,1,5,0,0,0,-1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev = []
    boxes = []  # (kind, start, end, x0, y0, x1, y1) - written to timing.json, QA checks overlaps
    cx = W / 2
    geo = []
    fmt = f"{W}x{H}"
    for L in lines:
        txt = join_words(words[j]["text"] for j in L["words"])
        fs = base_fs
        while meas.width(txt, fs) > max_w and fs > 40:
            fs -= 2
        wpx = round(meas.width(txt, fs))
        y = ys[L["slot"]]
        geo.append((fs, y, wpx))
        L.setdefault("geo", {})[fmt] = {"font_size": fs, "width_px": wpx, "x": round(cx), "y": round(y)}
        boxes.append(("lyric", L["appear"], L["disappear"], cx - wpx / 2, y - fs * 0.55, cx + wpx / 2, y + fs * 0.55))
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
                sep = "" if words[L["words"][n - 1]]["text"].endswith("\u05be") else " "
                parts.append(f"{{\\k{max(0, gap_cs)}}}{sep}")
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
        fade = "{\\fad(180,220)}" if L["appear"] > 0.05 else "{\\fad(0,220)}"
        ev.append(f"Dialogue: 1,{ass_time(L['appear'])},{ass_time(L['disappear'])},Lyric,,0,0,0,,"
                  f"{fade}{{\\an5\\pos({cx:.0f},{y:.0f})\\fs{fs}}}{body}")
    # count-in dots: above the upcoming line, on the side where reading starts
    for c in countins:
        L = lines[c["line"]]
        fs, y, wpx = geo[c["line"]]
        half = wpx / 2
        x = cx + half - fs * 0.6 if rtl else cx - half + fs * 0.6
        dy = y - fs * 0.95
        an = 6 if rtl else 4  # anchor right (RTL) / left (LTR)
        for k in range(c["dots"], 0, -1):
            a = c["end"] - k * c["beat"]
            b = a + c["beat"]
            dots = " ".join(["●"] * k)
            dw = fs * 0.5 * (1.4 * k)
            boxes.append(("dots", a, b, x - dw if rtl else x, dy - fs * 0.3, x if rtl else x + dw, dy + fs * 0.3))
            ev.append(f"Dialogue: 2,{ass_time(a)},{ass_time(b)},Dots,,0,0,0,,{{\\an{an}\\pos({x:.0f},{dy:.0f})}}{dots}")
    # title card from frame 0 (a karaoke video must never open on an empty frame: it is also the thumbnail)
    if title and lines:
        end = max(lines[0]["appear"] - 0.05, 0.8)
        ty = H * 0.30  # above both lyric slots, so it never collides with the first line
        tfs = base_fs * 1.7
        while meas.width(title, tfs) > max_w and tfs > 40:
            tfs -= 2
        tw = meas.width(title, tfs)
        boxes.append(("title", 0.0, end, cx - tw / 2, ty - tfs * 0.65, cx + tw / 2, ty + tfs * 0.65))
        rt = RLM if HEB_RE.search(title) else ""
        ev.append(f"Dialogue: 0,{ass_time(0.0)},{ass_time(end)},Title,,0,0,0,,"
                  f"{{\\fad(0,400)\\an5\\pos({cx:.0f},{ty:.0f})\\fs{tfs:.0f}}}{rt}{esc(title)}")
        sy = ty + base_fs * 1.35
        def fit(t, f0):
            while meas.width(t, f0) > max_w and f0 > 24:
                f0 -= 1
            return f0
        if artist:
            ra = RLM if HEB_RE.search(artist) else ""
            ev.append(f"Dialogue: 0,{ass_time(0.0)},{ass_time(end)},Sub,,0,0,0,,"
                      f"{{\\fad(0,400)\\an5\\pos({cx:.0f},{sy:.0f})\\fs{fit(artist, base_fs * 0.75):.0f}}}{ra}{esc(artist)}")
            sy += base_fs * 1.0
        kl = key_label(semis, rtl)
        ev.append(f"Dialogue: 0,{ass_time(0.0)},{ass_time(end)},Sub,,0,0,0,,"
                  f"{{\\fad(0,400)\\an5\\pos({cx:.0f},{sy:.0f})\\fs{fit(kl, base_fs * 0.75):.0f}\\1c&H{ass_color(SUNG)[4:]}&}}{RLM if rtl else ''}{kl}")
        kw = meas.width(kl, fit(kl, base_fs * 0.75))
        boxes.append(("title", 0.0, end, cx - kw / 2, sy - base_fs * 0.4, cx + kw / 2, sy + base_fs * 0.4))
    def bar(a, b, y):
        """a thin bar that shrinks to nothing between a and b: shows the music is running and when it ends"""
        bw = W * 0.30
        ms = int((b - a) * 1000)
        ev.append(f"Dialogue: 0,{ass_time(a)},{ass_time(b)},Sub,,0,0,0,,{{\\fad(300,300)\\an5\\pos({cx:.0f},{y:.0f})"
                  f"\\bord0\\shad0\\1c&H{ass_color(SUNG)[4:]}&\\1a&H30&\\t(0,{ms},\\fscx0)\\p1}}"
                  f"m 0 0 l {bw:.0f} 0 l {bw:.0f} 8 l 0 8{{\\p0}}")
        boxes.append(("bar", a, b, cx - bw / 2, y - 6, cx + bw / 2, y + 6))

    # long intro: the title card gets a bar counting down to the first entry
    if title and lines and lines[0]["appear"] > 8.0:
        bar(0.0, lines[0]["appear"] - 0.05, H * 0.30 + base_fs * 3.3)

    # instrumental breaks: never a dead screen. A label and a bar that shrinks to the next entry.
    lab = "\u266a מעבר מוזיקלי \u266a" if rtl else "\u266a Instrumental \u266a"
    by = H * (0.70 if not vertical else 0.52)
    for i in range(1, len(lines)):
        a = lines[i - 1]["disappear"] + 0.3
        b = lines[i]["appear"] - 0.2
        if b - a < 5.0:
            continue
        ms = int((b - a) * 1000)
        lw = meas.width(lab, base_fs * 0.75)
        ev.append(f"Dialogue: 0,{ass_time(a)},{ass_time(b)},Sub,,0,0,0,,{{\\fad(300,300)\\an5\\pos({cx:.0f},{by - base_fs * 0.5:.0f})}}"
                  f"{RLM if rtl else ''}{lab}")
        bw = W * 0.30
        ev.append(f"Dialogue: 0,{ass_time(a)},{ass_time(b)},Sub,,0,0,0,,{{\\fad(300,300)\\an5\\pos({cx:.0f},{by + base_fs * 0.35:.0f})"
                  f"\\bord0\\shad0\\1c&H{ass_color(SUNG)[4:]}&\\1a&H30&\\t(0,{ms},\\fscx0)\\p1}}"
                  f"m 0 0 l {bw:.0f} 0 l {bw:.0f} 8 l 0 8{{\\p0}}")
        boxes.append(("break", a, b, cx - max(lw, bw) / 2, by - base_fs * 0.95, cx + max(lw, bw) / 2, by + base_fs * 0.5))
    # end card over the outro (title, artist, key, credit) instead of a blank screen
    if dur and lines and dur - lines[-1]["disappear"] > 3.0:
        a = lines[-1]["disappear"] + 0.3
        ty2 = H * 0.36
        tfs2 = base_fs * 1.4
        while meas.width(title or "", tfs2) > max_w and tfs2 > 40:
            tfs2 -= 2
        rows = [("Title", title, tfs2), ("Sub", artist, None), ("Sub", key_label(semis, rtl), None), ("Sub", credit, None)]
        y_ = ty2
        top = ty2 - tfs2 * 0.6
        right = 0.0
        for st, txt, fs_ in rows:
            if not txt:
                continue
            fs_ = fs_ or (base_fs * 0.5 if txt == credit else base_fs * 0.75)
            while meas.width(txt, fs_) > max_w and fs_ > 24:  # every row fits the frame (critic: 9:16 credit ran off)
                fs_ -= 1
            right = max(right, meas.width(txt, fs_) / 2)
            extra = f"\\fs{fs_:.0f}"
            col = f"\\1c&H{ass_color(SUNG)[4:]}&" if txt == key_label(semis, rtl) else ""
            small = ""
            rl = RLM if HEB_RE.search(txt) else ""
            ev.append(f"Dialogue: 0,{ass_time(a)},{ass_time(dur)},{st},,0,0,0,,{{\\fad(500,800)\\an5\\pos({cx:.0f},{y_:.0f}){extra}{col}{small}}}{rl}{esc(txt)}")
            y_ += fs_ * 1.2
        boxes.append(("end", a, dur, cx - right, top, cx + right, y_))
        bar(a, dur, y_ + base_fs * 0.5)
    return hdr + "\n".join(ev) + "\n", [dict(kind=b[0], start=round(b[1], 3), end=round(b[2], 3),
                                              box=[round(v) for v in b[3:]]) for b in boxes]


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
    # pass 2: linear gain to -14 LUFS; limiter at 192 kHz to -2.3 dB so the AAC encode stays <= -1 dBTP
    gain = -14.0 - float(m["input_i"])
    run(["ffmpeg", "-v", "error", "-y", "-i", str(tmp), "-af",
         f"volume={gain:.2f}dB,aresample=192000,alimiter=limit={10 ** (-2.3 / 20):.4f}:level=disabled:attack=1:release=60,aresample=44100",
         "-c:a", "pcm_f32le", str(out)])
    tmp.unlink(missing_ok=True)
    return measure_loudness(out)


def background_input(bg: str | None, W, H):
    if bg and Path(bg).exists():
        vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=12:2,"
              f"eq=brightness=-0.18:saturation=0.85,vignette=PI/4")
        return ["-loop", "1", "-framerate", "30", "-i", bg], vf
    if bg and re.match(r"^#?[0-9a-fA-F]{6}$", bg):
        return ["-f", "lavfi", "-i", f"color=c=0x{bg.lstrip('#')}:s={W}x{H}:r=30"], "vignette=PI/3.2"
    # default: a slowly drifting deep gradient (never a dead static frame), light noise against banding
    return (["-f", "lavfi", "-i", f"gradients=s={W}x{H}:c0=0x101633:c1=0x2a1745:c2=0x0d2a3a:nb_colors=3:"
             f"x0=0:y0=0:x1={W}:y1={H}:speed=0.004:rate=30"], "vignette=PI/4,noise=alls=3:allf=t")


def render(ass: Path, audio: Path, bg, W, H, out: Path, dur: float):
    inp, vf = background_input(bg, W, H)
    ass_arg = str(ass).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
    fonts = str(FONT_DIR).replace(":", "\\:")
    vf = f"{vf},format=yuv420p,ass='{ass_arg}':fontsdir='{fonts}'"
    run(["ffmpeg", "-v", "error", "-y", *inp, "-i", str(audio), "-t", f"{dur:.3f}",
         "-vf", vf, "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "medium", "-crf", "19",
         "-tune", "animation", "-r", "30", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "256k",
         "-movflags", "+faststart", str(out)])
    # AAC can overshoot the WAV's true peak by 1-2 dB (measured +1.8 dB on a pitch-shifted mix): measure the
    # MP4 itself and, if needed, re-limit the mix with a lower ceiling (loudness ~unchanged, only peaks) and
    # re-encode the audio (video stream copied)
    ceiling = -2.3
    for _ in range(4):
        tp = float(measure_loudness(out)["input_tp"])
        if tp <= -1.2:
            break
        ceiling -= (tp + 1.4)
        tmp = out.with_name(out.stem + ".fix.mp4")
        run(["ffmpeg", "-v", "error", "-y", "-i", str(out), "-i", str(audio), "-map", "0:v", "-map", "1:a",
             "-c:v", "copy", "-af",
             f"aresample=192000,alimiter=limit={10 ** (ceiling / 20):.4f}:level=disabled:attack=1:release=60,"
             "aresample=44100", "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", str(tmp)])
        tmp.replace(out)
        log(f"AAC true peak was {tp:.2f} dBTP -> re-limited the mix at {ceiling:.2f} dB and re-encoded the audio")


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
    ap.add_argument("--credit", default=None, help="one small line on the end card, e.g. the license credit")
    ap.add_argument("--name", default=None, help="output file base name")
    ap.add_argument("--align-only", action="store_true", help="stop after timing (no pitch/mix/render): fast timing check")
    ap.add_argument("--no-ctc", action="store_true", help="skip MMS_FA forced alignment (whisper word times only)")
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
    ctc_ok = False
    if lyrics_text:
        lyric_lines = parse_lyrics(lyrics_text)
        if not any(lyric_lines):
            die("lyrics file is empty")
        # cached per (lyrics, vocal stem, aligner): changing the key or the format does not re-align
        import hashlib
        key = hashlib.sha1((lyrics_text + str(voc.stat().st_mtime) + asr + str(a.no_ctc) + ALIGN_VERSION)
                           .encode()).hexdigest()[:12]
        cache = work / f"alignment_{key}.json"
        if cache.exists():
            c = json.loads(cache.read_text(encoding="utf-8"))
            words, ctc_ok = c["words"], c["ctc_ok"]
            log(f"alignment from cache ({cache.name})")
        else:
            # whisper first (fallback + independent cross-check), then CTC over the whole song (primary)
            words = align_lyrics(voc, lyric_lines, lang, asr, work, local=a.no_ctc)
            k = 0
            line_idx = []
            for ln in lyric_lines:
                if ln:
                    line_idx.append(list(range(k, k + len(ln))))
                    k += len(ln)
            words, ctc_ok = (ctc_align(voc, words, line_idx, work) if not a.no_ctc else (words, False))
            cache.write_text(json.dumps({"words": words, "ctc_ok": ctc_ok}, ensure_ascii=False), encoding="utf-8")
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

    # constant offset of the recogniser's word timestamps (whisper tends to be a little late): measured
    # against the vocal onsets and removed (clamped to +-200 ms). qa_karaoke.py re-measures per line.
    if lyrics_text:
        trim_silent_tails(voc, words)
    lag = global_lag(voc, words)
    # whisper-only timing: remove its constant offset; CTC timing is already frame-accurate -> report only
    corr = 0.0 if ctc_ok else (max(-0.2, min(0.2, lag)) if abs(lag) > 0.02 else 0.0)
    log(f"sync: onset cross-correlation lag {lag * 1000:+.0f} ms ({'CTC timing, no correction' if ctc_ok else 'whisper timing'})")
    if corr:
        for w in words:
            w["start"] = round(max(0.0, w["start"] - corr), 3)
            w["end"] = round(max(w["start"] + 0.08, w["end"] - corr), 3)
        log(f"sync: removed a constant {corr * 1000:+.0f} ms offset (measured {lag * 1000:+.0f} ms)")
    beat = estimate_beat(inst)
    lines = build_lines(lyric_lines, words, a.max_words)
    countins = schedule(lines, beat)
    draft = lyrics_source != "supplied"

    # audio
    t = time.time()
    if a.align_only:
        tag = "align"
        base = a.name or re.sub(r"[^\w\u0590-\u05FF-]+", "_", audio.stem)[:40]
        timing = {"source": str(audio), "duration": round(dur, 3), "lang": lang, "rtl": rtl,
                  "lyrics_source": lyrics_source, "semitones": 0, "ctc_refined": bool(ctc_ok),
                  "measured_lag_ms": round(lag * 1000), "beat_s": round(beat, 3),
                  "stems": {"mix": str(mix), "vocals": str(voc), "instrumental": str(inst),
                            "instrumental_used": str(inst)},
                  "colors": {"sung": SUNG, "unsung": UNSUNG}, "words": words,
                  "lines": [{k: L[k] for k in ("text", "words", "start", "end", "appear", "disappear", "slot")}
                            for L in lines], "countins": countins, "outputs": []}
        p_ = out / f"{base}-timing-align.json"
        p_.write_text(json.dumps(timing, ensure_ascii=False, indent=1), encoding="utf-8")
        log(f"--align-only: timing written to {p_} (check: qa_karaoke.py {p_.name} --skip bleed,pitch,loudness,layout,frames)")
        return
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
    if not a.title:
        a.title = re.sub(r"[_-]+", " ", audio.stem).strip()[:60]
    outputs = []
    t = time.time()
    for f in [x.strip() for x in a.formats.split(",") if x.strip()]:
        W, H = (1920, 1080) if f == "16x9" else (1080, 1920)
        ass_txt, boxes = build_ass(lines, words, countins, W, H, rtl, a.title, a.artist, draft, a.semitones,
                                   dur=dur, credit=a.credit)
        ass_path = out / f"{base}-{f}.ass"
        ass_path.write_text(ass_txt, encoding="utf-8-sig")
        mp4 = out / f"{base}-karaoke-{tag}-{f}{'-DRAFT' if draft else ''}.mp4"
        log(f"rendering {mp4.name} ...")
        render(ass_path, final_audio, a.bg, W, H, mp4, dur)
        outputs.append({"format": f, "mp4": str(mp4), "ass": str(ass_path), "width": W, "height": H, "boxes": boxes})
    T["render_s"] = round(time.time() - t, 1)
    T["total_s"] = round(time.time() - t0, 1)

    timing = {
        "source": str(audio), "duration": round(dur, 3), "lang": lang, "rtl": rtl,
        "lyrics_source": lyrics_source, "semitones": a.semitones, "guide_vocal": a.guide_vocal,
        "separation_model": sep_model, "asr_model": asr, "sync_correction_ms": round(corr * 1000), "measured_lag_ms": round(lag * 1000), "ctc_refined": bool(ctc_ok), "model_dir": str(MODEL_DIR), "beat_s": round(beat, 3),
        "stems": {"mix": str(mix), "vocals": str(voc), "instrumental": str(inst),
                  "instrumental_used": str(inst_use), "final_audio": str(final_audio)},
        "colors": {"sung": SUNG, "unsung": UNSUNG},
        "loudness": {"lufs": float(loud["input_i"]), "true_peak": float(loud["input_tp"])},
        "words": words,
        "lines": [{k: L[k] for k in ("text", "words", "start", "end", "appear", "disappear", "slot", "section",
                                     "geo") if k in L} for L in lines],
        "countins": countins, "outputs": outputs, "timings_s": T,
        "uncertain_words": [dict(i=i, **w) for i, w in enumerate(words) if (w.get("prob") or 0) < 0.5],
    }
    (out / f"{base}-timing-{tag}.json").write_text(json.dumps(timing, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"done in {T['total_s']}s -> {out}")
    if draft:
        log("DRAFT render (unconfirmed lyrics, uncertain words underlined) - not a deliverable until confirmed.")


if __name__ == "__main__":
    main()
