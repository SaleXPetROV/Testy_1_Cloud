import json
from playwright.sync_api import sync_playwright
d = json.load(open('map.json'))
SP = 'file:///home/claude/TON_CITY_v2.3/frontend/public/sprites/neon/'
FONTS = open('/home/claude/ad/fonts_local.css').read()
fmt = lambda v: f"{v:,}".replace(',', ' ')
items = []; tags = []
for p in d["plots"]:
    x, y = p["x"], p["y"]
    if p["kind"] == 'free':
        items.append(f'<svg class="abs" style="left:0;top:0" width="{d["W"]}" height="{d["H"]}"><polygon points="{x},{y-57} {x+114},{y} {x},{y+57} {x-114},{y}" fill="rgba(0,240,255,.08)" stroke="#00F0FF" stroke-width="3" stroke-dasharray="10 8"/></svg>')
        items.append(f'<div class="plus" style="left:{x-22}px;top:{y-30}px">+</div>')
        tags.append(f'<div class="tag free" style="left:{x}px;top:{y-86}px">Свободно · {fmt(p["price"])} $CITY</div>')
        continue
    w = 238; top = y + 58 - w
    items.append(f'<img class="abs b" src="{SP}{p["b"]}.webp" style="left:{x-w/2}px;top:{top}px;width:{w}px;height:{w}px">')
    if p["kind"] == 'sale':
        tags.append(f'<div class="tag sale" style="left:{x}px;top:{top+18}px">🏷 {fmt(p["price"])} $CITY</div>')
    else:
        tags.append(f'<div class="tag own" style="left:{x}px;top:{top+18}px"><span class="lv">{p["lvl"]}</span>{p["owner"]}</div>')
for c in d["cars"]:
    rot = 26.6 if c["dir"] == 'a' else -26.6
    items.append(f'<div class="car" style="left:{c["x"]-9}px;top:{c["y"]-5}px;background:{c["c"]};transform:rotate({rot}deg)"></div>')
for t in d["trees"]:
    s = t["s"]
    items.append(f'<div class="tree" style="left:{t["x"]-10*s}px;top:{t["y"]-34*s}px;transform:scale({s})"><i></i><b></b></div>')
for l in d["lamps"]:
    items.append(f'<div class="lamp" style="left:{l["x"]-3}px;top:{l["y"]-26}px"></div>')
html = f'''<!doctype html><html><head><meta charset="utf-8"><style>{FONTS}
body{{margin:0;width:{d["W"]}px;height:{d["H"]}px;overflow:hidden;font-family:Rajdhani,sans-serif;
 background:radial-gradient(ellipse at 50% 42%,#0f5a86 0%,#0a3f63 38%,#062238 70%,#03121f 100%)}}
.abs{{position:absolute}} .b{{filter:drop-shadow(0 10px 10px rgba(0,0,0,.45))}}
.tag{{position:absolute;transform:translateX(-50%);padding:4px 12px;border-radius:999px;font-weight:800;font-size:17px;white-space:nowrap;
 box-shadow:0 6px 18px rgba(0,0,0,.45);border:2px solid rgba(255,255,255,.25)}}
.tag.own{{background:rgba(10,14,24,.88);color:#e6f6ff;border-color:rgba(0,240,255,.5)}}
.tag.own .lv{{display:inline-block;margin-right:7px;padding:0 7px;border-radius:7px;background:#00F0FF;color:#02131c;font-family:Unbounded;font-size:14px}}
.tag.sale{{background:linear-gradient(90deg,#1fd17a,#7bf5b1);color:#032313;font-family:Unbounded;font-size:17px}}
.tag.sale::after,.tag.own::after,.tag.free::after{{content:"";position:absolute;left:50%;bottom:-9px;margin-left:-7px;border:7px solid transparent;border-top-color:inherit}}
.tag.free{{background:rgba(0,240,255,.16);color:#bff8ff;border-color:#00F0FF;font-family:Unbounded;font-size:15px}}
.plus{{position:absolute;width:44px;height:44px;border-radius:50%;background:#00F0FF;color:#02131c;font:900 34px/44px Unbounded;text-align:center;box-shadow:0 0 22px #00F0FF}}
.car{{position:absolute;width:18px;height:10px;border-radius:3px;box-shadow:0 2px 3px rgba(0,0,0,.5)}}
.tree{{position:absolute;width:20px;height:40px;transform-origin:50% 100%}}
.tree b{{position:absolute;left:1px;top:0;width:18px;height:26px;border-radius:50% 50% 45% 45%;background:radial-gradient(circle at 35% 30%,#7fe08f,#2c7a3d 70%)}}
.tree i{{position:absolute;left:8px;top:22px;width:4px;height:12px;background:#5a3d25}}
.lamp{{position:absolute;width:6px;height:26px;background:linear-gradient(#ffe9a3 0 22%,#7a8294 22%)}}
.lamp::before{{content:"";position:absolute;left:-9px;top:-9px;width:24px;height:24px;border-radius:50%;background:rgba(255,226,140,.35);filter:blur(4px)}}
.cloud{{position:absolute;border-radius:50%;background:rgba(255,255,255,.10);filter:blur(18px)}}
.hud{{position:absolute;left:24px;top:22px;padding:12px 20px;border-radius:16px;background:rgba(5,10,20,.75);border:1px solid rgba(0,240,255,.35);color:#dff7ff;font-weight:700;font-size:20px}}
.hud b{{font-family:Unbounded;color:#00F0FF}}
.legend{{position:absolute;right:24px;top:22px;display:flex;gap:10px}}
.legend span{{padding:6px 12px;border-radius:999px;font-size:16px;font-weight:800}}
</style></head><body>
<svg class="abs" style="left:0;top:0" width="{d["W"]}" height="{d["H"]}">{''.join(d["tiles"])}</svg>
{''.join(items)}<div style="position:absolute;inset:0;z-index:5">{''.join(tags)}</div>
<div class="cloud" style="left:120px;top:120px;width:320px;height:120px"></div><div class="cloud" style="left:1150px;top:760px;width:380px;height:130px"></div>
<div class="hud">Остров <b>GRAM</b> · 12 участков</div>
<div class="legend"><span style="background:rgba(10,14,24,.88);color:#e6f6ff;border:2px solid rgba(0,240,255,.5)">Занят: владелец · уровень</span>
<span style="background:#1fd17a;color:#032313">Продаётся: цена</span><span style="background:rgba(0,240,255,.16);color:#bff8ff;border:2px solid #00F0FF">Свободно: цена</span></div>
</body></html>'''
open('map.html', 'w').write(html)
with sync_playwright() as p:
    b = p.chromium.launch(executable_path='/opt/pw-browsers/chromium-1194/chrome-linux/chrome', args=['--no-sandbox', '--allow-file-access-from-files'])
    pg = b.new_page(viewport={'width': d["W"], 'height': d["H"]}); pg.goto('file:///home/claude/mapc/map.html'); pg.wait_for_timeout(1500)
    pg.screenshot(path='map_concept.png'); b.close()
print('ok')
