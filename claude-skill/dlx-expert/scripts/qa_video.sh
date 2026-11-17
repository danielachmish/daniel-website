#!/usr/bin/env bash
# qa_video.sh <video> [outdir]
# Mandatory video QA before delivery: metadata, key frames, cuts, contact sheet,
# phone-size frames, loudness, true peak, spectrogram, silence. Prints PASS/WARN summary.
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <video> [outdir]" >&2; exit 2
fi
VIDEO="$1"
[[ -f "$VIDEO" ]] || { echo "File not found: $VIDEO" >&2; exit 2; }
OUT="${2:-./qa_video_out}"
mkdir -p "$OUT/frames" "$OUT/phone" "$OUT/shots"
command -v ffmpeg >/dev/null && command -v ffprobe >/dev/null || { echo "ffmpeg/ffprobe required" >&2; exit 2; }

declare -a FLAGS=()
pass() { FLAGS+=("PASS  $1"); }
warn() { FLAGS+=("WARN  $1"); }
NFAIL=0
fail() { FLAGS+=("FAIL  $1"); NFAIL=$((NFAIL+1)); }

# ---------- metadata ----------
DUR=$(ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$VIDEO")
W=$(ffprobe -v error -select_streams v:0 -show_entries stream=width -of default=nw=1:nk=1 "$VIDEO")
H=$(ffprobe -v error -select_streams v:0 -show_entries stream=height -of default=nw=1:nk=1 "$VIDEO")
FPS_RAW=$(ffprobe -v error -select_streams v:0 -show_entries stream=r_frame_rate -of default=nw=1:nk=1 "$VIDEO")
FPS=$(awk -F/ '{ if ($2>0) printf "%.2f", $1/$2; else print $1 }' <<<"$FPS_RAW")
HAS_AUDIO=$(ffprobe -v error -select_streams a -show_entries stream=index -of csv=p=0 "$VIDEO" | head -1 || true)
ASPECT=$(awk -v w="$W" -v h="$H" 'BEGIN{
  r=w/h; a="custom";
  if (r>1.70&&r<1.80) a="16:9 (horizontal)"; else if (r>0.55&&r<0.58) a="9:16 (vertical)";
  else if (r>0.99&&r<1.01) a="1:1 (square)"; else if (r>0.79&&r<0.81) a="4:5 (feed)";
  printf "%s (%.3f)", a, r }')

echo "=== METADATA ==="
printf "File:       %s\nDuration:   %.2fs\nResolution: %sx%s\nAspect:     %s\nFPS:        %s\nAudio:      %s\n" \
  "$VIDEO" "$DUR" "$W" "$H" "$ASPECT" "$FPS" "$([[ -n "$HAS_AUDIO" ]] && echo yes || echo NO)"

# ---------- key frames ----------
echo; echo "=== KEY FRAMES ==="
for t in 0 0.5 1 2 3; do
  if awk -v t="$t" -v d="$DUR" 'BEGIN{exit !(t<d)}'; then
    ffmpeg -v error -y -ss "$t" -i "$VIDEO" -frames:v 1 "$OUT/frames/t_${t}s.png"
    ffmpeg -v error -y -i "$OUT/frames/t_${t}s.png" -vf "scale=360:-2" "$OUT/phone/t_${t}s_360w.png"
    echo "frame ${t}s -> $OUT/frames/t_${t}s.png  (phone: $OUT/phone/t_${t}s_360w.png)"
  fi
done

# ---------- scene cuts ----------
echo; echo "=== CUTS ==="
CUTS_FILE="$OUT/cuts.txt"
# Detect on a 4fps downsampled stream: hard cuts AND soft transitions (crossfades/slides,
# which score near 0 frame-to-frame at full fps) show up as a jump. Merge detections <0.75s apart.
ffmpeg -hide_banner -i "$VIDEO" -an -vf "fps=4,scale=320:-2,select='gt(scene,0.1)',metadata=print:file=-" -f null - 2>/dev/null \
  | grep -o 'pts_time:[0-9.]*' | cut -d: -f2 \
  | awk 'BEGIN{last=-10} { if ($1-last>=0.75) print $1; last=$1 }' > "$CUTS_FILE" || true
NCUTS=$(grep -c . "$CUTS_FILE" || true)
NSHOTS=$((NCUTS + 1))
AVG_SHOT=$(awk -v d="$DUR" -v n="$NSHOTS" 'BEGIN{printf "%.2f", d/n}')
echo "Cuts: $NCUTS  Shots: $NSHOTS  Avg shot length: ${AVG_SHOT}s"
echo "(note: very slow slides/fades may be undercounted - confirm against the contact sheet)"
[[ "$NCUTS" -gt 0 ]] && echo "Cut times (s): $(tr '\n' ' ' < "$CUTS_FILE")"

# one frame per shot: midpoint of each shot
{ echo 0; cat "$CUTS_FILE"; echo "$DUR"; } > "$OUT/.bounds"
i=0
mapfile -t B < "$OUT/.bounds"
for ((k=0; k<${#B[@]}-1; k++)); do
  mid=$(awk -v a="${B[$k]}" -v b="${B[$((k+1))]}" 'BEGIN{printf "%.3f", (a+b)/2}')
  i=$((i+1))
  ffmpeg -v error -y -ss "$mid" -i "$VIDEO" -frames:v 1 -vf "scale=480:-2" "$OUT/shots/shot_$(printf %03d $i).png"
done
rm -f "$OUT/.bounds"
COLS=4; [[ $i -lt 4 ]] && COLS=$i
ROWS=$(( (i + COLS - 1) / COLS ))
ffmpeg -v error -y -pattern_type glob -i "$OUT/shots/shot_*.png" \
  -vf "tile=${COLS}x${ROWS}:padding=6:color=black" -frames:v 1 "$OUT/contact_sheet.png"
echo "Contact sheet ($i shots): $OUT/contact_sheet.png"

# timeline sheet: one frame every N seconds (never misses a scene, unlike cut detection)
STEP=$(awk -v d="$DUR" 'BEGIN{ s=d/24; if (s<1) s=1; printf "%.2f", s }')
NT=$(awk -v d="$DUR" -v s="$STEP" 'BEGIN{ printf "%d", d/s }'); [[ "$NT" -lt 1 ]] && NT=1
TR=$(( (NT + 5) / 6 ))
ffmpeg -v error -y -i "$VIDEO" -vf "fps=1/${STEP},scale=320:-2,tile=6x${TR}:padding=4:color=black" -frames:v 1 "$OUT/timeline_sheet.png"
echo "Timeline sheet (1 frame / ${STEP}s): $OUT/timeline_sheet.png"

# ---------- first 3s motion ----------
# mean absolute frame difference over first 3s (0..255 scale via signalstats YDIF)
MOTION=$(ffmpeg -hide_banner -t 3 -i "$VIDEO" -an -vf "signalstats,metadata=print:key=lavfi.signalstats.YDIF:file=-" -f null - 2>/dev/null \
  | grep -o 'YDIF=[0-9.]*' | cut -d= -f2 | awk '{s+=$1;n++} END{ if(n) printf "%.2f", s/n; else print "0"}')
echo; echo "=== FIRST 3s ==="
echo "Avg frame difference (YDIF) in first 3s: $MOTION  (below ~1.0 = practically static)"

# ---------- audio ----------
echo; echo "=== AUDIO ==="
LUFS=""; TP=""
if [[ -n "$HAS_AUDIO" ]]; then
  LN=$(ffmpeg -hide_banner -i "$VIDEO" -vn -af loudnorm=print_format=json -f null - 2>&1 | sed -n '/^{/,/^}/p')
  LUFS=$(grep '"input_i"' <<<"$LN" | grep -o '\-\?[0-9.inf]*' | tail -1)
  TP=$(grep '"input_tp"' <<<"$LN" | grep -o '\-\?[0-9.inf]*' | tail -1)
  LRA=$(grep '"input_lra"' <<<"$LN" | grep -o '\-\?[0-9.inf]*' | tail -1)
  echo "Integrated loudness: ${LUFS} LUFS   True peak: ${TP} dBTP   Loudness range: ${LRA} LU"
  ffmpeg -v error -y -i "$VIDEO" -lavfi "showspectrumpic=s=1200x400:legend=1" "$OUT/spectrogram.png"
  echo "Spectrogram: $OUT/spectrogram.png  (look: real music = rich harmonic texture; synthesized = flat noise / repeated identical clicks)"
  ffmpeg -hide_banner -i "$VIDEO" -vn -af silencedetect=n=-45dB:d=0.5 -f null - 2>&1 \
    | grep -E 'silence_(start|end)' | sed 's/^\[[^]]*\] //' > "$OUT/silence.txt" || true
  NSIL=$(grep -c silence_start "$OUT/silence.txt" || true)
  echo "Silences (>0.5s below -45dB): $NSIL  -> $OUT/silence.txt"
else
  echo "No audio stream."
fi

# ---------- opening frame content (edge density) ----------
edge_at() { ffmpeg -hide_banner -ss "$1" -i "$VIDEO" -frames:v 1 \
  -vf "scale=540:-1,edgedetect=low=0.1:high=0.3,signalstats,metadata=print:key=lavfi.signalstats.YAVG" \
  -f null - 2>&1 | grep -o 'YAVG=[0-9.]*' | head -1 | cut -d= -f2; }
E0=$(edge_at 0); E0=${E0:-0}
E1=$(edge_at 1); E1=${E1:-0}
echo; echo "=== OPENING CONTENT ==="
echo "Edge density: frame 0 = $E0, frame 1s = $E1  (0 = empty frame; <1.5 = sparse)"

# ---------- music credits ----------
VDIR=$(cd "$(dirname "$VIDEO")" && pwd)
CREDITS=""
for c in "$VDIR/CREDITS.md" "$VDIR/../CREDITS.md" "$PWD/CREDITS.md"; do [[ -f "$c" ]] && CREDITS="$c" && break; done

# ---------- summary ----------
awk -v a="$AVG_SHOT" 'BEGIN{exit !(a>4)}' && warn "Avg shot length ${AVG_SHOT}s > 4s (slow pacing; ads 1-2.5s, explainers 2.5-4s)" \
  || pass "Avg shot length ${AVG_SHOT}s"
awk -v m="$MOTION" 'BEGIN{exit !(m<1.0)}' && warn "First 3s mostly static (YDIF $MOTION) - weak hook" \
  || pass "First 3s has motion (YDIF $MOTION)"
awk -v e="$E0" 'BEGIN{exit !(e<0.5)}' && fail "Frame 0 is empty (edge density $E0) - the thumbnail and the hook show nothing. Start on a strong, full frame" \
  || pass "Frame 0 has content (edge density $E0)"
awk -v e="$E1" 'BEGIN{exit !(e<1.5)}' && warn "Frame at 1s is sparse (edge density $E1) - hook may be too slow" || true
if [[ -z "$HAS_AUDIO" ]]; then
  warn "No audio track"
else
  if [[ "$LUFS" =~ ^-?[0-9.]+$ ]] && awk -v l="$LUFS" 'BEGIN{exit !(l<-16 || l>-12)}'; then
    fail "Loudness ${LUFS} LUFS outside -16..-12 (normalize to -14: see marketing-video.md audio recipe)"
  else pass "Loudness ${LUFS} LUFS"; fi
  if [[ "$TP" =~ ^-?[0-9.]+$ ]] && awk -v p="$TP" 'BEGIN{exit !(p>-1)}'; then
    fail "True peak ${TP} dBTP > -1 (audible clipping/distortion on phones)"
  else pass "True peak ${TP} dBTP"; fi
  if [[ -n "$CREDITS" ]]; then pass "Music/asset credits found: $CREDITS"
  else fail "Audio present but no CREDITS.md next to the video - music source and license unproven (synthesized music is forbidden)"; fi
fi
awk -v d="$DUR" 'BEGIN{exit !(d>60)}' && warn "Duration ${DUR}s > 60s - check it fits the platform" || pass "Duration ok for most platforms"

echo; echo "=== SUMMARY ==="
printf '%s\n' "${FLAGS[@]}"

# ---------- report to attach to the delivery ----------
REPORT="$OUT/qa_report.md"
{
  echo "# דוח בדיקת סרטון"
  echo
  echo "קובץ: \`$(basename "$VIDEO")\` | ${DUR}s | ${W}x${H} | חיתוכים: ${NCUTS:-?} | ממוצע לשוט: ${AVG_SHOT}s"
  echo "סאונד: ${LUFS:-אין} LUFS, שיא ${TP:-אין} dBTP"
  echo
  echo "## בדיקות אוטומטיות"
  printf -- '- %s\n' "${FLAGS[@]}"
  echo
  echo "## בדיקה ידנית (חובה למלא, עם זמן בסרטון כהוכחה)"
  echo "| סעיף | עובר? | הוכחה (שנייה / פריים) |"
  echo "|---|---|---|"
  for item in "לא פותח בלוגו, במסך פתיחה, בהתחברות או בהרשמה" \
              "ההוק מראה כאב או רגע מפתיע ב-3 השניות הראשונות" \
              "אף קומפוזיציה לא חוזרת ביותר מ-2 סצנות" \
              "אין קליפ-ארט גנרי ואין ערבוב סגנונות" \
              "מוצרים אמיתיים (לא אייקונים או מלבנים)" \
              "זום לפרט החשוב בכל מסך ממשק" \
              "כל טקסט קריא ברוחב 360px" \
              "טקסט וכפתורים מחוץ לאזורים הלא בטוחים (9:16)" \
              "המצלמה לא סטטית יותר מ-3 שניות" \
              "המוזיקה היא קטע אמיתי עם רישיון (לא סינתזה)" \
              "הגיבור הוא אדם או לקוח, לא המערכת" \
              "הנעה לפעולה ברורה בסוף"; do
    echo "| $item |  |  |"
  done
} > "$REPORT"
echo
echo "Report (attach to delivery, fill the manual table): $REPORT"
echo "NEXT: open timeline_sheet.png, contact_sheet.png, phone/*.png and spectrogram.png and LOOK at them."
if (( NFAIL > 0 )); then
  echo "RESULT: FAIL ($NFAIL) - do NOT deliver. Fix, re-render, re-run."
  exit 1
fi
echo "RESULT: no automatic failures. Delivery still requires the manual table to be fully passing."
