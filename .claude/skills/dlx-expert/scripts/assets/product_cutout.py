"""product_cutout.py - cut real product photos (pack shots on white) out of their background, for use on any
background in videos and graphics. Removes border-connected white and light-grey shadow, the hanger hole near the
top, and stray specks. Keeps white parts inside the product (e.g. a white charger behind a window).
Usage: python3 -I product_cutout.py <outdir> <img1.png> [img2.png ...]   (needs numpy, pillow, scipy)
ALWAYS check the result on a dark background: thin white parts touching the edge (e.g. a white cable in a
clear window) can be lost - if so, use another product shot."""
import sys, numpy as np
from PIL import Image, ImageFilter
from scipy import ndimage
for src in sys.argv[2:]:
    im=Image.open(src).convert('RGB'); a=np.asarray(im).astype(int)
    mx=a.max(2); mn=a.min(2); sat=mx-mn
    H=a.shape[0]
    light=(mn>150)&(sat<22)          # white bg + light grey shadow
    lab,n=ndimage.label(light)
    border=set(np.unique(np.concatenate([lab[0],lab[-1],lab[:,0],lab[:,-1]])))-{0}
    bg=np.isin(lab,list(border))
    # enclosed light holes near the top (hanger hole) are background too
    white=(mn>200)&(sat<20)
    wl,wn=ndimage.label(white&~bg)
    for i,sl in enumerate(ndimage.find_objects(wl),1):
        cy=(sl[0].start+sl[0].stop)/2
        if cy<0.2*H and (wl[sl]==i).sum()>30: bg|=(wl==i)
    keep=ndimage.binary_opening(~bg,iterations=1)
    # keep only the largest connected object (drops stray shadow specks)
    kl,kn=ndimage.label(keep)
    if kn>1:
        sizes=ndimage.sum(keep,kl,range(1,kn+1)); keep=kl==(1+int(np.argmax(sizes)))
    keep=ndimage.binary_fill_holes(keep) & ~((~keep)&bg)
    alpha=Image.fromarray((keep*255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.7))
    out=im.convert('RGBA'); out.putalpha(alpha); out=out.crop(out.getbbox())
    name=src.rsplit('/',1)[-1].replace('.png','_cut.png'); out.save(sys.argv[1]+'/'+name); print(name,out.size)
