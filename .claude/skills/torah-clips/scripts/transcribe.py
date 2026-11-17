#!/usr/bin/env python3
"""Transcribe Hebrew lesson audio with word-level timestamps.

Usage: transcribe.py <audio.wav> <workdir> [--model MODEL] [--device cpu|cuda]

Outputs in <workdir>:
  words.json      [{"w": word, "s": start, "e": end}, ...]
  segments.json   [{"s": start, "e": end, "text": ...}, ...]
  transcript.txt  "[hh:mm:ss.s] text" lines, broken at pauses / sentence ends
"""
import argparse
import json
import os
import subprocess
import sys
import time

DEFAULT_MODEL = "ivrit-ai/whisper-large-v3-turbo-ct2"


def ensure_faster_whisper():
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "faster-whisper"])


def ts(sec: float) -> str:
    h = int(sec // 3600)
    m = int(sec % 3600 // 60)
    s = sec % 60
    return f"{h:02d}:{m:02d}:{s:04.1f}"


def build_lines(words, pause=0.7, max_len=160):
    """Group words into readable lines, breaking at pauses or sentence ends."""
    lines, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        text_len = sum(len(x["w"]) + 1 for x in cur)
        nxt = words[i + 1] if i + 1 < len(words) else None
        gap = (nxt["s"] - w["e"]) if nxt else 99
        ends_sentence = w["w"].rstrip().endswith((".", "?", "!"))
        if gap >= pause or (ends_sentence and text_len > 40) or text_len >= max_len:
            lines.append(cur)
            cur = []
    if cur:
        lines.append(cur)
    return lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("workdir")
    ap.add_argument("--model", default=os.environ.get("TORAH_CLIPS_MODEL", DEFAULT_MODEL))
    ap.add_argument("--device", default="auto")
    ap.add_argument("--glossary-prompt", default="שיעור תורה. הקדוש ברוך הוא, הגמרא, רש\"י, הרמב\"ם, קל וחומר, הווה אמינא.")
    args = ap.parse_args()

    ensure_faster_whisper()
    from faster_whisper import WhisperModel

    device = args.device
    if device == "auto":
        try:
            import ctranslate2
            device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
        except Exception:
            device = "cpu"
    compute = "float16" if device == "cuda" else "int8"
    print(f"loading {args.model} on {device}/{compute}", flush=True)
    model = WhisperModel(args.model, device=device, compute_type=compute,
                         cpu_threads=os.cpu_count() or 4)

    # Decode with ffmpeg ourselves (avoids PyAV version incompatibilities).
    import numpy as np
    raw = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", args.audio,
                          "-f", "f32le", "-ac", "1", "-ar", "16000", "-"],
                         check=True, capture_output=True).stdout
    audio = np.frombuffer(raw, dtype=np.float32)

    t0 = time.time()
    segments, info = model.transcribe(
        audio, language="he", word_timestamps=True, vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
        initial_prompt=args.glossary_prompt, beam_size=5,
        condition_on_previous_text=False,
    )
    words, segs = [], []
    for seg in segments:
        segs.append({"s": round(seg.start, 2), "e": round(seg.end, 2), "text": seg.text.strip()})
        for w in seg.words or []:
            t = w.word.strip()
            if t:
                words.append({"w": t, "s": round(w.start, 2), "e": round(w.end, 2)})
        print(f"\r{ts(seg.end)} / {ts(info.duration)}", end="", flush=True)
    print(f"\ndone in {time.time() - t0:.0f}s, {len(words)} words", flush=True)

    os.makedirs(args.workdir, exist_ok=True)
    with open(os.path.join(args.workdir, "words.json"), "w", encoding="utf-8") as f:
        json.dump(words, f, ensure_ascii=False)
    with open(os.path.join(args.workdir, "segments.json"), "w", encoding="utf-8") as f:
        json.dump(segs, f, ensure_ascii=False, indent=0)
    with open(os.path.join(args.workdir, "transcript.txt"), "w", encoding="utf-8") as f:
        for line in build_lines(words):
            f.write(f"[{ts(line[0]['s'])}] {' '.join(x['w'] for x in line)}\n")


if __name__ == "__main__":
    main()
