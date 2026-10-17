import httpx, json
from pymongo import MongoClient
from playwright.sync_api import sync_playwright
db=MongoClient('mongodb://127.0.0.1:27017')['ton_city']
tok=httpx.post('http://127.0.0.1:8001/api/auth/login',json={'email':'testuser@example.com','password':'Test1234!'},timeout=30).json()['token']
with sync_playwright() as p:
    b=p.chromium.launch(executable_path='/opt/pw-browsers/chromium-1194/chrome-linux/chrome', args=['--no-sandbox'])
    c=b.new_context(viewport={'width':390,'height':844}, device_scale_factor=3)
    c.add_init_script(f"localStorage.setItem('token',{json.dumps(tok)});localStorage.setItem('ton_city_token',{json.dumps(tok)});localStorage.setItem('ton_city_lang','ru');")
    pg=c.new_page()
    for grp,name in (('standard','biz_std'),('crazy','biz_crazy')):
        db.businesses.update_one({'id':'ad-biz-0'},{'$set':{'skin_group':grp}})
        pg.goto('http://localhost:3000/my-businesses', wait_until='domcontentloaded', timeout=60000)
        pg.wait_for_selector('[data-testid=header-city-pass]', timeout=45000); pg.wait_for_timeout(3500)
        pg.screenshot(path=f'shots/{name}.png')
        box=pg.evaluate("(()=>{const im=[...document.querySelectorAll('img')].find(i=>i.src.startsWith('data:image/webp')); if(!im) return null; const r=im.getBoundingClientRect(); return [r.x,r.y,r.width,r.height];})()")
        print(name, 'skin img box (css px):', box)
    b.close()
