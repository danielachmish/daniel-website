"""beat_grid.py - estimate tempo (BPM), the first beat and the energy profile of a music track, so cuts,
type hits and SFX can be placed exactly on the beat (agency rule: >=80% of cuts within +-2 frames of a beat).

Usage: python3 -I beat_grid.py <music.mp3|wav> [fps=30]
Prints BPM, beat length in seconds and frames, first-beat offset, and RMS energy per 2s window
(use the energy to pick the segment with a build/drop, and align the track's real ending with the end card).
Requires ffmpeg and numpy.
"""
import subprocess
import sys
import numpy as np

path = sys.argv[1]
fps = float(sys.argv[2]) if len(sys.argv) > 2 else 30.0
sr = 11025
raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', path, '-ac', '1', '-ar', str(sr), '-f', 's16le', '-'],
                     capture_output=True, check=True).stdout
x = np.frombuffer(raw, dtype=np.int16).astype(float) / 32768
hop = 256
n = len(x) // hop
e = np.sqrt(np.mean(x[:n * hop].reshape(n, hop) ** 2, axis=1))
on = np.maximum(0, np.diff(np.log(e + 1e-4)))
on = np.convolve(on, np.ones(3) / 3, 'same')
rate = sr / hop
best_bpm, best_s = None, -1
for bpm in np.arange(70, 181, 0.5):
    lag = int(round(rate * 60 / bpm))
    s = np.mean(on[:-lag] * on[lag:])
    if s > best_s:
        best_bpm, best_s = bpm, s
bpm = best_bpm * 2 if best_bpm < 90 else best_bpm
period = rate * 60 / bpm
phases = np.arange(0, period, 0.5)
scores = [sum(on[int(round(ph + k * period))] for k in range(int((len(on) - ph) / period)) if int(round(ph + k * period)) < len(on)) for ph in phases]
first = phases[int(np.argmax(scores))] / rate
beat = 60 / bpm
print(f'BPM ~{bpm:.1f} | beat {beat:.4f}s = {beat * fps:.3f} frames @ {fps:g}fps | first beat at {first:.3f}s')
print('To start the video on a beat, trim the track at: first + k*beat (e.g. ffmpeg -ss <that> ...)')
w = int(2 * rate)
for i in range(0, n - w, w):
    print(f'{i / rate:6.1f}s  rms {20 * np.log10(np.mean(e[i:i + w]) + 1e-9):6.1f} dB')
