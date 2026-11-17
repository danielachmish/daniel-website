#!/usr/bin/env bash
# Usage: fetch.sh <youtube-url | local-file> <workdir>
# Produces <workdir>/source.mp4 and <workdir>/audio.wav (16kHz mono).
set -euo pipefail
SRC="${1:?source url or file}"
WORK="${2:?workdir}"
mkdir -p "$WORK"

if [[ -f "$SRC" ]]; then
  ext="${SRC##*.}"
  ln -sf "$(realpath "$SRC")" "$WORK/source.$ext"
  SRC_FILE="$WORK/source.$ext"
else
  if ! command -v yt-dlp >/dev/null 2>&1; then
    python3 -m pip install -q -U yt-dlp
  fi
  yt-dlp -f "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080]/b" \
    --merge-output-format mp4 -o "$WORK/source.%(ext)s" \
    --write-info-json --no-playlist "$SRC"
  SRC_FILE="$WORK/source.mp4"
fi

ffmpeg -hide_banner -loglevel error -y -i "$SRC_FILE" -vn -ac 1 -ar 16000 "$WORK/audio.wav"
dur=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$WORK/audio.wav")
echo "OK: $SRC_FILE  audio.wav  duration=${dur}s"
