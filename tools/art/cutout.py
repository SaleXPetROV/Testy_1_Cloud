"""Cut a building out of a dark, opaque AI render: background = dark area connected to the image
border (soft edge keeps the neon glow), then keep only the main object (drops the watermark)."""
import numpy as np
from PIL import Image
from scipy import ndimage as ndi

def cutout(path, t_low=26, t_high=70, band=4, close=7):
    im = Image.open(path).convert('RGB'); a = np.asarray(im).astype(np.float32)
    H, W, _ = a.shape
    border = np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]])
    bg = np.median(border, axis=0)
    dist = np.abs(a - bg).max(axis=2)                       # how different from the background colour
    lum = a.mean(axis=2)
    cand = (dist < t_low) & (lum < 40)                       # dark & close to the background
    lab, n = ndi.label(cand)
    edge = np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))
    bgmask = np.isin(lab, edge[edge > 0])
    # silhouette: close small dark gaps and fill enclosed holes, so dark walls INSIDE the building
    # are never taken for background (dark facades are close to the background colour)
    obj = ~bgmask
    st = ndi.generate_binary_structure(2, 1)
    sil = ndi.binary_closing(obj, structure=st, iterations=close)
    sil = ndi.binary_fill_holes(sil)
    sil &= ~ndi.binary_erosion(bgmask, iterations=close + 2)   # do not swallow wide background bays
    sil = ndi.binary_fill_holes(sil)
    alpha = np.zeros((H, W), np.float32)
    alpha[sil] = 1
    # soft edge just outside the silhouette (keeps neon glow, no hard cut)
    ring = ndi.binary_dilation(sil, iterations=band) & ~sil
    soft = np.clip((dist - t_low) / (t_high - t_low), 0, 1)
    alpha[ring] = soft[ring]
    # keep the main object: the largest blob (glows merged by a dilation), drops the "Oreate AI" text
    solid = alpha > 0.35
    grown = ndi.binary_dilation(solid, iterations=6)
    lab2, n2 = ndi.label(grown)
    if n2 > 1:
        sizes = ndi.sum(solid, lab2, range(1, n2 + 1)); keep = 1 + int(np.argmax(sizes))
        alpha[lab2 != keep] = 0
    # un-darken the semi-transparent fringe (background colour bleeding into the edge)
    rgb = a.copy(); f = (alpha > 0) & (alpha < 1)
    k = alpha[f][:, None]
    rgb[f] = np.clip((a[f] - bg * (1 - k)) / np.maximum(k, 0.15), 0, 255)
    out = np.dstack([rgb, alpha * 255]).astype(np.uint8)
    return Image.fromarray(out, 'RGBA')
