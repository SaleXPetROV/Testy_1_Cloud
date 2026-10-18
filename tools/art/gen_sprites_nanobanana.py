#!/usr/bin/env python3
"""Generate the 63 city building sprites with Nano Banana (Gemini 2.5 Flash Image).

    export GEMINI_API_KEY=...                      # Google AI Studio key
    python tools/art/gen_sprites_nanobanana.py --dry-run          # show the prompts only
    python tools/art/gen_sprites_nanobanana.py --only gram_bank   # one building (3 stages)
    python tools/art/gen_sprites_nanobanana.py                    # everything (skips finished files)

Pipeline per sprite
 1. prompt = shared style + building description + stage modifier + tier colour + lot size,
    on a SOLID #00FF00 background (Nano Banana has no transparency);
 2. the first finished image (Банк Gram, stage 2) is sent with every next request as a
    style / camera reference, so all 63 look like one set;
 3. chroma-key the green away (+ despill), trim, scale and place the foundation on the same
    anchor points as frontend/public/sprites/city/manifest.json -> stage<N>.webp (320x400);
 4. raw PNGs stay in art/raw/ so any picture can be re-processed or replaced by hand.
"""
import argparse, base64, io, json, os, sys, time
from pathlib import Path

import numpy as np
import requests
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
CITY = ROOT / "frontend/public/sprites/city"
RAW = ROOT / "art/raw"
MODEL = os.environ.get("NANO_BANANA_MODEL", "gemini-2.5-flash-image")
API = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"

STYLE = ("mobile strategy game building asset, Clash of Clans art style, Supercell style, stylized 3D render, "
         "chunky but elegant proportions, soft rounded bevelled edges, hand-painted textures, cyberpunk neon city theme, "
         "dark navy metal plating with rivets and panel seams, glowing neon accents in {tier_color}, "
         "the building stands on a thin square metal foundation slab, warm key light from the upper left, soft ambient occlusion, "
         "subtle colored rim light, isometric view, 2:1 isometric angle, camera 30 degrees elevation, rotated 45 degrees, "
         "single building centered, full building visible, nothing cut off, no text, no letters, no logos, no people, "
         "no ground or scenery around the foundation, on a perfectly flat solid pure green #00FF00 background")
NEGATIVE = ("Avoid: photorealism, blur, text, watermark, logos, people, cropped parts, several buildings, scenery, "
            "top-down view, side view, front view, perspective distortion, shadows on the background, gradients in the background.")
TIER_COLOR = {1: "cyan (#00F0FF)", 2: "violet (#B36BFF)", 3: "gold (#FFD84D)"}
STAGE = {1: "small early version (levels 0-3), compact, basic details, few neon lights",
         2: "upgraded version (levels 4-6), taller, more floors and equipment, more neon lights, small neon lamp posts on the foundation corners",
         3: "maximum level version (levels 7-10), tallest and most impressive, rich details, golden trims, a holographic halo ring floating above the roof"}
LOT = {"1x1": "small square 1x1 lot", "2x2": "square 2x2 lot", "1x2": "long rectangular 1x2 lot, the long side going to the lower right",
       "3x3": "large square 3x3 lot, grand landmark building"}
DESC = {
 "helios": "solar power station: tilted glowing blue solar panel arrays around a small control tower with a bright energy core on top",
 "nano_dc": "compact data center block with vertical green and cyan LED server strips on the walls, rooftop satellite dish and cooling vents",
 "quartz_mine": "crystal mine: cluster of large glowing cyan and violet quartz crystals, small mining building and a drilling derrick with a neon beam",
 "signal_tower": "telecom tower: steel lattice antenna mast emitting neon signal rings, small equipment hut at its base",
 "hydro_cooling": "cooling plant: two white cooling towers releasing glowing icy vapor, frosted pipes, small pump house",
 "bio_farm": "bio farm: glass dome greenhouse with glowing neon plants inside, hydroponic trays, green neon trim",
 "scrap_yard": "cyber scrapyard: piles of metal scrap and crates, a yellow crane with a magnet, small orange-lit workshop",
 "chips_factory": "microchip factory hall with saw-tooth roof, two chimneys with violet smoke, glowing chip emblem on the wall",
 "nft_studio": "digital art studio with big glowing gradient art frames on the walls (magenta to cyan), rooftop hologram projector",
 "ai_lab": "AI research lab with a glass dome containing a glowing holographic brain, neon flasks, server racks",
 "logistics_hub": "logistics hangar with curved roof, open gate, stacked colorful cargo containers, helipad with a delivery drone",
 "cyber_cafe": "cozy cyber cafe with magenta striped awning, neon coffee cup sign, warm window light, outdoor tables",
 "repair_shop": "mechanic garage with roller door, glowing neon wrench sign, tool racks, a small robot arm",
 "vr_club": "VR gaming club with a big neon VR headset sculpture on the roof, magenta and cyan window strips",
 "validator": "blockchain validator node: dark monolith with golden circuit lines and a glowing shield emblem, four energy pylons",
 "gram_bank": "futuristic bank: classical white columns, golden pyramid roof, glowing golden coin emblem, vault door",
 "dex": "crypto exchange tower with screens showing glowing green and red candlestick charts, rooftop beacon",
 "casino": "neon casino with a glowing marquee sign with 777, big white dice on the roof, gold windows",
 "arena": "oval cyber stadium with glowing green field, golden rim lights, floodlight masts",
 "incubator": "startup incubator: platform with large glowing egg-shaped capsules (gold, violet, mint), energy cables",
 "bridge": "cable-stayed bridge segment with two pylons and golden neon cables over a short deck",
}
REFERENCE = ("gram_bank", 2)


