#!/usr/bin/env python3
"""qa_image.py - technical QA for static creatives (social posts, stories, carousels, banners, ad images).

Usage: python3 -I qa_image.py <dir|img.png ...> [--out <qa_dir>]
Checks every PNG/JPG and exits 1 if anything FAILs:
  1. Dimensions match a known platform format (and the format the image was rendered for).
  2. Text contrast >= 4.5:1, measured on real pixels: the text colour against the background render with the text
     hidden (<name>.bg.png). 90% of the background pixels under every text line must pass.
  3. Every text line and the logo sit inside the platform safe zone (story: top 14%, bottom 35%, sides 6%).
  4. Minimum text size relative to the canvas, and a headline big enough to read at phone size.
  5. No overflowing/clipped text, no overlapping text blocks, fonts actually loaded, real product photos not
     upscaled past 1.5x (blurry).
  WARN only: text area over 25% of the canvas, too many words, file over 5 MB.
Checks 2-5 need the <name>.layout.json sidecar written by templates/social-graphics/render.mjs (in <dir>/.qa/).
Without it only dimensions are checked and the report says so: then measure text by hand.
Always writes: <name>_phone.png (360 px wide), <name>_overlay.png (safe zone + text boxes), contact_sheet.png,
blur_sheet.png (hierarchy squint test) and qa_report.md. LOOK at them; this script does not judge design.
Needs: numpy, pillow.
"""
import sys, os, json, re, glob
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

FORMATS = {  # keep in sync with templates/social-graphics/formats.json
    'feed-4x5': (1080, 1350, (0.06, 0.05, 0.06, 0.05), 32, 60),
    'square-1x1': (1080, 1080, (0.06, 0.06, 0.06, 0.06), 32, 60),
    'story-9x16': (1080, 1920, (0.06, 0.14, 0.06, 0.35), 40, 80),
    'banner-web': (1920, 800, (0.08, 0.10, 0.08, 0.10), 30, 72),
    'landscape-191': (1200, 628, (0.06, 0.07, 0.06, 0.07), 26, 48),
    'google-square': (1200, 1200, (0.06, 0.06, 0.06, 0.06), 34, 64),
    'google-portrait': (960, 1200, (0.06, 0.05, 0.06, 0.05), 30, 56),
    'profile': (400, 400, (0.15, 0.15, 0.15, 0.15), 0, 0),
}

def font(sz):
    for p in ['/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', '/System/Library/Fonts/Supplemental/Arial Bold.ttf', 'C:/Windows/Fonts/arialbd.ttf']:
        if os.path.exists(p): return ImageFont.truetype(p, sz)
    return ImageFont.load_default()

def lin(c):
    c = c / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)

def lum(rgb):
    rgb = np.asarray(rgb, float)
    l = lin(rgb)
    return 0.2126 * l[..., 0] + 0.7152 * l[..., 1] + 0.0722 * l[..., 2]

def parse_color(s):
    n = [float(x) for x in re.findall(r'[\d.]+', s)]
    return (n[0], n[1], n[2], n[3] if len(n) > 3 else 1.0)

def overlap(a, b):
    x0, y0 = max(a[0], b[0]), max(a[1], b[1]); x1, y1 = min(a[0] + a[2], b[0] + b[2]), min(a[1] + a[3], b[1] + b[3])
    return max(0, x1 - x0) * max(0, y1 - y0)

