"""logo_on_dark.py - turn a logo that is dark-on-white into a transparent PNG for dark backgrounds:
white/near-white background -> transparent, dark parts -> white, saturated brand colours kept.

Usage: python3 -I logo_on_dark.py <logo.png> <out.png> [brand_hex]
Render an SVG logo to PNG first at high resolution (e.g. Playwright screenshot at deviceScaleFactor 4).
Always look at the result on a dark background before using it.
"""
import sys
import numpy as np
from PIL import Image

src, out = sys.argv[1], sys.argv[2]
a = np.asarray(Image.open(src).convert('RGB')).astype(float)
r, g, b = a[..., 0], a[..., 1], a[..., 2]
lum = 0.299 * r + 0.587 * g + 0.114 * b
sat = a.max(2) - a.min(2)
coloured = sat > 40
alpha = np.clip((255 - lum) / 255 * 1.6, 0, 1)
alpha = np.where(coloured, np.clip(sat / 120, 0, 1), alpha)
res = np.zeros(a.shape[:2] + (4,), np.uint8)
res[..., :3] = 255
if len(sys.argv) > 3:
    h = sys.argv[3].lstrip('#')
    res[coloured, :3] = [int(h[i:i + 2], 16) for i in (0, 2, 4)]
else:
    res[coloured, :3] = a[coloured].astype(np.uint8)
res[..., 3] = (alpha * 255).astype(np.uint8)
im = Image.fromarray(res, 'RGBA')
im = im.crop(im.getbbox())
im.save(out)
print(out, im.size)
