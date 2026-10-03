from pathlib import Path
import re
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
html=(ROOT/'site/index.html').read_text()
css=(ROOT/'site/assets/styles.css').read_text()
app=(ROOT/'site/assets/app.js').read_text()
i18n=(ROOT/'site/assets/i18n.js').read_text()
halloween_preview=(ROOT/'site/assets/halloween-preview.js').read_text()
halloween=(ROOT/'site/assets/halloween.js').read_text()
# Strip all external scripts and inline service-worker registration.
test_html=re.sub(r'<script[^>]+src="[^"]+"[^>]*></script>','',html,flags=re.I)
test_html=re.sub(r'<script>if\("serviceWorker"[^<]+</script>','',test_html,flags=re.I)
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True,executable_path='/usr/bin/chromium',args=['--no-sandbox'])
    page=browser.new_page(viewport={'width':1280,'height':900})
    page.set_content(test_html.replace('</head>','<style>'+css+'</style></head>'),wait_until='domcontentloaded')
    page.evaluate('''() => { const store=()=>({_m:new Map(),get length(){return this._m.size},key(i){return Array.from(this._m.keys())[i]??null},getItem(k){return this._m.has(k)?this._m.get(k):null},setItem(k,v){this._m.set(String(k),String(v))},removeItem(k){this._m.delete(String(k))},clear(){this._m.clear()}}); window.__mfStorage=store();window.__mfSessionStorage=store();window.fetch=async(url)=>new Response(JSON.stringify({ok:true,release_id:'v1 (0.63-A)',site_version:'0.63-A',state_epoch:'ui',beamng_version:'0.39',stages:Array.from({length:15},(_,i)=>({key:String(i),label:'Этап '+(i+1),description:'',weight:1})),config:{brand_name:'ModMendryx',tagline:'Проверка и безопасное исправление модов BeamNG.drive',default_suffix:'FIXED',repair_modes:{standard:{count:7},medium:{count:11},aggressive:{count:15}},processing_speed_profiles:{standard:{},balanced:{},aggressive:{}}},capabilities:{}}),{status:200,headers:{'Content-Type':'application/json'}}); window.__mfStorage.setItem('mf_data_reset_release','0.63-A');window.__mfStorage.setItem('mf_seen_release','v1 (0.63-A)');window.__mfStorage.setItem('mf_privacy','1');window.__mfStorage.setItem('mf_guide','1'); }''')
    page.add_script_tag(content=app.replace('localStorage','window.__mfStorage').replace('sessionStorage','window.__mfSessionStorage'))
    page.add_script_tag(content=i18n.replace('localStorage','window.__mfStorage'))
    page.add_script_tag(content=halloween_preview.replace('localStorage','window.__mfStorage'))
    page.add_script_tag(content=halloween.replace('localStorage','window.__mfStorage'))
    page.wait_for_timeout(700)
    assert page.locator('link[rel="icon"]').get_attribute('href') == '/assets/logo.png?v=063a'
    page.locator('#settingsTop').click()
    assert page.locator('.ui-performance-card[data-ui-performance]').count() == 4
    page.locator('#sCancel').click()
    page.locator('#languageTop').click(); page.wait_for_timeout(150)
    assert page.locator('html').get_attribute('lang') == 'en'
    assert 'Choose' in page.locator('#dropTitle').inner_text()
    page.locator('#languageTop').click(); page.wait_for_timeout(150)
    assert page.locator('html').get_attribute('lang') == 'ru'
    page.locator('#snakePromoBtn').click(); page.wait_for_timeout(100)
    box=page.locator('.game-panel').bounding_box(); assert box and box['width']<=361 and box['x']>=0
    page.set_viewport_size({'width':390,'height':844}); page.wait_for_timeout(100)
    box=page.locator('.game-panel').bounding_box(); assert box and box['x']>=0 and box['width']<=390 and box['y']>=0
    # Halloween contract: 31 clicks -> warning -> active; another 31 -> exit and restore.
    for _ in range(31): page.locator('#brand').click()
    assert page.locator('#modal').is_visible()
    page.locator('#halloweenConfirm').click()
    page.wait_for_timeout(100)
    assert page.locator('html').get_attribute('class') and 'halloween-preview-active' in (page.locator('html').get_attribute('class') or '')
    page.locator('#preparationPanel')
    page.evaluate("document.documentElement.setAttribute('data-phase','processing'); window.dispatchEvent(new CustomEvent('modmendryx:phase'))")
    await_ms=page.wait_for_timeout
    await_ms(150)
    assert page.locator('.mf-pumpkin').count() == 1
    page.wait_for_timeout(3300)
    assert page.locator('.mf-pumpkin').count() == 1 or page.locator('.mf-pumpkin').count() == 0
    for _ in range(31): page.locator('#brand').click()
    page.wait_for_timeout(120)
    assert 'halloween-preview-active' not in (page.locator('html').get_attribute('class') or '')
    browser.close()
print('FINAL HEADLESS UI: PASS (language, four performance profiles, static favicon, responsive mini-game)')