def check(path, qa_dir):
    name = os.path.splitext(os.path.basename(path))[0]
    im = Image.open(path).convert('RGB'); W, H = im.size; res = []
    def add(level, msg): res.append((level, msg))
    side = os.path.join(os.path.dirname(path), '.qa', name + '.layout.json')
    meta = json.load(open(side)) if os.path.exists(side) else None
    # 1. dimensions
    if meta:
        fmt = meta['format']; safe = meta['safe']; min_t, head_min = meta['minText'], meta['headlineMin']
        if (W, H) != (meta['w'], meta['h']): add('FAIL', f'size {W}x{H} but format {fmt} is {meta["w"]}x{meta["h"]}')
        else: add('PASS', f'size {W}x{H} = {fmt}')
    else:
        hit = [k for k, v in FORMATS.items() if (v[0], v[1]) == (W, H)]
        if not hit: add('FAIL', f'size {W}x{H} matches no platform format ({", ".join(f"{v[0]}x{v[1]}" for v in FORMATS.values())})'); fmt = None
        else: fmt = hit[0]; add('PASS', f'size {W}x{H} = {fmt}')
        if fmt:
            l, t, r, b = FORMATS[fmt][2]; safe = [round(l * W), round(t * H), round(W * (1 - r)), round(H * (1 - b))]
        else: safe = [0, 0, W, H]
        add('WARN', 'no layout.json sidecar: contrast/safe-zone/text-size NOT measured. Render with templates/social-graphics or check by hand')
    if os.path.getsize(path) > 5 * 1024 * 1024: add('WARN', f'file {os.path.getsize(path) / 1e6:.1f} MB (Google image assets max 5 MB)')

    boxes = []  # for overlay: (rect, ok)
    if meta:
        bgp = os.path.join(os.path.dirname(path), '.qa', name + '.bg.png')
        bg = np.asarray(Image.open(bgp).convert('RGB')).astype(float) if os.path.exists(bgp) else None
        if bg is None: add('WARN', 'no background render: contrast not measured')
        if not meta.get('fontsOk', True): add('FAIL', 'brand font did not load (fallback font in render)')
        for o in meta.get('overflow', []): add('FAIL', f'text overflows its box: "{o}"')
        sx0, sy0, sx1, sy1 = safe
        # ink check: every pixel that changes when text is hidden (glyphs, text-coloured marks, CTA arrows) must be
        # inside the safe zone. Catches glyph overshoot that line boxes miss (italic/skewed marks, tight tracking).
        if bg is not None:
            fgimg = np.asarray(im).astype(float)
            ink = np.abs(fgimg - bg).max(2) > 48
            out_ink = ink.copy(); out_ink[sy0:sy1, sx0:sx1] = False
            if out_ink.sum() > 40:
                ys, xs = np.nonzero(out_ink)
                add('FAIL', f'text ink outside safe zone: {int(out_ink.sum())} px around x={xs.min()}-{xs.max()}, y={ys.min()}-{ys.max()}')
        words = 0; heads = []
        for t in meta['texts']:
            role, size, txt = t['role'], t['size'], t['text']
            if role != 'legal': words += len(txt.split())
            if role == 'headline': heads.append(size)
            label = txt[:28]
            ok = True
            # 4. size
            lim = min_t  # no exemption for legal/fine print: if it must be read, it must be readable on a phone
            if size < lim: add('FAIL', f'text {size:.0f}px < {lim:.0f}px min ({role}): "{label}"'); ok = False
            # 3. safe zone
            for (x, y, w, h) in t['lines']:
                if x < sx0 - 2 or y < sy0 - 2 or x + w > sx1 + 2 or y + h > sy1 + 2:
                    add('FAIL', f'text outside safe zone at ({x},{y},{w}x{h}): "{label}"'); ok = False; break
            # 2. contrast on real pixels
            if bg is not None:
                r, g, b_, a = parse_color(t['color'])
                worst = 99.0
                for (x, y, w, h) in t['lines']:
                    x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
                    if x1 <= x0 or y1 <= y0: continue
                    px = bg[y0:y1, x0:x1].reshape(-1, 3)
                    fg = np.array([r, g, b_]) * a + np.median(px, 0) * (1 - a)
                    lf, lb = lum(fg), lum(px)
                    cr = (np.maximum(lf, lb) + 0.05) / (np.minimum(lf, lb) + 0.05)
                    worst = min(worst, float(np.percentile(cr, 10)))
                if worst < 4.5: add('FAIL', f'contrast {worst:.2f}:1 < 4.5 ({role}): "{label}"'); ok = False
                elif worst < 99: res.append(('INFO', f'contrast {worst:.1f}:1 "{label}"'))
            boxes += [((x, y, w, h), ok) for (x, y, w, h) in t['lines']]
        if heads and max(heads) < head_min: add('FAIL', f'largest headline {max(heads):.0f}px < {head_min}px (unreadable at phone size)')
        if not heads: add('WARN', 'no element marked data-role="headline": hierarchy not checked')
        # overlapping text blocks
        T = meta['texts']
        for i in range(len(T)):
            for j in range(i + 1, len(T)):
                if T[i].get('block') is not None and T[i].get('block') == T[j].get('block'): continue
                for a_ in T[i]['lines']:
                    for b2 in T[j]['lines']:
                        ov = overlap(a_, b2)
                        if ov > 0.02 * min(a_[2] * a_[3], b2[2] * b2[3]):
                            add('FAIL', f'text blocks overlap: "{T[i]["text"][:20]}" / "{T[j]["text"][:20]}"'); break
                        same_row = min(a_[1] + a_[3], b2[1] + b2[3]) - max(a_[1], b2[1]) > 0.5 * min(a_[3], b2[3])
                        gap = max(b2[0] - (a_[0] + a_[2]), a_[0] - (b2[0] + b2[2]))
                        if same_row and 0 <= gap < 16 and ov == 0:
                            add('FAIL', f'text blocks touch ({gap}px apart, need 16+): "{T[i]["text"][:20]}" / "{T[j]["text"][:20]}"'); break
                    else: continue
                    break
        # images
        for imr in meta.get('images', []):
            if not imr['ok']: add('FAIL', f'image failed to load: {imr["src"]}')
            if imr['role'] == 'logo':
                x, y, w, h = imr['rect']
                if x < sx0 - 2 or y < sy0 - 2 or x + w > sx1 + 2 or y + h > sy1 + 2: add('FAIL', 'logo outside safe zone')
                if h < 0.03 * min(W, H): add('WARN', f'logo only {h}px high, may be unreadable on a phone')
            if imr['role'] == 'product':
                if imr['scale'] > 1.5: add('FAIL', f'product photo upscaled {imr["scale"]}x (blurry): {imr["src"]} - use a larger source or show it smaller')
                elif imr['scale'] > 1.2: add('WARN', f'product photo upscaled {imr["scale"]}x: {imr["src"]}')
        # text area ratio and word count
        mask = np.zeros((H, W), bool)
        for t in meta['texts']:
            for (x, y, w, h) in t['lines']: mask[max(0, y):y + h, max(0, x):x + w] = True
        ratio = mask.mean()
        add('WARN' if ratio > 0.25 else 'PASS', f'text covers {ratio * 100:.0f}% of the canvas (Meta: less text tends to deliver better)')
        if words > 18: add('WARN', f'{words} words on the image (aim for <= 7-10 in the main message; move detail to the caption)')
        if all(l != 'FAIL' for l, _ in res): add('PASS', 'text size, safe zone and contrast measured')

    # previews
    ph = im.resize((360, round(H * 360 / W)), Image.LANCZOS); ph.save(os.path.join(qa_dir, name + '_phone.png'))
    ov = im.copy().convert('RGBA'); lay = Image.new('RGBA', ov.size, (0, 0, 0, 0)); d = ImageDraw.Draw(lay)
    sx0, sy0, sx1, sy1 = safe
    for rect in [(0, 0, W, sy0), (0, sy1, W, H), (0, sy0, sx0, sy1), (sx1, sy0, W, sy1)]:
        if rect[2] > rect[0] and rect[3] > rect[1]: d.rectangle(rect, fill=(255, 0, 0, 70))
    for (x, y, w, h), ok in boxes: d.rectangle((x, y, x + w, y + h), outline=(0, 255, 0, 255) if ok else (255, 0, 0, 255), width=3)
    Image.alpha_composite(ov, lay).convert('RGB').save(os.path.join(qa_dir, name + '_overlay.png'))
    return name, fmt, res, ph

