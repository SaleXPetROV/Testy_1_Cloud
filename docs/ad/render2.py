import sys, os
from playwright.sync_api import sync_playwright
FPS = 30; DUR = 30.0
times = [float(x) for x in sys.argv[1].split(',')] if len(sys.argv) > 1 and sys.argv[1] != 'all' else None
with sync_playwright() as p:
    b = p.chromium.launch(executable_path='/opt/pw-browsers/chromium-1194/chrome-linux/chrome', args=['--no-sandbox', '--allow-file-access-from-files'])
    pg = b.new_page(viewport={'width': 1080, 'height': 1920}, device_scale_factor=1)
    pg.goto('file:///home/claude/ad/composer2.html'); pg.wait_for_timeout(1500)
    pg.evaluate("document.fonts.ready")
    if times:
        for t in times:
            pg.evaluate(f"render({t})"); pg.screenshot(path=f'preview_{t:05.2f}.jpg', type='jpeg', quality=90)
    else:
        n = int(FPS * DUR)
        for i in range(n):
            pg.evaluate(f"render({i / FPS})")
            pg.screenshot(path=f'frames2/{i:05d}.jpg', type='jpeg', quality=93)
            if i % 150 == 0: print('frame', i, '/', n, flush=True)
    b.close()
