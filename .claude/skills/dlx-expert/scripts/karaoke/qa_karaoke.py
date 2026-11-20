#!/usr/bin/env python3
"""qa_karaoke.py - mandatory QA for a karaoke render made by karaoke.py. Exit 1 on any FAIL.

  python qa_karaoke.py <timing.json> [--out qa_dir] [--no-bleed-model] [--shift 0.0]

Checks
  (a) SYNC     word starts vs. the vocal stem: nearest onset (all words), energy rise at phrase starts,
               global lag (cross-correlation), words sitting on silence.
               FAIL: p90 > 250 ms (either measure), |lag| > 100 ms, < 75% of word time voiced.
  (b) BLEED    vocal residue left in the instrumental: re-separate the instrumental with a second model
               (MDX Inst HQ3) and compare its "vocals" energy with the real vocal stem (whole song and the
               worst 2-second window). Plus a band-energy heuristic (300-3500 Hz, sung vs. non-sung frames).
               FAIL: whole-song residue > -14 dB.
  (c) PITCH    shift measured between original and shifted instrumental (log-frequency cross-correlation
               of whitened spectra, median over blocks). FAIL: |measured - requested| > 15 cents,
               duration diff > 50 ms, time offset > 20 ms.
  (d) LOUDNESS each MP4: -14 +-1 LUFS, true peak <= -1 dBTP; resolution and duration.
  (e) FRAMES   lyric-moment frames + contact sheet per format; automatic highlight-direction test
               (RTL: the sung part must be on the RIGHT of the unsung part); OCR word-order test with
               tesseract (heb/eng) when installed.
--shift S adds S seconds to every word (negative control: a 0.4 s shift must FAIL the sync check).
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path

import numpy as np

RESULTS = []


def res(level, name, msg):
    RESULTS.append((level, name, msg))
    print(f"{level:5s} {name}: {msg}", flush=True)


def load_mono(path, sr=22050):
    import librosa
    y, _ = librosa.load(str(path), sr=sr, mono=True)
    return y


def pct(a, q):
    return float(np.percentile(np.asarray(a), q)) if len(a) else float("nan")


# ----------------------------------------------------------------------------------- (a) sync
def check_sync(T, shift):
    import librosa
    sr, hop = 22050, 256
    fps = sr / hop
    y = load_mono(T["stems"]["vocals"], sr)
    env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop)
    onsets = librosa.onset.onset_detect(onset_envelope=env, sr=sr, hop_length=hop, backtrack=True, units="time")
    rms = librosa.feature.rms(y=y, frame_length=1024, hop_length=hop)[0]
    db = 20 * np.log10(rms + 1e-9)
    active = db > np.percentile(db, 95) - 30

    words = [dict(w) for w in T["words"]]
    for w in words:
        w["start"] += shift
        w["end"] += shift
    meas = [w for w in words if not w.get("interpolated")]

    # 1) nearest onset (all words)
    offs = []
    for w in meas:
        if len(onsets):
            d = w["start"] - onsets[np.argmin(np.abs(onsets - w["start"]))]
            if abs(d) <= 0.5:
                offs.append(d)
    a1 = np.abs(offs) * 1000 if offs else np.array([9999.0])
    no_onset = 1 - len(offs) / max(1, len(meas))

    # 2) phrase starts: word after >= 0.35 s rest, silence before -> first voiced frame
    poffs = []
    for i, w in enumerate(meas):
        if i and w["start"] - meas[i - 1]["end"] < 0.35:
            continue
        lo = int(max(0, (w["start"] - 0.6) * fps))
        hi = int(min(len(active), (w["start"] + 0.6) * fps))
        seg = active[lo:hi]
        if seg.size < 10 or seg[:4].any() or not seg.any():
            continue
        poffs.append(w["start"] - (lo + int(np.argmax(seg))) / fps)
    a2 = np.abs(poffs) * 1000 if poffs else np.array([])

    # 3) global lag: word-start impulses vs onset envelope
    n = len(env)
    imp = np.zeros(n)
    for w in meas:
        k = int(round(w["start"] * fps))
        if 0 <= k < n:
            imp[k] = 1
    g = np.exp(-0.5 * (np.arange(-6, 7) / 2.0) ** 2)
    imp = np.convolve(imp, g, "same")
    e = (env - env.mean()) / (env.std() + 1e-9)
    maxlag = int(0.5 * fps)
    lags = np.arange(-maxlag, maxlag + 1)
    xc = [np.dot(imp[max(0, -l):n - max(0, l)], e[max(0, l):n - max(0, -l)]) for l in lags]
    lag_ms = -lags[int(np.argmax(xc))] / fps * 1000  # >0: words are LATE vs. the voice

    # 4) voiced coverage
    tot = on = 0
    for w in meas:
        a, b = int(w["start"] * fps), int(w["end"] * fps)
        tot += max(1, b - a)
        on += int(active[a:max(a + 1, b)].sum())
    cov = on / max(1, tot)

    out = dict(words=len(meas), nearest_onset_median_ms=round(float(np.median(a1)), 1),
               nearest_onset_p90_ms=round(pct(a1, 90), 1), words_without_onset=round(no_onset, 3),
               phrase_starts=len(a2), phrase_start_median_ms=round(float(np.median(a2)), 1) if len(a2) else None,
               phrase_start_p90_ms=round(pct(a2, 90), 1) if len(a2) else None,
               phrase_start_signed_median_ms=round(float(np.median(poffs)) * 1000, 1) if poffs else None,
               global_lag_ms=round(float(lag_ms), 1), voiced_coverage=round(cov, 3))
    msg = (f"nearest-onset median {out['nearest_onset_median_ms']}ms p90 {out['nearest_onset_p90_ms']}ms "
           f"({len(offs)}/{len(meas)} words); phrase-starts n={out['phrase_starts']} median "
           f"{out['phrase_start_median_ms']}ms p90 {out['phrase_start_p90_ms']}ms; lag {out['global_lag_ms']}ms; "
           f"voiced {cov:.0%}")
    fail = (out["nearest_onset_p90_ms"] > 250 or (len(a2) >= 3 and out["phrase_start_p90_ms"] > 250)
            or abs(lag_ms) > 100 or cov < 0.75)
    res("FAIL" if fail else "PASS", "sync", msg)
    if not fail and len(a2) < 3:
        res("WARN", "sync", "fewer than 3 clean phrase starts - phrase-start measure not conclusive")
    return out


# ---------------------------------------------------------------------------------- (b) bleed
def separator_exe():
    exe = shutil.which("audio-separator") or str(Path(sys.executable).parent / "audio-separator")
    return exe if Path(exe).exists() else None


def check_bleed(T, use_model, work):
    import librosa
    sr = 22050
    inst = load_mono(T["stems"]["instrumental"], sr)
    voc = load_mono(T["stems"]["vocals"], sr)
    mix = load_mono(T["stems"]["mix"], sr)
    n = min(len(inst), len(voc), len(mix))
    inst, voc, mix = inst[:n], voc[:n], mix[:n]
    out = {}
    # heuristic: 300-3500 Hz energy of instrumental relative to mix, sung vs non-sung frames
    S = lambda x: np.abs(librosa.stft(x, n_fft=2048, hop_length=512)) ** 2  # noqa
    f = librosa.fft_frequencies(sr=sr, n_fft=2048)
    band = (f > 300) & (f < 3500)
    Ei, Em, Ev = S(inst)[band].sum(0), S(mix)[band].sum(0), S(voc)[band].sum(0)
    vdb = 10 * np.log10(Ev + 1e-12)
    sung = vdb > np.percentile(vdb, 95) - 25
    r = 10 * np.log10((Ei + 1e-12) / (Em + 1e-12))
    if sung.any() and (~sung).any():
        out["band_drop_sung_vs_unsung_db"] = round(float(np.median(r[sung]) - np.median(r[~sung])), 2)
    exe = separator_exe() if use_model else None
    model_dir = Path(T.get("model_dir") or (Path.home() / ".cache" / "karaoke-models"))
    if exe:
        d = work / "bleed_sep"
        shutil.rmtree(d, ignore_errors=True)
        r2 = subprocess.run([exe, T["stems"]["instrumental"], "-m", "UVR-MDX-NET-Inst_HQ_3.onnx",
                             "--model_file_dir", str(model_dir), "--output_dir", str(d), "--output_format", "WAV",
                             "--single_stem", "Vocals"], capture_output=True, text=True)
        vs = list(d.glob("*(Vocals)*.wav"))
        if r2.returncode == 0 and vs:
            resid = load_mono(vs[0], sr)[:n]
            ev, er = float(np.sum(voc ** 2)), float(np.sum(resid ** 2))
            whole = 10 * np.log10((er + 1e-12) / (ev + 1e-12))
            # worst 2 s window, only where the singer sings (relative to that window's vocal energy)
            win = 2 * sr
            worst, wt = -120.0, 0.0
            for s in range(0, n - win, sr // 2):
                v = float(np.sum(voc[s:s + win] ** 2))
                if v < ev / (n / win) * 0.3:
                    continue
                d_db = 10 * np.log10((float(np.sum(resid[s:s + win] ** 2)) + 1e-12) / (v + 1e-12))
                if d_db > worst:
                    worst, wt = d_db, s / sr
            out.update(residue_db=round(whole, 2), worst_window_db=round(worst, 2), worst_window_at_s=round(wt, 1))
        else:
            out["residue_db"] = None
            res("WARN", "bleed", f"second-model check failed to run: {r2.stderr[-300:]}")
    if out.get("residue_db") is not None:
        lvl = "FAIL" if out["residue_db"] > -14 else ("WARN" if out["residue_db"] > -20 or out["worst_window_db"] > -10 else "PASS")
        res(lvl, "bleed", f"vocal residue in instrumental {out['residue_db']} dB vs. the vocal stem "
                          f"(worst 2s window {out['worst_window_db']} dB at {out['worst_window_at_s']}s - listen there); "
                          f"band heuristic {out.get('band_drop_sung_vs_unsung_db')} dB")
    else:
        res("WARN", "bleed", f"model check not run; band heuristic only: {out.get('band_drop_sung_vs_unsung_db')} dB "
                             "(more negative = vocals removed; ~0 = vocals still there)")
    return out


# ---------------------------------------------------------------------------------- (c) pitch
def logspec(y, sr, fmin=150.0, fmax=4000.0, step=5.0):
    import librosa
    Sx = np.abs(librosa.stft(y, n_fft=16384, hop_length=4096))
    f = librosa.fft_frequencies(sr=sr, n_fft=16384)
    cents = np.arange(0, 1200 * np.log2(fmax / fmin), step)
    grid = fmin * 2 ** (cents / 1200)
    L = np.stack([np.interp(grid, f, 20 * np.log10(Sx[:, t] + 1e-9)) for t in range(Sx.shape[1])], 1)
    return L, step


def whiten(L, width):
    from scipy.ndimage import median_filter
    W = L - median_filter(L, size=(width, 1), mode="nearest")
    return np.clip(W, 0, None)


def measure_shift(orig, shifted, sr):
    A, step = logspec(orig, sr)
    B, _ = logspec(shifted, sr)
    m = min(A.shape[1], B.shape[1])
    A, B = whiten(A[:, :m], 41), whiten(B[:, :m], 41)
    maxlag = int(450 / step)
    blk = 8  # ~1.5 s blocks
    ests = []
    energy = A.sum(0)
    thr = np.percentile(energy, 30)
    for s in range(0, m - blk, blk):
        if energy[s:s + blk].mean() < thr:
            continue
        a, b = A[:, s:s + blk].mean(1), B[:, s:s + blk].mean(1)
        a = a - a.mean(); b = b - b.mean()
        best = None
        xs = []
        for l in range(-maxlag, maxlag + 1):
            if l >= 0:
                xs.append(np.dot(a[:len(a) - l], b[l:]))
            else:
                xs.append(np.dot(a[-l:], b[:len(b) + l]))
        xs = np.array(xs)
        k = int(np.argmax(xs))
        if 0 < k < len(xs) - 1:
            den = xs[k - 1] - 2 * xs[k] + xs[k + 1]
            frac = 0.5 * (xs[k - 1] - xs[k + 1]) / den if den != 0 else 0
        else:
            frac = 0
        best = (k - maxlag + frac) * step
        ests.append(best)
    ests = np.array(ests)
    return float(np.median(ests)), float(np.median(np.abs(ests - np.median(ests)))), len(ests)


def check_pitch(T):
    import soundfile as sf
    import librosa
    semis = float(T.get("semitones") or 0)
    if not semis:
        res("PASS", "pitch", "no key change requested (skipped)")
        return {}
    o_path, s_path = T["stems"]["instrumental"], T["stems"]["instrumental_used"]
    io, is_ = sf.info(o_path), sf.info(s_path)
    ddiff = abs(io.frames / io.samplerate - is_.frames / is_.samplerate) * 1000
    sr = 22050
    yo, ys = load_mono(o_path, sr), load_mono(s_path, sr)
    cents, mad, nblk = measure_shift(yo, ys, sr)
    err = cents - semis * 100
    # timing offset via onset envelopes (pitch shift must not move the beat)
    hop = 256
    eo = librosa.onset.onset_strength(y=yo, sr=sr, hop_length=hop)
    es = librosa.onset.onset_strength(y=ys, sr=sr, hop_length=hop)
    m = min(len(eo), len(es))
    eo, es = eo[:m] - eo[:m].mean(), es[:m] - es[:m].mean()
    L = 20
    xc = [np.dot(eo[max(0, -l):m - max(0, l)], es[max(0, l):m - max(0, -l)]) for l in range(-L, L + 1)]
    off_ms = (int(np.argmax(xc)) - L) * hop / sr * 1000
    corr = float(np.corrcoef(eo, es)[0, 1])
    out = dict(requested_cents=semis * 100, measured_cents=round(cents, 1), error_cents=round(err, 1),
               block_spread_cents=round(mad, 1), blocks=nblk, duration_diff_ms=round(ddiff, 1),
               time_offset_ms=round(off_ms, 1), onset_envelope_corr=round(corr, 3))
    fail = abs(err) > 15 or ddiff > 50 or abs(off_ms) > 20
    res("FAIL" if fail else "PASS", "pitch",
        f"requested {semis:+g} st = {semis * 100:+.0f} cents, measured {cents:+.1f} cents (error {err:+.1f}, "
        f"spread {mad:.1f}, {nblk} blocks); duration diff {ddiff:.1f} ms; time offset {off_ms:.1f} ms")
    if corr < 0.8:
        res("WARN", "pitch", f"onset envelope correlation {corr:.2f} < 0.8: transients may be smeared - listen")
    return out


# ------------------------------------------------------------------------------- (d) loudness
def probe(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=width,height,codec_type",
                        "-of", "json", str(path)], capture_output=True, text=True)
    return json.loads(r.stdout)


def check_loudness(T):
    out = {}
    for o in T["outputs"]:
        p = o["mp4"]
        if not Path(p).exists():
            res("FAIL", "output", f"missing {p}")
            continue
        r = subprocess.run(["ffmpeg", "-hide_banner", "-i", p, "-vn", "-af", "loudnorm=print_format=json",
                            "-f", "null", "-"], capture_output=True, text=True)
        j = json.loads(r.stderr[r.stderr.rfind("{"):r.stderr.rfind("}") + 1])
        lufs, tp = float(j["input_i"]), float(j["input_tp"])
        pr = probe(p)
        v = [s for s in pr["streams"] if s.get("codec_type") == "video"][0]
        dur = float(pr["format"]["duration"])
        ok = -15 <= lufs <= -13 and tp <= -1.0
        res("PASS" if ok else "FAIL", f"loudness[{o['format']}]", f"{lufs:.1f} LUFS, true peak {tp:.1f} dBTP")
        size_ok = (v["width"], v["height"]) == (o["width"], o["height"])
        dur_ok = abs(dur - T["duration"]) < 0.2
        res("PASS" if size_ok and dur_ok else "FAIL", f"format[{o['format']}]",
            f"{v['width']}x{v['height']}, {dur:.2f}s (song {T['duration']:.2f}s)")
        out[o["format"]] = dict(lufs=lufs, true_peak=tp, width=v["width"], height=v["height"], duration=dur)
    return out



# ----------------------------------------------------------------------------------- layout
ASS_T = re.compile(r"(\d+):(\d\d):(\d\d)\.(\d\d)")


def ass_sec(t):
    h, m, s_, cs = map(int, ASS_T.match(t).groups())
    return h * 3600 + m * 60 + s_ + cs / 100


def check_layout(T):
    """(1) the .ass itself: no two lyric events at the same position at the same time (ghosted text);
    (2) no two text boxes (lyrics, count-in dots, title) intersect while both are on screen;
    (3) every box inside the frame with a 3% margin; never more than 2 lyric lines on screen."""
    out = {}
    for o in T["outputs"]:
        fmt, W, H = o["format"], o["width"], o["height"]
        evs = []
        for ln in Path(o["ass"]).read_text(encoding="utf-8-sig").splitlines():
            if not ln.startswith("Dialogue:"):
                continue
            f = ln.split(",", 9)
            m = re.search(r"\\pos\(([-\d.]+),([-\d.]+)\)", f[9])
            evs.append(dict(style=f[3], start=ass_sec(f[1]), end=ass_sec(f[2]),
                            pos=(round(float(m.group(1))), round(float(m.group(2)))) if m else None))
        lyr = sorted([e for e in evs if e["style"] == "Lyric"], key=lambda e: e["start"])
        same = []
        for i, a in enumerate(lyr):
            for b in lyr[i + 1:]:
                if b["start"] >= a["end"]:
                    continue
                if a["pos"] == b["pos"]:
                    same.append(f"{a['start']:.2f}-{a['end']:.2f} & {b['start']:.2f}-{b['end']:.2f} at {a['pos']}")
        # max simultaneous lyric lines
        pts = sorted([(e["start"], 1) for e in lyr] + [(e["end"], -1) for e in lyr], key=lambda x: (x[0], x[1]))
        cur = mx = 0
        for _, d in pts:
            cur += d
            mx = max(mx, cur)
        inter, outside = [], []
        bx = o.get("boxes", [])
        for i, a in enumerate(bx):
            x0, y0, x1, y1 = a["box"]
            if x0 < W * 0.03 or x1 > W * 0.97 or y0 < 0 or y1 > H:
                outside.append(f"{a['kind']} {a['start']:.2f}s {a['box']}")
            for b in bx[i + 1:]:
                if min(a["end"], b["end"]) - max(a["start"], b["start"]) <= 0.02:
                    continue
                X0, Y0, X1, Y1 = b["box"]
                if x0 < X1 - 4 and X0 < x1 - 4 and y0 < Y1 - 4 and Y0 < y1 - 4:
                    inter.append(f"{a['kind']}@{a['start']:.2f}s x {b['kind']}@{b['start']:.2f}s")
        fail = bool(same or inter or outside or mx > 2)
        res("FAIL" if fail else "PASS", f"layout[{fmt}]",
            f"{len(lyr)} lyric events; same-position overlaps {len(same)}; box intersections {len(inter)}; "
            f"outside frame {len(outside)}; max lines on screen {mx}"
            + (f" | e.g. {(same + inter + outside)[:3]}" if fail else ""))
        out[fmt] = dict(same_position_overlaps=same, box_intersections=inter, outside=outside, max_lines=mx)
    return out

# --------------------------------------------------------------------------------- (e) frames
def hex_rgb(h):
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], float)


def grab(mp4, t, path):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", mp4, "-frames:v", "1", str(path)],
                   check=True)


def ys_for(o, slot):
    W, H = o["width"], o["height"]
    return ([H * 0.62, H * 0.78] if H < W else [H * 0.47, H * 0.57])[slot]


def norm_word(s):
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if c.isalnum() and not unicodedata.combining(c)).lower()


def ocr_line(img_path, box, lang):
    if not shutil.which("tesseract"):
        return None
    from PIL import Image, ImageOps
    im = Image.open(img_path).convert("RGB").crop(box)
    g = np.asarray(im).astype(float)
    # text (white or yellow, both bright) -> black on white for OCR
    bright = (g.max(2) > 170) & (g.min(2) > 20)
    b = Image.fromarray(np.where(bright, 0, 255).astype(np.uint8))
    b = ImageOps.expand(b, 20, fill=255)
    with tempfile.NamedTemporaryFile(suffix=".png") as tf:
        b.save(tf.name)
        r = subprocess.run(["tesseract", tf.name, "-", "-l", "heb" if lang == "he" else "eng", "--psm", "7"],
                           capture_output=True, text=True)
    return r.stdout.strip()


def check_frames(T, qa_dir):
    from PIL import Image
    words, lines = T["words"], T["lines"]
    sung, unsung = hex_rgb(T["colors"]["sung"]), hex_rgb(T["colors"]["unsung"])
    rtl = T["rtl"]
    out = {"direction": [], "ocr": [], "frames": []}
    fr_dir = qa_dir / "frames"
    fr_dir.mkdir(parents=True, exist_ok=True)
    # moments: count-in of the first line, then lines spread over the song (partly sung)
    idx = sorted(set(np.linspace(0, len(lines) - 1, min(8, len(lines))).astype(int).tolist()))
    dir_fail = 0
    ocr_scores = []
    for o in T["outputs"]:
        shots = []
        for c in T.get("countins", [])[:2]:
            t = c["end"] - c["beat"] * 1.5
            p = fr_dir / f"{o['format']}_countin_{t:07.2f}.png"
            grab(o["mp4"], t, p); shots.append(p)
        for i in idx:
            L = lines[i]
            ws = L["words"]
            if len(ws) < 2:
                continue
            # moment: halfway through the 2nd word -> first word fully sung, last words unsung
            w2 = words[ws[1]]
            t = (w2["start"] + w2["end"]) / 2
            p = fr_dir / f"{o['format']}_line{i:03d}_{t:07.2f}.png"
            grab(o["mp4"], t, p); shots.append(p)
            im = np.asarray(Image.open(p).convert("RGB")).astype(float)
            g = L.get("geo", {}).get(f"{o['width']}x{o['height']}", {})
            y = g.get("y", ys_for(o, L["slot"]))
            fs = g.get("font_size", 80)
            y0, y1 = int(max(0, y - fs * 0.75)), int(min(im.shape[0], y + fs * 0.75))
            band = im[y0:y1]
            ds = np.linalg.norm(band - sung, axis=2)
            du = np.linalg.norm(band - unsung, axis=2)
            ms, mu = ds < 60, du < 45
            if ms.sum() > 50 and mu.sum() > 50:
                xs = np.nonzero(ms)[1].mean()
                xu = np.nonzero(mu)[1].mean()
                ok = (xs > xu) if rtl else (xs < xu)
                out["direction"].append(dict(line=i, t=round(t, 2), fmt=o["format"], sung_x=round(xs), unsung_x=round(xu), ok=bool(ok)))
                dir_fail += 0 if ok else 1
            # OCR on a frame where the line is visible (same frame)
            half = g.get("width_px", o["width"] * 0.8) / 2 + 30
            box = (int(max(0, o["width"] / 2 - half)), y0, int(min(o["width"], o["width"] / 2 + half)), y1)
            txt = ocr_line(p, box, T["lang"])
            if txt is not None:
                exp = [norm_word(words[j]["text"]) for j in ws]
                got = [norm_word(x) for x in txt.split() if norm_word(x)]
                sc = difflib.SequenceMatcher(None, exp, got).ratio()
                rev = difflib.SequenceMatcher(None, exp, got[::-1]).ratio()
                ocr_scores.append(sc)
                out["ocr"].append(dict(line=i, fmt=o["format"], expected=" ".join(words[j]["text"] for j in ws),
                                       ocr=txt, order_score=round(sc, 2), reversed_score=round(rev, 2)))
        out["frames"] += [str(s) for s in shots]
        # contact sheet
        if shots:
            ims = [Image.open(s).convert("RGB") for s in shots]
            tw = 640
            th = int(ims[0].height * tw / ims[0].width)
            cols = 3 if o["width"] > o["height"] else 4
            if o["width"] < o["height"]:
                tw, th = 360, 640
            rows = (len(ims) + cols - 1) // cols
            sheet = Image.new("RGB", (cols * (tw + 6), rows * (th + 6)), "black")
            for k, im in enumerate(ims):
                sheet.paste(im.resize((tw, th)), ((k % cols) * (tw + 6), (k // cols) * (th + 6)))
            sp = qa_dir / f"contact_{o['format']}.png"
            sheet.save(sp)
            out.setdefault("sheets", []).append(str(sp))
    nd = len(out["direction"])
    if nd == 0:
        res("WARN", "highlight-direction", "could not measure (no frame with both sung and unsung text)")
    else:
        res("FAIL" if dir_fail else "PASS", "highlight-direction",
            f"{nd - dir_fail}/{nd} frames: sung part starts on the {'right (RTL)' if rtl else 'left (LTR)'}")
    if ocr_scores:
        m = float(np.mean(ocr_scores))
        revs = [x["reversed_score"] for x in out["ocr"]]
        flipped = sum(1 for x in out["ocr"] if x["reversed_score"] > x["order_score"] + 0.2)
        lvl = "FAIL" if flipped >= max(1, len(revs) // 3) else ("PASS" if m >= 0.6 else "WARN")
        res(lvl, "word-order(OCR)", f"mean order match {m:.2f}; lines that read reversed: {flipped}/{len(revs)} "
                                    "(OCR is approximate - the critic must also read the frames)")
    else:
        res("WARN", "word-order(OCR)", "tesseract not installed - word order must be checked by eye")
    return out


# ------------------------------------------------------------------------------------- lyrics
def check_lyrics(T):
    if T["lyrics_source"] != "supplied":
        res("FAIL", "lyrics", "lyrics are an unconfirmed transcription - user must confirm lyrics_draft.txt first")
    else:
        res("PASS", "lyrics", "lyrics supplied by user/source (aligned, not invented)")
    interp = sum(1 for w in T["words"] if w.get("interpolated"))
    lowp = sum(1 for w in T["words"] if (w.get("prob") or 0) < 0.2)
    if interp:
        res("WARN", "alignment", f"{interp} words had no timestamp and were interpolated - check those lines")
    if lowp > 0.15 * len(T["words"]):
        res("WARN", "alignment", f"{lowp}/{len(T['words'])} words aligned with very low confidence - "
                                 "lyrics may not match this recording (other version / ad-libs)")
    long_lines = [L["text"] for L in T["lines"] if len(L["words"]) > 7]
    if long_lines:
        res("WARN", "lines", f"{len(long_lines)} lines with > 7 words")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("timing")
    ap.add_argument("--out", default=None)
    ap.add_argument("--no-bleed-model", action="store_true")
    ap.add_argument("--shift", type=float, default=0.0)
    ap.add_argument("--skip", default="", help="comma list of checks to skip: sync,bleed,pitch,loudness,layout,frames")
    a = ap.parse_args()
    T = json.loads(Path(a.timing).read_text(encoding="utf-8"))
    qa_dir = Path(a.out or Path(a.timing).parent / "qa")
    qa_dir.mkdir(parents=True, exist_ok=True)
    skip = set(x.strip() for x in a.skip.split(",") if x.strip())
    report = {"timing": a.timing, "shift": a.shift}
    check_lyrics(T)
    if "sync" not in skip:
        report["sync"] = check_sync(T, a.shift)
    if a.shift:
        print("(negative-control run: only the sync result is meaningful)")
    else:
        if "bleed" not in skip:
            report["bleed"] = check_bleed(T, not a.no_bleed_model, qa_dir)
        if "pitch" not in skip:
            report["pitch"] = check_pitch(T)
        if "loudness" not in skip:
            report["loudness"] = check_loudness(T)
        if "layout" not in skip:
            report["layout"] = check_layout(T)
        if "frames" not in skip:
            report["frames"] = check_frames(T, qa_dir)
    report["results"] = [dict(level=l, check=n, msg=m) for l, n, m in RESULTS]
    (qa_dir / "qa_karaoke.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    md = ["# דוח בדיקת קריוקי", "", f"קובץ תזמון: `{a.timing}`", "", "| רמה | בדיקה | פירוט |", "|---|---|---|"]
    md += [f"| {l} | {n} | {m} |" for l, n, m in RESULTS]
    if report.get("frames"):
        md += ["", "## פריימים לבדיקה בעין (חובה: מבקר נפרד)"] + [f"- `{p}`" for p in report["frames"].get("sheets", [])]
    (qa_dir / "qa_karaoke_report.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    nf = sum(1 for l, _, _ in RESULTS if l == "FAIL")
    print(f"\nReport: {qa_dir / 'qa_karaoke_report.md'}")
    if nf:
        print(f"RESULT: FAIL ({nf}) - do NOT deliver. Fix and re-run.")
        sys.exit(1)
    print("RESULT: automatic checks passed. Still required: critic review of the frames/contact sheets, "
          "and listening to the worst bleed window.")


if __name__ == "__main__":
    main()