def sheet(items, path, blur=False):
    cols = min(4, len(items)); rows = (len(items) + cols - 1) // cols
    th = max(p.height for _, _, _, p in items); cw, ch = 380, th + 60
    out = Image.new('RGB', (cols * cw + 20, rows * ch + 20), (235, 235, 235)); d = ImageDraw.Draw(out)
    for i, (name, fmt, res, p) in enumerate(items):
        x, y = 20 + (i % cols) * cw, 20 + (i // cols) * ch
        q = p.filter(ImageFilter.GaussianBlur(6)) if blur else p
        out.paste(q, (x, y)); fail = any(l == 'FAIL' for l, _ in res)
        d.text((x, y + p.height + 6), name[:40], fill=(20, 20, 20), font=font(14))
        d.text((x, y + p.height + 26), 'FAIL' if fail else 'PASS', fill=(200, 0, 0) if fail else (0, 130, 0), font=font(16))
    out.save(path)

def main():
    a = sys.argv[1:]
    if not a or a[0] in ('-h', '--help'): print(__doc__); sys.exit(0)
    out = a[a.index('--out') + 1] if '--out' in a else None
    if '--out' in a: i = a.index('--out'); a = a[:i] + a[i + 2:]
    files = []
    for x in a:
        if os.path.isdir(x): files += sorted(glob.glob(os.path.join(x, '*.png')) + glob.glob(os.path.join(x, '*.jpg')))
        else: files.append(x)
    if not files: print('FAIL: no images found'); sys.exit(1)
    qa_dir = out or os.path.join(os.path.dirname(os.path.abspath(files[0])), 'qa')
    os.makedirs(qa_dir, exist_ok=True)
    items = [check(f, qa_dir) for f in files]
    sheet(items, os.path.join(qa_dir, 'contact_sheet.png')); sheet(items, os.path.join(qa_dir, 'blur_sheet.png'), blur=True)
    nfail = 0; md = ['# QA report (qa_image.py)', '', '| image | format | result | details |', '|---|---|---|---|']
    for name, fmt, res, _ in items:
        fails = [m for l, m in res if l == 'FAIL']; warns = [m for l, m in res if l == 'WARN']
        nfail += len(fails); status = 'FAIL' if fails else ('WARN' if warns else 'PASS')
        print(f'\n== {name} ({fmt}) : {status}')
        for l, m in res:
            if l != 'INFO': print(f'  {l:4}  {m}')
        md.append(f'| {name} | {fmt} | {status} | {"<br>".join(fails + warns) or "all checks passed"} |')
    md += ['', 'Previews: *_phone.png (360px), *_overlay.png (red = outside safe zone, boxes = measured text), contact_sheet.png, blur_sheet.png.',
           'Technical checks only. Design, message and facts are judged by an independent critic against the rubric in references/visuals.md.']
    open(os.path.join(qa_dir, 'qa_report.md'), 'w').write('\n'.join(md) + '\n')
    print(f'\n{len(items)} image(s), {nfail} FAIL. Report + previews: {qa_dir}')
    sys.exit(1 if nfail else 0)

if __name__ == '__main__':
    main()
