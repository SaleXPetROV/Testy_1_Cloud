import json, os, sys
import numpy as np
from PIL import Image
sys.path.insert(0, os.path.dirname(__file__))
from cutout import cutout
SRC = (sys.argv[1] if len(sys.argv) > 1 else 'art/source') + '/'
OUT = os.path.join(os.path.dirname(__file__), '../../frontend/public/sprites/city')
MAP = {   # ONE picture per business (all growth stages use it); change a file name here to pick another
 'helios': 'helios-1.png', 'nano_dc': 'Nano-1.png', 'quartz_mine': 'Quarz-1.png', 'signal_tower': 'signal-1.png',
 'hydro_cooling': 'cold-1.png', 'bio_farm': 'bio-1.png', 'scrap_yard': 'scrap-1.png',
 'chips_factory': 'chip-2.png', 'ai_lab': 'ai-2.png', 'nft_studio': 'nft-2.png', 'logistics_hub': 'logistics.png',
 'cyber_cafe': 'cafe-1.png', 'vr_club': 'vr-1.png', 'repair_shop': 'repair.png',
 'validator': 'Validator.png', 'gram_bank': '1791383713772254312_167876733_0.png', 'dex': 'DEX.png',
 'casino': 'casino.png', 'arena': 'arena.png', 'incubator': 'Incubator.png',
}
# 1x2 lots exist in both orientations on the map: these get a second (mirrored) view, "*_alt.webp".
# Mirroring flips the neon lettering — the owner fixes the text on art/second_view/<type>.png and re-runs.
ALT = {'cyber_cafe', 'vr_club', 'repair_shop'}
CANVAS = {1: (400, 500), 2: (512, 640), 3: (640, 800)}   # same as backend/core/sprite_art.py
WIDE = {'chips_factory', 'ai_lab', 'nft_studio', 'logistics_hub', 'cyber_cafe', 'vr_club', 'repair_shop'}

def foundation(alpha):
    """bottom tip row and foundation width from the opaque mask (robust to thin spikes)."""
    m = alpha > 128; rows = m.sum(axis=1); ys = np.where(rows > 0)[0]
    top, maxw = ys[0], rows.max()
    bottom = ys[rows[ys] > maxw * 0.22][-1]                  # lowest row that is still "foundation-wide"
    h = bottom - top
    lower = m[int(bottom - h * 0.45):bottom + 1]
    cols = np.where(lower.any(axis=0))[0]
    left, right = cols[0], cols[-1]
    return top, bottom, left, right

def place(rgba, tier, wide):
    W, H = CANVAS[tier]
    a = np.asarray(rgba)[..., 3]
    top, bottom, left, right = foundation(a)
    fw = right - left
    s = (W * 0.86) / fw                                       # foundation = 86% of the canvas width
    bottom_y = H * 0.9
    if (bottom - top) * s > bottom_y - 4:                     # very tall: shrink to fit
        s = (bottom_y - 4) / (bottom - top)
    img = rgba.resize((max(1, round(rgba.width * s)), max(1, round(rgba.height * s))), Image.LANCZOS)
    cx_src = (left + right) / 2
    x = round(W / 2 - cx_src * s); y = round(bottom_y - bottom * s)
    canvas = Image.new('RGBA', (W, H), (0, 0, 0, 0)); canvas.alpha_composite(img, (x, y))
    fwp = fw * s
    meta = {'size': [W, H], 'footprint_width': round(fwp / W, 4), 'anchor': [0.5, round((bottom_y - fwp / 4) / H, 4)],
            'top': round(max(0, (y + top * s)) / H, 4), 'long_axis': 'y' if wide else None}
    return canvas, meta

man = json.load(open(f'{OUT}/manifest.json', encoding='utf-8'))
total = 0
ALTDIR = os.path.join(os.path.dirname(__file__), '../../art/second_view')
os.makedirs(ALTDIR, exist_ok=True)
for t, f in MAP.items():
    tier = man['types'][t]['tier']; entry = man['types'][t]
    cut = cutout(SRC + f)
    img, meta = place(cut, tier, t in WIDE)
    entry['files_meta'], entry.pop('files_alt', None)
    entry['files_meta'] = {}
    for st in (1, 2, 3):
        p = f'{OUT}/{t}/stage{st}.webp'; img.save(p, 'WEBP', quality=90, method=6); total += os.path.getsize(p)
        entry['files_meta'][str(st)] = {**meta, 'source': f}
    if t in ALT:
        # second view: an owner-edited picture if present, otherwise the mirrored cut-out
        fixed = os.path.join(ALTDIR, f'{t}.png')
        if os.path.exists(fixed) and os.path.getmtime(fixed) > os.path.getmtime(SRC + f) and not os.environ.get('RESET_ALT'):
            alt_src = Image.open(fixed).convert('RGBA'); note = 'owner-edited second view'
        else:
            alt_src = cut.transpose(Image.FLIP_LEFT_RIGHT); alt_src.crop(alt_src.getbbox()).save(fixed); note = 'mirrored (text to be fixed)'
        aimg, ameta = place(alt_src, tier, t in WIDE)
        ameta['long_axis'] = 'x' if meta['long_axis'] == 'y' else 'y'
        entry['files_alt'] = {}
        for st in (1, 2, 3):
            p = f'{OUT}/{t}/stage{st}_alt.webp'; aimg.save(p, 'WEBP', quality=90, method=6); total += os.path.getsize(p)
            entry['files_alt'][str(st)] = {**ameta, 'file': f'{t}/stage{st}_alt.webp', 'source': note}
# bridge: no picture yet -> keep the code-drawn sprite, measured the same way
for st in (1, 2, 3):
    rgba = Image.open(os.path.join(os.path.dirname(__file__), f'../../docs/skins_src/bridge_stage{st}.png')).convert('RGBA')
    img, meta = place(rgba, 3, False)
    p = f'{OUT}/bridge/stage{st}.webp'; img.save(p, 'WEBP', quality=90, method=6); total += os.path.getsize(p)
    man['types']['bridge'].setdefault('files_meta', {})[str(st)] = {**meta, 'source': 'vector placeholder'}
man['style'] = 'AI-rendered cyber buildings (owner art), background removed; bridge = vector placeholder'
man['display_scale'] = {'1x1': 0.92, '1x2': 0.94, '2x2': 0.8, '3x3': 0.72}
man['note_alt'] = 'files_alt[stage]: the second orientation of 1x2 buildings (long side along the other axis) — no runtime mirroring.'
man['note'] = ('files_meta[stage]: size, footprint_width (fraction of width), anchor (lot centre on the ground), '
               'top (top of the building, for price tags), long_axis ("y" = long side to the lower-left / upper-right; '
               'mirror the image for a lot that is long along x). Admin fine-tuning is stored on the server (city_sprites).')
json.dump(man, open(f'{OUT}/manifest.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('sprites written:', 21 * 3, '| total', round(total / 1024), 'KB')
