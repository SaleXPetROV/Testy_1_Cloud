"""Turn a building picture into a city-map sprite (same pipeline as tools/art/process_owner_art.py):
dark opaque background cut by silhouette (glow kept, watermark dropped) — or a transparent PNG
taken as is — then the foundation is found and placed on the same anchor as all sprites."""
import io
from typing import Dict, Tuple

import numpy as np
from PIL import Image

CANVAS = {1: (400, 500), 2: (512, 640), 3: (640, 800),     # bigger than before: crisp on high-DPI phones
          'park1': (512, 512), 'park2': (1024, 1024)}            # park pictures 1x1 / 2x2 (square, like parks/manifest.json)
WIDE = {'chips_factory', 'ai_lab', 'nft_studio', 'logistics_hub', 'cyber_cafe', 'vr_club', 'repair_shop'}


def cutout(im: Image.Image, t_low=26, t_high=70, band=4, close=7) -> Image.Image:
    from scipy import ndimage as ndi
    a = np.asarray(im.convert('RGB')).astype(np.float32)
    H, W, _ = a.shape
    border = np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]])
    bg = np.median(border, axis=0)
    dist = np.abs(a - bg).max(axis=2)
    lum = a.mean(axis=2)
    cand = (dist < t_low) & (lum < 40)
    lab, _n = ndi.label(cand)
    edge = np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))
    bgmask = np.isin(lab, edge[edge > 0])
    st = ndi.generate_binary_structure(2, 1)
    sil = ndi.binary_fill_holes(ndi.binary_closing(~bgmask, structure=st, iterations=close))
    sil &= ~ndi.binary_erosion(bgmask, iterations=close + 2)
    sil = ndi.binary_fill_holes(sil)
    alpha = np.zeros((H, W), np.float32); alpha[sil] = 1
    ring = ndi.binary_dilation(sil, iterations=band) & ~sil
    alpha[ring] = np.clip((dist - t_low) / (t_high - t_low), 0, 1)[ring]
    solid = alpha > 0.35
    lab2, n2 = ndi.label(ndi.binary_dilation(solid, iterations=6))
    if n2 > 1:
        keep = 1 + int(np.argmax(ndi.sum(solid, lab2, range(1, n2 + 1))))
        alpha[lab2 != keep] = 0
    rgb = a.copy(); f = (alpha > 0) & (alpha < 1); k = alpha[f][:, None]
    rgb[f] = np.clip((a[f] - bg * (1 - k)) / np.maximum(k, 0.15), 0, 255)
    return Image.fromarray(np.dstack([rgb, alpha * 255]).astype(np.uint8), 'RGBA')


def _foundation(alpha):
    m = alpha > 128; rows = m.sum(axis=1); ys = np.where(rows > 0)[0]
    top, maxw = ys[0], rows.max()
    bottom = ys[rows[ys] > maxw * 0.22][-1]
    lower = m[int(bottom - (bottom - top) * 0.45):bottom + 1]
    cols = np.where(lower.any(axis=0))[0]
    return top, bottom, cols[0], cols[-1]


def place(rgba: Image.Image, tier: int, wide: bool) -> Tuple[Image.Image, Dict]:
    W, H = CANVAS.get(tier, CANVAS[1])
    top, bottom, left, right = _foundation(np.asarray(rgba)[..., 3])
    fw = right - left
    s = (W * 0.86) / max(1, fw)
    bottom_y = H * 0.9
    if (bottom - top) * s > bottom_y - 4:
        s = (bottom_y - 4) / (bottom - top)
    img = rgba.resize((max(1, round(rgba.width * s)), max(1, round(rgba.height * s))), Image.LANCZOS)
    x = round(W / 2 - (left + right) / 2 * s); y = round(bottom_y - bottom * s)
    canvas = Image.new('RGBA', (W, H), (0, 0, 0, 0)); canvas.alpha_composite(img, (x, y))
    fwp = fw * s
    return canvas, {'size': [W, H], 'footprint_width': round(fwp / W, 4), 'anchor': [0.5, round((bottom_y - fwp / 4) / H, 4)],
                    'top': round(max(0, (y + top * s)) / H, 4), 'long_axis': 'y' if wide else None}


def make_sprite(raw: bytes, tier: int, sprite_type: str, mirror: bool = False) -> Tuple[bytes, Dict]:
    im = Image.open(io.BytesIO(raw))
    im.load()
    rgba = im.convert('RGBA')
    a = np.asarray(rgba)[..., 3]
    transparent = (a < 16).mean() > 0.05            # a PNG with a transparent background: take it as is
    cut = rgba if transparent else cutout(im)
    if mirror:
        cut = cut.transpose(Image.FLIP_LEFT_RIGHT)
    img, meta = place(cut, tier, sprite_type in WIDE)
    if mirror and meta['long_axis']:
        meta['long_axis'] = 'x'
    buf = io.BytesIO(); img.save(buf, 'WEBP', quality=90, method=6)
    return buf.getvalue(), meta
