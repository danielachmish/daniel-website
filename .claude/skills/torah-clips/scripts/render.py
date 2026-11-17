#!/usr/bin/env python3
"""Render clips from clips.json into finished videos with Hebrew captions.

Usage: render.py <workdir> [--only 01,03] [--aspect 9:16|16:9|1:1] [--crop-x 0.5]
                 [--font "DejaVu Sans"] [--fontsdir DIR] [--words-per-line 3]

Reads <workdir>/clips.json, <workdir>/words.json and the source video;
writes <workdir>/out/<id>.mp4 (+ <id>.ass for debugging).
"""
import argparse
import glob
import json
import os
import subprocess

PAD_START = 0.12
PAD_END = 0.25
SIZES = {"9:16": (1080, 1920), "16:9": (1920, 1080), "1:1": (1080, 1080)}


def snap(seg, words):
    """Snap a segment to word boundaries: start at the first word starting at/after
    start-0.3, end at the last word ending at/before end+0.3."""
    s, e = seg["start"], seg["end"]
    inside = [w for w in words if w["s"] >= s - 0.3 and w["e"] <= e + 0.3]
    if inside:
        s, e = inside[0]["s"], inside[-1]["e"]
    return max(0.0, s - PAD_START), e + PAD_END


def ass_time(t):
    t = max(0.0, t)
    h = int(t // 3600)
    m = int(t % 3600 // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def esc(text):
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", " ")


def build_ass(clip, words, spans, W, H, font, wpl):
    """spans: list of (src_start, src_end) after snapping, concatenated in order."""
    fs = int(H * 0.042) if H > W else int(H * 0.055)
    title_fs = int(fs * 0.85)
    margin_v = int(H * 0.22) if H > W else int(H * 0.08)
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{font},{fs},&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,{max(3, fs // 12)},2,2,60,60,{margin_v},-1
Style: Title,{font},{title_fs},&H00FFFFFF,&H00FFFFFF,&H00000000,&HB4000000,-1,0,0,0,100,100,0,0,3,18,0,8,70,70,{int(H * 0.08)},-1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    total = sum(e - s for s, e in spans)
    title = clip.get("title")
    if title:
        events.append(f"Dialogue: 1,{ass_time(0)},{ass_time(total)},Title,,0,0,0,,{esc(title)}")

    # Map source-time words into clip time, grouped into short lines.
    offset = 0.0
    for s, e in spans:
        ws = [w for w in words if w["s"] >= s - 0.05 and w["e"] <= e + 0.05]
        groups = [ws[i:i + wpl] for i in range(0, len(ws), wpl)]
        for gi, g in enumerate(groups):
            g_end_src = groups[gi + 1][0]["s"] if gi + 1 < len(groups) else g[-1]["e"] + 0.3
            g_end_src = min(g_end_src, e)
            for wi, w in enumerate(g):
                t0 = w["s"] - s + offset
                t1 = (g[wi + 1]["s"] if wi + 1 < len(g) else g_end_src) - s + offset
                if t1 <= t0:
                    continue
                parts = []
                for wj, x in enumerate(g):
                    tok = esc(x["w"])
                    if wj == wi:
                        tok = "{\\c&H00D7FF&}" + tok + "{\\c&HFFFFFF&}"
                    parts.append(tok)
                events.append(f"Dialogue: 0,{ass_time(t0)},{ass_time(t1)},Cap,,0,0,0,,{' '.join(parts)}")
        offset += e - s
    return header + "\n".join(events) + "\n"


def find_source(workdir, name):
    p = os.path.join(workdir, name or "source.mp4")
    if os.path.exists(p):
        return p
    c = sorted(glob.glob(os.path.join(workdir, "source.*")))
    c = [x for x in c if not x.endswith(".json")]
    if not c:
        raise SystemExit("source video not found in " + workdir)
    return c[0]


def has_video(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries",
                          "stream=index", "-of", "csv=p=0", path], capture_output=True, text=True).stdout
    return bool(out.strip())


def render_clip(src, clip, words, outdir, W, H, crop_x, font, fontsdir, wpl, video):
    spans = [snap(seg, words) for seg in clip["segments"]]
    ass_path = os.path.abspath(os.path.join(outdir, f"{clip['id']}.ass"))
    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(build_ass(clip, words, spans, W, H, font, wpl))

    inputs, filters, concat_in = [], [], ""
    for i, (s, e) in enumerate(spans):
        inputs += ["-ss", f"{s:.3f}", "-t", f"{e - s:.3f}", "-i", src]
        if video:
            # Scale to cover the target frame, then crop at crop_x horizontally.
            filters.append(
                f"[{i}:v]scale={W}:{H}:force_original_aspect_ratio=increase,"
                f"crop={W}:{H}:(iw-{W})*{crop_x}:(ih-{H})/2,setsar=1,fps=30[v{i}]")
        else:
            filters.append(f"color=c=0x101418:s={W}x{H}:r=30:d={e - s:.3f}[v{i}]")
        filters.append(f"[{i}:a]aresample=48000,asetpts=PTS-STARTPTS[a{i}]")
        concat_in += f"[v{i}][a{i}]"
    n = len(spans)
    sub = ass_path.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
    fd = f":fontsdir='{fontsdir}'" if fontsdir else ""
    filters.append(f"{concat_in}concat=n={n}:v=1:a=1[vc][ac]")
    filters.append(f"[vc]ass='{sub}'{fd}[vout]")
    filters.append("[ac]loudnorm=I=-14:TP=-1.5:LRA=11[aout]")

    out = os.path.join(outdir, f"{clip['id']}.mp4")
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *inputs,
           "-filter_complex", ";".join(filters), "-map", "[vout]", "-map", "[aout]",
           "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", out]
    subprocess.run(cmd, check=True)
    dur = sum(e - s for s, e in spans)
    print(f"{clip['id']}: {out} ({dur:.1f}s)", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workdir")
    ap.add_argument("--only", default="")
    ap.add_argument("--aspect", default="9:16", choices=SIZES.keys())
    ap.add_argument("--crop-x", type=float, default=0.5)
    ap.add_argument("--font", default=os.environ.get("TORAH_CLIPS_FONT", "DejaVu Sans"))
    ap.add_argument("--fontsdir", default=os.environ.get("TORAH_CLIPS_FONTSDIR", ""))
    ap.add_argument("--words-per-line", type=int, default=3)
    args = ap.parse_args()

    wd = args.workdir
    with open(os.path.join(wd, "clips.json"), encoding="utf-8") as f:
        spec = json.load(f)
    with open(os.path.join(wd, "words.json"), encoding="utf-8") as f:
        words = json.load(f)
    src = find_source(wd, spec.get("source"))
    video = has_video(src)
    outdir = os.path.join(wd, "out")
    os.makedirs(outdir, exist_ok=True)
    W, H = SIZES[args.aspect]
    only = {x.strip() for x in args.only.split(",") if x.strip()}
    for clip in spec["clips"]:
        if only and clip["id"] not in only:
            continue
        render_clip(src, clip, words, outdir, W, H, args.crop_x, args.font,
                    args.fontsdir, args.words_per_line, video)


if __name__ == "__main__":
    main()