def prompt_for(t, meta, stage):
    return (STYLE.format(tier_color=TIER_COLOR[meta["tier"]]) + ". Building: " + DESC[t] + ". " + STAGE[stage] +
            ". Foundation: " + LOT[meta["footprint"]] + ". " + NEGATIVE)


def call_nano_banana(key, prompt, ref_png=None, retries=4):
    parts = [{"text": prompt}]
    if ref_png is not None:
        parts.insert(0, {"text": "Reference image: match its art style, camera angle, lighting, outline and level of detail exactly. "
                                  "Draw a DIFFERENT building as described below."})
        parts.insert(1, {"inline_data": {"mime_type": "image/png", "data": base64.b64encode(ref_png).decode()}})
    body = {"contents": [{"parts": parts}], "generationConfig": {"responseModalities": ["IMAGE"]}}
    for attempt in range(retries):
        r = requests.post(API, headers={"x-goog-api-key": key, "Content-Type": "application/json"}, json=body, timeout=180)
        if r.status_code == 200:
            for cand in r.json().get("candidates", []):
                for p in cand.get("content", {}).get("parts", []):
                    data = (p.get("inline_data") or p.get("inlineData") or {}).get("data")
                    if data:
                        return base64.b64decode(data)
            raise RuntimeError("no image in the response: " + r.text[:300])
        if r.status_code in (429, 500, 503):
            time.sleep(8 * (attempt + 1)); continue
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
    raise RuntimeError("too many retries")


def chroma_key(img):
    """Pure-green background -> transparency, with despill on the edges."""
    a = np.asarray(img.convert("RGB")).astype(np.float32)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    greenness = g - np.maximum(r, b)                       # how much greener than the other channels
    alpha = np.clip(1.0 - (greenness - 40) / 90.0, 0, 1)  # >130 greener -> fully transparent
    spill = np.clip(greenness, 0, None) * (alpha < 1)      # despill semi-transparent edge pixels
    g2 = np.clip(g - spill * 0.85, 0, 255)
    out = np.dstack([r, g2, b, alpha * 255]).astype(np.uint8)
    return Image.fromarray(out, "RGBA")


def normalize(img, meta):
    """Trim and place the sprite so its foundation matches the manifest anchors (320x400 canvas)."""
    W, H = 320, 400
    bbox = img.getbbox()
    if not bbox:
        raise RuntimeError("empty image after keying")
    img = img.crop(bbox)
    # the foundation is the widest part: scale so its width = footprint_width of the canvas
    target_w = meta["footprint_width"] * W
    s = target_w / img.width
    img = img.resize((max(1, round(img.width * s)), max(1, round(img.height * s))), Image.LANCZOS)
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    # bottom tip of the foundation -> same place as the code-drawn sprites
    bottom_y = round(meta["anchor"][1] * H + (meta["footprint_width"] * W) / 4.0)
    x = round(W / 2 - img.width / 2); y = bottom_y - img.height
    if y < 0:                                               # very tall building: shrink to fit
        k = bottom_y / img.height
        img = img.resize((max(1, round(img.width * k)), bottom_y), Image.LANCZOS)
        x = round(W / 2 - img.width / 2); y = 0
    canvas.alpha_composite(img, (x, y))
    return canvas


def process(raw_png, meta, out_path):
    img = chroma_key(Image.open(io.BytesIO(raw_png)))
    normalize(img, meta).save(out_path, "WEBP", quality=88, method=6)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", default="")
    ap.add_argument("--force", action="store_true", help="regenerate even if the raw file exists")
    ap.add_argument("--reprocess", action="store_true", help="only re-run keying/normalising on art/raw")
    args = ap.parse_args()
    manifest = json.loads((CITY / "manifest.json").read_text(encoding="utf-8"))
    types = [t for t in manifest["types"] if not args.only or t in args.only.split(",")]
    jobs = [REFERENCE] + [(t, s) for t in types for s in (1, 2, 3) if (t, s) != REFERENCE]
    if args.only:
        jobs = [j for j in jobs if j[0] in types]
    if args.dry_run:
        for t, s in jobs:
            print(f"--- {t} stage{s}\n{prompt_for(t, manifest['types'][t], s)}\n")
        print(f"{len(jobs)} images"); return
    key = os.environ.get("GEMINI_API_KEY")
    if not key and not args.reprocess:
        sys.exit("Set GEMINI_API_KEY (Google AI Studio).")
    RAW.mkdir(parents=True, exist_ok=True)
    ref_path = RAW / f"{REFERENCE[0]}_stage{REFERENCE[1]}.png"
    for t, s in jobs:
        meta = manifest["types"][t]
        raw = RAW / f"{t}_stage{s}.png"
        if not args.reprocess and (args.force or not raw.exists()):
            ref = ref_path.read_bytes() if ref_path.exists() and (t, s) != REFERENCE else None
            print(f"generating {t} stage{s} ...", flush=True)
            raw.write_bytes(call_nano_banana(key, prompt_for(t, meta, s), ref))
        if raw.exists():
            process(raw.read_bytes(), meta, CITY / t / f"stage{s}.webp")
            print(f"  -> {t}/stage{s}.webp")
    manifest["style"] = f"Nano Banana ({MODEL}) — Clash of Clans × cyber"
    (CITY / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done")


if __name__ == "__main__":
    main()
