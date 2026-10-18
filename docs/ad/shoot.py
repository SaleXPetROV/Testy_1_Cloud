import httpx, json
from playwright.sync_api import sync_playwright
tok=httpx.post('http://127.0.0.1:8001/api/auth/login',json={'email':'testuser@example.com','password':'Test1234!'},timeout=30).json()['token']
SHOTS=[  # name, url, wait selector, actions
 ('biz','/my-businesses','[data-testid=header-city-pass]',None),
 ('resources','/resources','[data-testid=resources-my-title]',None),
 ('boosters','/resources?tab=boosters','[data-testid=boosters-panel]',None),
 ('trading','/trading','body',None),
 ('tasks','/tasks','[data-testid=tasks-tabs]',None),
 ('league','/community','[data-testid=league-table]',None),
 ('pass','/city-pass','[data-testid=pass-levels]',None),
 ('pass_scroll','/city-pass','[data-testid=pass-levels]','scroll:700'),
]
with sync_playwright() as p:
    b=p.chromium.launch(executable_path='/opt/pw-browsers/chromium-1194/chrome-linux/chrome', args=['--no-sandbox'])
    c=b.new_context(viewport={'width':390,'height':844}, device_scale_factor=3)
    c.add_init_script(f"localStorage.setItem('token',{json.dumps(tok)});localStorage.setItem('ton_city_token',{json.dumps(tok)});localStorage.setItem('ton_city_lang','ru');")
    pg=c.new_page()
    for name,url,sel,act in SHOTS:
        pg.goto('http://localhost:3000'+url, wait_until='domcontentloaded', timeout=60000)
        try: pg.wait_for_selector(sel, timeout=45000)
        except Exception as e: print(name,'wait failed')
        pg.wait_for_timeout(3000)
        if act and act.startswith('scroll:'):
            pg.evaluate(f"document.querySelectorAll('[data-radix-scroll-area-viewport]').forEach(v=>v.scrollTop={act.split(':')[1]})"); pg.wait_for_timeout(800)
        pg.screenshot(path=f'shots/{name}.png'); print('shot', name)
    b.close()
