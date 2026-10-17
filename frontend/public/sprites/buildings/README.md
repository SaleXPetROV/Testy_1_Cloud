# Building sprites

Optional PNG art for businesses on the isometric map. If a sprite is missing,
the map renders the business **emoji icon** instead (intended fallback — not an
error).

## How the engine picks sprites

`IsometricMapEngine` reads `manifest.json` (an array of existing sprite
filenames) and ONLY fetches sprites listed there. Anything not listed renders as
emoji with **zero network requests** (no 404 noise in DevTools).

## Adding / enabling art

1. Drop the PNG here, named `<business_type>_lvl<level>.png`
   (e.g. `bio_farm_lvl1.png`, `helios_lvl2.png`).
2. Add the exact filename to `manifest.json`, e.g.:
   ```json
   ["bio_farm_lvl1.png", "helios_lvl1.png"]
   ```
3. Rebuild the frontend and deploy.

Leave `manifest.json` as `[]` to keep the whole map emoji-based.
