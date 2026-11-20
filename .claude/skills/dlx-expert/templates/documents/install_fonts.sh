#!/usr/bin/env bash
# install_fonts.sh - install the document design fonts (Heebo, Assistant, Frank Ruhl Libre; SIL OFL 1.1)
# so LibreOffice renders and embeds them in the PDF. Without this, PDFs fall back to DejaVu and look amateur.
set -euo pipefail
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/fonts"
DEST="${HOME}/.fonts"
mkdir -p "$DEST"
cp "$SRC"/*.ttf "$DEST"/
command -v fc-cache >/dev/null && fc-cache -f "$DEST" >/dev/null
if command -v fc-list >/dev/null; then
  FAMS="$(fc-list : family)"
  for f in Heebo Assistant "Frank Ruhl Libre"; do
    if grep -q "$f" <<<"$FAMS"; then echo "OK   $f"; else echo "FAIL $f not visible to fontconfig"; exit 1; fi
  done
fi
