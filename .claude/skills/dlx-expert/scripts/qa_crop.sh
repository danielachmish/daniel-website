#!/usr/bin/env bash
# qa_crop.sh - zoomed inspection of one region of a video over a time range.
# Use it on every shot that has a composited screen (phone, laptop, sign) or any small detail:
# it shows the region at 100% (or larger) every 0.25s, so misaligned corners, screen overflowing the
# bezel, green-screen spill, drifting tracking and unreadable text become visible.
#
# Usage: qa_crop.sh <video> <start_s> <end_s> <x:y:w:h> [outdir]
#   x:y:w:h = region in the video's own pixels (top-left corner, width, height)
# Example: qa_crop.sh ad.mp4 2 6 960:100:520:900
set -euo pipefail
[[ $# -ge 4 ]] || { echo "Usage: $0 <video> <start_s> <end_s> <x:y:w:h> [outdir]" >&2; exit 2; }
VIDEO="$1"; START="$2"; END="$3"; REGION="$4"
OUT="${5:-./qa_crop_out}"
[[ -f "$VIDEO" ]] || { echo "File not found: $VIDEO" >&2; exit 2; }
IFS=: read -r X Y W H <<< "$REGION"
mkdir -p "$OUT"
DUR=$(awk -v s="$START" -v e="$END" 'BEGIN{print e-s}')
# Scale so the crop is at least 600px tall (zoom in on small regions), never shrink below 100%.
SCALE="scale=-2:'max(600,ih)'"
ffmpeg -v error -y -ss "$START" -t "$DUR" -i "$VIDEO" \
  -vf "crop=${W}:${H}:${X}:${Y},${SCALE},fps=4,drawtext=text='%{pts\\:hms}':x=6:y=6:fontsize=20:fontcolor=yellow:box=1:boxcolor=black@0.6,tile=4x2:padding=4" \
  -start_number 1 "$OUT/crop_%02d.png"
echo "Zoomed crop sheets (every 0.25s, ${W}x${H} at ${X},${Y}, ${START}-${END}s): $OUT/"
echo "LOOK FOR: screen edges outside the device bezel, square corners on a rounded screen, perspective that"
echo "does not match the device, green/blue spill on edges, the screen sliding relative to the device between"
echo "frames, glare/brightness that does not match the scene, and text too small to read."
