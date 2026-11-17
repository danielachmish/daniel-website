#!/usr/bin/env bash
# qa_doc.sh <file.pdf|.docx|.doc|.odt|.pptx|.ppt|.odp|.xlsx|.html> [outdir]
# Mandatory document QA before delivery: render every page/slide to an image so you can LOOK at it.
# Produces full-size PNGs, phone-width (360px) PNGs, a contact sheet, and prints the page count.
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <file.pdf|.docx|.pptx|.xlsx|.html> [outdir]" >&2; exit 2
fi
IN="$1"
[[ -f "$IN" ]] || { echo "File not found: $IN" >&2; exit 2; }
OUT="${2:-./qa_doc_out}"
mkdir -p "$OUT/pages" "$OUT/phone"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXT="${IN##*.}"; EXT="${EXT,,}"
BASE="$(basename "${IN%.*}")"

have() { command -v "$1" >/dev/null 2>&1; }
SOFFICE=""; have soffice && SOFFICE=soffice; [[ -z "$SOFFICE" ]] && have libreoffice && SOFFICE=libreoffice

PDF=""
case "$EXT" in
  pdf)
    PDF="$IN" ;;
  docx|doc|odt|rtf|pptx|ppt|odp|xlsx|xls|ods)
    if [[ -z "$SOFFICE" ]]; then
      echo "ERROR: LibreOffice (soffice) is not installed - cannot render .$EXT."
      echo "Fallback: export the file to PDF yourself and run this script on the PDF."
      exit 3
    fi
    echo "Converting .$EXT -> PDF with LibreOffice..."
    # separate profile dir avoids lock conflicts with any running instance
    PROFILE="$(mktemp -d)"
    "$SOFFICE" -env:UserInstallation="file://$PROFILE" --headless --convert-to pdf --outdir "$OUT" "$IN" >/dev/null 2>&1 || true
    rm -rf "$PROFILE"
    PDF="$OUT/$BASE.pdf"
    [[ -f "$PDF" ]] || { echo "ERROR: LibreOffice conversion failed for $IN"; exit 3; }
    echo "Note: LibreOffice rendering can differ slightly from Word/PowerPoint (fonts, spacing)." ;;
  html|htm)
    have node || { echo "ERROR: node not installed - cannot render HTML."; exit 3; }
    echo "Rendering HTML to PDF with Playwright (A4, backgrounds on)..."
    PDF="$OUT/$BASE.pdf"
    NODE_PATH="${NODE_PATH:-}" node - "$IN" "$PDF" <<'JS'
const { chromium } = require('playwright');
const path = require('path'); const { pathToFileURL } = require('url');
(async () => {
  const [inFile, outPdf] = process.argv.slice(2);
  const b = await chromium.launch(); const p = await b.newPage();
  await p.goto(pathToFileURL(path.resolve(inFile)).href, { waitUntil: 'networkidle' });
  await p.pdf({ path: outPdf, format: 'A4', printBackground: true });
  await b.close();
})().catch(e => { console.error(e.message); process.exit(3); });
JS
    ;;
  *)
    echo "ERROR: unsupported type .$EXT (supported: pdf docx doc odt rtf pptx ppt odp xlsx xls ods html)"; exit 2 ;;
esac

have pdftoppm || { echo "ERROR: pdftoppm (poppler-utils) not installed - cannot rasterize PDF. PDF is at: $PDF"; exit 3; }

PAGES=""
have pdfinfo && PAGES=$(pdfinfo "$PDF" 2>/dev/null | awk '/^Pages:/{print $2}')
echo "Rendering pages..."
pdftoppm -r 110 -png "$PDF" "$OUT/pages/page"
mapfile -t IMGS < <(ls "$OUT"/pages/page-*.png | sort -V)
[[ -z "$PAGES" ]] && PAGES=${#IMGS[@]}

for img in "${IMGS[@]}"; do
  ffmpeg -v error -y -i "$img" -vf "scale=360:-2" "$OUT/phone/$(basename "$img" .png)_360w.png" 2>/dev/null \
    || { have convert && convert "$img" -resize 360x "$OUT/phone/$(basename "$img" .png)_360w.png"; }
done

# contact sheet
N=${#IMGS[@]}
if have montage; then
  montage "${IMGS[@]}" -thumbnail 400x -tile 4x -geometry +6+6 -background '#333' "$OUT/contact_sheet.png" 2>/dev/null || true
elif have ffmpeg; then
  COLS=4; [[ $N -lt 4 ]] && COLS=$N; ROWS=$(( (N + COLS - 1) / COLS ))
  ffmpeg -v error -y -i "$OUT/pages/page-%0${#N}d.png" -vf "scale=400:-2,tile=${COLS}x${ROWS}:padding=6" -frames:v 1 "$OUT/contact_sheet.png" 2>/dev/null || true
fi

echo
echo "=== RESULT ==="
echo "Source:        $IN"
echo "PDF:           $PDF"
echo "Pages/slides:  $PAGES"
echo "Full pages:    $OUT/pages/"
echo "Phone (360w):  $OUT/phone/"
[[ -f "$OUT/contact_sheet.png" ]] && echo "Contact sheet: $OUT/contact_sheet.png"
if have pdffonts; then
  MISSING=$(pdffonts "$PDF" 2>/dev/null | awk 'NR>2 && $(NF-4)=="no"{print $1}' | sort -u | head -5)
  [[ -n "$MISSING" ]] && echo "WARN fonts not embedded: $MISSING (may look different on the recipient's computer)"
fi
echo
echo "NEXT: open the contact sheet and every page and LOOK: overflowing text, broken RTL/Hebrew,"
echo "missing fonts, empty pages, tables cut off, slide text too small, consistent styling."
