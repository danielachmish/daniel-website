#!/usr/bin/env python3
"""הכנת תמונות לאתר: WebP בשני גדלים (רגיל וחד לרטינה), חיתוך שוליים שקופים, ותמונת שיתוף (OG).

שימוש:
  python3 tools/prepare_images.py products <out_dir> <img1.png> [img2.png ...] [--width 320]
      יוצר <name>-<w>.webp ו-<name>-<2w>.webp, ומדפיס תגית <img> מוכנה עם srcset, width ו-height.
  python3 tools/prepare_images.py og <out.jpg> --logo logo.png --bg "#0b0c0d" --accent "#84cc2d" <product1.png> [product2.png ...]
      תמונת שיתוף 1200x630: לוגו + עד 3 מוצרים על רקע המותג.
דרישות: Pillow (pip install pillow).
"""
import sys, os, argparse
from PIL import Image, ImageDraw, ImageFilter


def trim(im):
    if im.mode != 'RGBA':
        return im
    box = im.getchannel('A').point(lambda a: 255 if a > 8 else 0).getbbox()
    return im.crop(box) if box else im


def products(args):
    os.makedirs(args.out, exist_ok=True)
    for src in args.files:
        im = trim(Image.open(src).convert('RGBA'))
        name = os.path.splitext(os.path.basename(src))[0].replace('_cut', '')
        outs = []
        # לא מגדילים מעבר למקור: 1x ו-2x חתוכים לרוחב המקורי
        for w in sorted({min(args.width, im.width), min(args.width * 2, im.width)}):
            h = round(im.height * w / im.width)
            p = os.path.join(args.out, f'{name}-{w}.webp')
            im.resize((w, h), Image.LANCZOS).save(p, 'WEBP', quality=82, method=6)
            outs.append((p, w, h))
        (p1, w1, h1), (p2, w2, _) = outs[0], outs[-1]
        kb = sum(os.path.getsize(p) for p, _, _ in outs) // 1024
        if w2 == w1:
            print(f'<!-- {name}: {kb}KB. המקור קטן מ-2x: אין גרסת רטינה. עדיף מקור ברזולוציה גבוהה יותר -->')
        else:
            print(f'<!-- {name}: {kb}KB -->')
        print(f'<img src="assets/img/{os.path.basename(p1)}" srcset="assets/img/{os.path.basename(p1)} {w1}w, '
              f'assets/img/{os.path.basename(p2)} {w2}w" sizes="(min-width: 75em) 16rem, 60vw" '
              f'width="{w1}" height="{h1}" alt="" loading="lazy" decoding="async">')


def hex2rgb(h):
    h = h.lstrip('#')
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def og(args):
    W, H = 1200, 630
    bg = hex2rgb(args.bg)
    acc = hex2rgb(args.accent)
    canvas = Image.new('RGB', (W, H), bg)
    glow = Image.new('L', (W, H), 0)
    ImageDraw.Draw(glow).ellipse((620, 40, 1240, 700), fill=120)
    glow = glow.filter(ImageFilter.GaussianBlur(120))
    canvas.paste(Image.new('RGB', (W, H), acc), (0, 0), glow)
    d = ImageDraw.Draw(canvas)
    for i, x in enumerate((760, 880)):  # פסים אלכסוניים (רכיב חתימה)
        d.polygon([(x + 120, 60), (x + 200, 60), (x + 80, 600), (x, 600)], fill=acc if i == 0 else tuple(int(c * 0.55 + b * 0.45) for c, b in zip(acc, bg)))
    items = [trim(Image.open(p).convert('RGBA')) for p in args.files[:3]]
    slots = [(820, 470, 0), (690, 400, -6), (960, 400, 6)] if len(items) >= 3 else [(840, 480, 0)] * len(items)
    order = [1, 2, 0] if len(items) >= 3 else range(len(items))
    for idx in order:
        im = items[idx]; cx, h, rot = slots[idx]
        im = im.resize((round(im.width * h / im.height), h), Image.LANCZOS).rotate(rot, expand=True, resample=Image.BICUBIC)
        canvas.paste(im, (cx - im.width // 2, H - im.height + 40), im)
    if args.logo:
        lg = trim(Image.open(args.logo).convert('RGBA'))
        lw = 460
        lg = lg.resize((lw, round(lg.height * lw / lg.width)), Image.LANCZOS)
        canvas.paste(lg, (70, 80), lg)
    canvas.save(args.out, 'JPEG', quality=86, optimize=True, progressive=True)
    print(f'OG image: {args.out} ({os.path.getsize(args.out) // 1024}KB). הוסיפו כותרת בעברית בעורך תמונות אם צריך.')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    a = sub.add_parser('products'); a.add_argument('out'); a.add_argument('files', nargs='+'); a.add_argument('--width', type=int, default=320)
    b = sub.add_parser('og'); b.add_argument('out'); b.add_argument('files', nargs='*'); b.add_argument('--logo'); b.add_argument('--bg', default='#0b0c0d'); b.add_argument('--accent', default='#2f6fed')
    args = ap.parse_args()
    products(args) if args.cmd == 'products' else og(args)
