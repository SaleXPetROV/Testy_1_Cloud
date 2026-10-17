import json, sys
from playwright.sync_api import sync_playwright
specs = json.load(open('specs.json'))
only = sys.argv[1].split(',') if len(sys.argv) > 1 else list(specs)
js = open('kit.js').read() + '\n' + open('buildings.js').read()
GLOW = {1: '#00F0FF', 2: '#B36BFF', 3: '#FFD84D'}
HS = {1: 0.9, 2: 1.1, 3: 1.32}            # exaggerated, chunky proportions
with sync_playwright() as p:
    b = p.chromium.launch(executable_path='/opt/pw-browsers/chromium-1194/chrome-linux/chrome', args=['--no-sandbox'])
    pg = b.new_page(viewport={'width': 512, 'height': 640})
    pg.set_content('<html><body style="margin:0;background:transparent"><div id="c"></div><script>' + js + '</script></body></html>')
    for t in only:
        sp = specs[t]
        for st in (1, 2, 3):
            pg.evaluate(f"""(() => {{
              HS = {HS[st]}; TINT = {json.dumps(GLOW[sp['tier']])}; BS = 1.12; SX = 1; SY = {0.5 if sp['fp'] == '1x2' else 1};
              const svg = B[{json.dumps(t)}]();
              document.getElementById('c').innerHTML = svg;
              const ex = document.getElementById('extras');
              let extra = stageExtras({st}, {json.dumps(GLOW[sp['tier']])});
              if ({st} >= 3) {{                       // holo halo above the highest point of the building
                const bb = document.getElementById('bld').getBBox();
                const cx = 256, cy = Math.max(26, bb.y - 18);
                extra += `<ellipse cx="${{cx}}" cy="${{cy}}" rx="46" ry="12" fill="none" stroke="{GLOW[sp['tier']]}" stroke-width="4" filter="url(#glow)"/>`
                       + `<ellipse cx="${{cx}}" cy="${{cy}}" rx="28" ry="7" fill="none" stroke="#ffffff" stroke-width="2" opacity=".8"/>`;
                for (const [dx, dy, r] of [[-60, 10, 3], [58, 4, 2.5], [0, -16, 3.5]]) extra += `<circle cx="${{cx + dx}}" cy="${{cy + dy}}" r="${{r}}" fill="#fff" filter="url(#glowS)"/>`;
              }}
              ex.innerHTML = extra;
            }})()""")
            pg.locator('#c svg').screenshot(path=f'stages/{t}_stage{st}.png', omit_background=True)
        print('rendered', t, flush=True)
    b.close()
