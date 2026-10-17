import json, sys
from playwright.sync_api import sync_playwright
mode = sys.argv[1]
opts = {'labels': mode == 'overview', 'locked': 4 if mode in ('locked', 'overview') else None, 'lod': 'far' if mode == 'overview' else 'near',
        'viewer': {'newbie': 'newbie', 'zero': 'zero'}.get(mode, 'level1'), 'open': {1: 121, 2: 80, 3: 119, 4: 0}}
with sync_playwright() as p:
    b = p.chromium.launch(executable_path='/opt/pw-browsers/chromium-1194/chrome-linux/chrome', args=['--no-sandbox', '--allow-file-access-from-files'])
    pg = b.new_page(viewport={'width': 1200, 'height': 900})
    errs = []; pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.goto('file:///home/claude/isomap/' + (sys.argv[2] if len(sys.argv) > 2 else 'iso_map.html')); pg.wait_for_timeout(500)
    info = pg.evaluate(f"renderMap({json.dumps(opts)}).then(r => ({{W: r.W, H: r.H, b: r.buildings, s: r.sprites, centers: r.centers}}))")
    pg.set_viewport_size({'width': info['W'], 'height': info['H']}); pg.wait_for_timeout(300)
    pg.locator('#cv').screenshot(path=f'full_{mode}{"_sq" if len(sys.argv) > 2 else ""}.png')
    json.dump(info, open('info.json', 'w'))
    print(mode, 'errors in layout:', pg.evaluate('window.placementErrors ? placementErrors : null'), info['W'], 'x', info['H'], '| buildings', info['b'], '| sprites loaded', info['s'], '| errors', errs)
    b.close()
