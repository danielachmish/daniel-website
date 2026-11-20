"""product_cutout.py - cut real product photos (pack shots on white) out of their background, for use on any
background in videos and graphics. Removes border-connected white, light-grey shadow and grey cast shadows touching it, the hanger hole near the
top, and stray specks. Keeps white parts inside the product (e.g. a white charger behind a window).
Usage: python3 -I product_cutout.py <outdir> <img1.png> [img2.png ...]   (needs numpy, pillow, scipy)
ALWAYS check the result on a bright magenta background (holes show instantly) AND on a dark one: a hole inside the
product (e.g. a white cable in a clear window shown as background) is an altered product and must not ship."""
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
    # cast shadows on the backdrop (grey, unsaturated, mid-light) that touch the background are background too.
    # Grown only from the background, so light parts enclosed by the product (a white charger in a window) stay.
    shadowish=(sat<14)&(mn>132)&(mn<=215)   # >132: keeps grey box spines (~110-122)
    bg=ndimage.binary_propagation(bg,mask=bg|shadowish)
    # light parts INSIDE the product outline (a white cable behind a clear window that touches the window edge)
    # must stay: rebuild the outline from the dark packaging, close small gaps, fill it, and never treat it as bg.
    dark=mn<128
    sil=ndimage.binary_fill_holes(ndimage.binary_closing(dark,structure=np.ones((3,3)),iterations=8))
    sil=ndimage.binary_erosion(sil,iterations=2)
    bg&=~sil
    # ...except the hanger hole(s): light areas enclosed by the hanger in the top 22% stay transparent
    hl,hn=ndimage.label(light&~bg)
    for i,sl in enumerate(ndimage.find_objects(hl),1):
        if (sl[0].start+sl[0].stop)/2<0.22*H and (hl[sl]==i).sum()>30: bg|=(hl==i)
    keep=ndimage.binary_opening(~bg,iterations=1)
    # keep only the largest connected object (drops stray shadow specks)
    kl,kn=ndimage.label(keep)
    if kn>1:
        sizes=ndimage.sum(keep,kl,range(1,kn+1)); keep=kl==(1+int(np.argmax(sizes)))
    keep=ndimage.binary_fill_holes(keep) & ~((~keep)&bg)
    alpha=Image.fromarray((keep*255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.7))
    out=im.convert('RGBA'); out.putalpha(alpha); out=out.crop(out.getbbox())
    name=src.rsplit('/',1)[-1].replace('.png','_cut.png'); out.save(sys.argv[1]+'/'+name); print(name,out.size)
