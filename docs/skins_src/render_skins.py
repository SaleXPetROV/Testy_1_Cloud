import sys, json
from playwright.sync_api import sync_playwright
names = sys.argv[1].split(',')
js = open('kit.js').read() + '\n' + open('buildings.js').read()
with sync_playwright() as p:
    b = p.chromium.launch(executable_path='/opt/pw-browsers/chromium-1194/chrome-linux/chrome', args=['--no-sandbox'])
    pg = b.new_page(viewport={'width': 512, 'height': 512})
    pg.set_content('<html><body style="margin:0;background:transparent"><div id="c"></div><script>' + js + '</script></body></html>')
    for n in names:
        svg = pg.evaluate(f"B[{json.dumps(n)}]()")
        pg.evaluate("s => { document.getElementById('c').innerHTML = s; }", svg)
        pg.locator('#c svg').screenshot(path=f'out/{n}.png', omit_background=True)
        print('rendered', n)
    b.close()
