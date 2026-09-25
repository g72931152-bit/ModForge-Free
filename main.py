from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import time
import uuid
from collections import defaultdict
from pathlib import Path, PurePosixPath
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

APP_NAME = "ModForge"
APP_VERSION = "v1"
BEAMNG_VERSION = "0.39"
MAX_UPLOAD = 2 * 1024 * 1024 * 1024
MAX_UNPACKED = 4 * 1024 * 1024 * 1024
MAX_FILES = 12000
LARGE_JOB_THRESHOLD = 1 * 1024 * 1024 * 1024
LARGE_JOB_COOLDOWN = 15 * 60
WORK_ROOT = Path(os.environ.get("MODFORGE_WORK_ROOT", "/tmp/modforge"))
ASSET_ROOT = Path(__file__).resolve().parent / "assets"
ASSET_ROOT.mkdir(parents=True, exist_ok=True)
CONFIG_PATH = Path(__file__).resolve().parent / "site_config.json"
WORK_ROOT.mkdir(parents=True, exist_ok=True)
ASSET_ROOT.mkdir(parents=True, exist_ok=True)

jobs: dict[str, dict] = {}
large_cooldowns: dict[str, float] = {}

app = FastAPI(title=APP_NAME, docs_url=None, redoc_url=None)
app.mount("/assets", StaticFiles(directory=ASSET_ROOT), name="assets")

TEXT_EXTS = {".json", ".jbeam", ".pc", ".lua", ".txt", ".cs", ".cfg", ".materials"}
RESOURCE_EXTS = r"dds|png|jpe?g|tga|bmp|gif|dae|cdae|jbeam|json|pc|cdb|lua"
RESOURCE_RE = re.compile(
    rf"(?P<path>[A-Za-z0-9_@%+~.-]+(?:[\\/][A-Za-z0-9_@%+~.-]+)*\.(?:{RESOURCE_EXTS}))",
    re.I,
)
MISSING_RESOURCE_MAX = 160

DEFAULT_CONFIG = {
    "brand_name": "ModForge",
    "tagline": "BeamNG mod repair",
    "support_url": "",
    "support_label": "Поддержать проект",
    "ad_enabled": False,
    "ad_html": "",
    "default_suffix": "FIXED",
}


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    try:
        incoming = json.loads(CONFIG_PATH.read_text("utf-8"))
        if isinstance(incoming, dict):
            cfg.update({k: incoming[k] for k in cfg if k in incoming})
    except Exception:
        pass
    return cfg


CONFIG = load_config()


def html_escape(value: object) -> str:
    text = str(value)
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


HTML = r'''<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="theme-color" content="#090909"><link rel="icon" type="image/png" href="/assets/logo.png"><title>ModForge</title>
<style>
:root{--bg:#080808;--panel:#101010;--panel2:#151515;--line:#292929;--line2:#3b3b3b;--text:#f4f4f4;--muted:#989898;--orange:#ff7a18;--green:#65d695;--red:#ff6666;--yellow:#e7bf55;--blue:#72b9ff}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.5 system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif}button,input,textarea,select{font:inherit}.shell{width:min(1320px,100%);margin:auto;padding:18px clamp(12px,3vw,34px) 40px}.top{display:flex;align-items:center;justify-content:space-between;gap:15px;border-bottom:1px solid var(--line);padding:4px 0 16px}.brand{display:flex;gap:11px;align-items:center}.brand img{width:40px;height:40px;border:1px solid var(--line);border-radius:9px;object-fit:contain}.brand h1{font-size:20px;margin:0}.brand small{display:block;color:var(--muted);font-size:11px}.pill{border:1px solid var(--line);border-radius:7px;padding:6px 9px;color:var(--muted);font-size:11px}.banner{display:none;margin:18px 0;border:1px solid var(--line);border-radius:10px;overflow:hidden}.banner img{width:100%;display:block}.layout{display:grid;grid-template-columns:minmax(0,1.3fr) minmax(260px,.7fr);gap:16px;margin-top:18px}.card{background:var(--panel);border:1px solid var(--line);border-radius:11px}.main{padding:clamp(18px,3vw,30px)}.side{padding:20px}.eyebrow{color:var(--orange);font-size:10px;text-transform:uppercase;letter-spacing:.08em}h2{font-size:clamp(28px,4vw,46px);line-height:1.04;letter-spacing:-.035em;margin:13px 0 10px}h3{margin:0 0 10px}p{color:var(--muted);margin:0 0 14px}.drop{margin-top:20px;border:1px dashed #454545;border-radius:9px;padding:26px;text-align:center;background:#0c0c0c}.drop.active{border-color:var(--orange)}.drop b{display:block;margin:7px 0}.actions{display:flex;gap:8px;flex-wrap:wrap;justify-content:center}.btn{border:1px solid var(--line2);background:#181818;color:var(--text);border-radius:7px;padding:9px 12px;min-height:40px;font-weight:700;cursor:pointer}.btn.primary{background:var(--orange);border-color:var(--orange);color:#160b03}.btn.ghost{background:transparent;color:var(--muted)}.btn:disabled{opacity:.45;cursor:not-allowed}.fileinfo,.notice,.field{margin-top:12px;border:1px solid var(--line);border-radius:8px;padding:11px;background:#0d0d0d}.field label{display:block;font-size:11px;color:#ccc;margin-bottom:6px}.field textarea,.field input,.field select{width:100%;background:#090909;color:var(--text);border:1px solid var(--line2);border-radius:7px;padding:9px;outline:none}.field textarea{min-height:90px;resize:vertical}.quick{display:flex;gap:6px;flex-wrap:wrap}.quick button{font-size:11px;padding:6px 8px;border:1px solid var(--line);background:#141414;color:#bbb;border-radius:6px;cursor:pointer}.feature{padding:11px 0;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;color:var(--muted)}.feature:last-child{border:0}.feature strong{color:var(--text)}.section{margin-top:16px;padding:18px}.steps{display:grid;grid-template-columns:repeat(3,1fr);gap:7px}.step{border:1px solid var(--line);border-radius:8px;background:#0d0d0d;padding:10px;min-height:76px}.step .head{display:flex;align-items:center;gap:7px}.dot{width:19px;height:19px;border:1px solid var(--line2);border-radius:50%;display:grid;place-items:center;font-size:10px;color:#777}.step b{font-size:12px}.step small{display:block;color:#777;margin:6px 0 0}.step.active{border-color:#744016;background:#17100b}.step.active .dot{border-color:var(--orange);color:var(--orange)}.step.done .dot{background:#163322;border-color:#2f6948;color:var(--green)}.step.error .dot{background:#351717;border-color:#713232;color:var(--red)}.step button{margin-top:7px;background:none;border:0;color:#777;font-size:11px;padding:0;cursor:pointer}.detail{display:none;color:#aaa;border-top:1px solid var(--line);margin-top:7px;padding-top:7px;font-size:11px}.step.open .detail{display:block}.progressbox{display:none;margin-top:16px}.progressline{height:8px;background:#090909;border:1px solid var(--line);border-radius:99px;overflow:hidden}.progressline i{display:block;width:0;height:100%;background:var(--orange);transition:width .25s}.progressmeta{display:flex;justify-content:space-between;gap:10px;color:var(--muted);font-size:11px;margin-top:7px}.controls{display:flex;gap:7px;flex-wrap:wrap;margin-top:11px}.controls .btn{min-height:34px;padding:6px 9px;font-size:11px}.summary{display:grid;grid-template-columns:repeat(4,1fr);gap:7px}.stat{border:1px solid var(--line);border-radius:8px;padding:12px;background:#0d0d0d}.stat .n{font-size:23px;font-weight:800}.stat small{color:#777}.issues{display:grid;gap:7px;margin-top:10px}.issue{border:1px solid var(--line);border-radius:8px;padding:11px;background:#0d0d0d}.tag{font-size:9px;font-weight:800;padding:3px 5px;border-radius:4px;margin-right:6px}.fixed{background:#321616;color:#ff9292}.warning{background:#302815;color:#f2d174}.ok{background:#153022;color:#82e2a5}.info{background:#152537;color:#8ccaff}.issue small{display:block;color:#777;margin-top:5px;word-break:break-word}.download{display:flex;gap:7px;flex-wrap:wrap;margin-top:12px}.modal{position:fixed;inset:0;background:#000b;display:none;align-items:center;justify-content:center;padding:15px;z-index:20}.modal.show{display:flex}.modalbox{width:min(680px,100%);max-height:90vh;overflow:auto;background:#111;border:1px solid var(--line2);border-radius:12px;padding:22px}.modalbox h2{font-size:25px;margin:0 0 10px}.modalbox ul{padding-left:20px;color:#aaa}.modalfoot{display:flex;justify-content:flex-end;gap:7px;margin-top:17px}.settingsgrid{display:grid;grid-template-columns:1fr 1fr;gap:10px}.adslot{display:none;min-height:90px;margin-top:16px;border:1px dashed #343434;border-radius:8px;padding:14px;color:#666;text-align:center}.footer{border-top:1px solid var(--line);margin-top:20px;padding-top:15px;color:#666;font-size:11px;display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap}.muted{color:var(--muted)}@media(max-width:900px){.layout{grid-template-columns:1fr}.steps{grid-template-columns:1fr 1fr}}@media(max-width:600px){.shell{padding:12px 9px 28px}.top{align-items:flex-start}.pill{font-size:10px}.layout{margin-top:12px}.steps{grid-template-columns:1fr}.summary{grid-template-columns:1fr 1fr}.settingsgrid{grid-template-columns:1fr}.main,.side,.section{padding:16px}.drop{padding:22px 12px}.download .btn{width:100%}}
</style></head><body>
<div class="shell"><header class="top"><div class="brand"><img src="/assets/logo.png" alt="ModForge" onerror="this.style.display='none'"><div><h1 id="brand">ModForge</h1><small id="tagline">BeamNG.drive mod repair</small></div></div><div class="pill"><span id="version">v1</span> · BeamNG.drive <span id="beamver">0.39</span> · <span id="service">проверка…</span></div></header>
<div class="banner" id="banner"><img src="/assets/banner.png" alt="ModForge"></div>
<main><div class="layout"><section class="card main"><div class="eyebrow">поддерживаемые моды · BeamNG.drive 0.39</div><h2>Проверка и исправление модов без лишней сложности.</h2><p>Загрузите ZIP или папку мода. ModForge последовательно проверит структуру, конфигурации, ресурсы и материалы, затем повторно проверит результат.</p><div class="drop" id="drop"><div>MODFORGE</div><b>Перетащите ZIP или выберите папку мода</b><p>Принимаются только структуры, предназначенные для BeamNG.drive.</p><div class="actions"><button class="btn primary" id="zipBtn">Выбрать ZIP</button><button class="btn" id="folderBtn">Выбрать папку</button></div><input id="zipInput" type="file" accept=".zip" hidden><input id="folderInput" type="file" webkitdirectory directory multiple hidden><div class="fileinfo" id="fileInfo"></div></div><div class="field"><label>Что проверить в первую очередь</label><div class="quick"><button data-q="Проверить текстуры и ссылки на ресурсы">Текстуры</button><button data-q="Проверить стекло и материалы">Стекло</button><button data-q="Проверить JBeam и конфигурации">JBeam</button><button data-q="Проверить освещение и материалы">Свет</button><button data-q="Проверить всё максимально тщательно">Всё</button></div></div><div class="field"><label>Дополнительные пожелания</label><textarea id="wishes" placeholder="Например: в первую очередь проверь стекло и отсутствующие текстуры."></textarea></div><div class="field"><label>Формат результата</label><select id="outputType"><option value="zip">Исправленный ZIP — рекомендуется</option><option value="zip_same">ZIP с сохранением структуры исходного мода</option></select><div class="muted" style="font-size:11px;margin-top:5px">Папка загружается как папка, но браузер не умеет скачать папку напрямую — поэтому результат выдаётся ZIP-архивом.</div></div><div class="actions" style="justify-content:flex-start;margin-top:12px"><button class="btn primary" id="startBtn" disabled>Начать проверку</button><button class="btn ghost" id="clearBtn">Сбросить</button><button class="btn ghost" id="settingsBtn">Настройки выдачи</button></div></section>
<aside class="card side"><h3>Как работает ModForge</h3><div class="feature"><span>Целевая версия</span><strong>0.39</strong></div><div class="feature"><span>Текущая версия</span><strong>v1</strong></div><div class="feature"><span>Автоисправление</span><strong>Да</strong></div><div class="feature"><span>Повторная проверка</span><strong>Да</strong></div><div class="notice"><strong>Что сервис не делает</strong><br><span class="muted">Не запускает полноценный BeamNG.drive для визуального рендера, не гарантирует исправление неизвестной Lua/физики и не скачивает чужие игровые ассеты из интернета.</span></div><div class="adslot" id="adslot">Рекламное место</div></aside></div>
<section class="card section" id="progressBox"><h3>Проверка мода</h3><div class="progressline"><i id="bar"></i></div><div class="progressmeta"><span id="progressText">Подготовка…</span><span id="progressPct">0%</span><span id="eta">Осталось: —</span></div><div class="controls"><button class="btn" id="pauseBtn">Пауза</button><button class="btn" id="resetJobBtn">Остановить и сбросить</button><button class="btn" id="filesBtn">Показать проверяемые файлы</button></div><div class="steps" id="steps"></div></section>
<section class="card section" id="result" style="display:none"><h3 id="resultTitle">Результат</h3><p id="resultLead"></p><div class="summary"><div class="stat"><div class="n" id="statGood">0</div><small>проверок OK</small></div><div class="stat"><div class="n" id="statFixed">0</div><small>исправлено</small></div><div class="stat"><div class="n" id="statWarn">0</div><small>предупреждений</small></div><div class="stat"><div class="n" id="statFiles">0</div><small>файлов</small></div></div><div class="issues" id="issues"></div><div class="download"><a class="btn primary" id="downloadBtn">Скачать исправленный ZIP</a><button class="btn" id="reportBtn">Скачать JSON-отчёт</button></div></section></main><footer class="footer"><span>ModForge · временная обработка файлов · v1</span><span>BeamNG.drive 0.39</span></footer></div>
<div class="modal" id="modal"><div class="modalbox" id="modalbox"></div></div>
<script>
const $=id=>document.getElementById(id);let selected=[],selectedKind='',reportCache=null,currentJob=null,settings={suffix:'FIXED'};const maxBytes=2*1024*1024*1024;
const stages=[['prepare','Подготовка','Формат, пути и безопасность.'],['structure','Структура','Папки, дубли и структура мода.'],['syntax','Синтаксис','JSON, PC, JBeam и конфигурации.'],['resources','Ресурсы','Текстуры, модели и ссылки.'],['repair','Автоисправление','Безопасные подтверждённые исправления.'],['deep_repair','Глубокое исправление','Повторная проверка изменённых файлов.'],['recheck','Полная перепроверка','Весь мод после исправлений.'],['final','Финальная проверка','Проверка итогового архива.'],['done','Готово','Результат подготовлен.']];
function esc(s){return String(s??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]))}function bytes(n){let u=['B','KB','MB','GB'],i=0;while(n>=1024&&i<3){n/=1024;i++}return n.toFixed(i?1:0)+' '+u[i]}function eta(sec){if(!Number.isFinite(sec)||sec<=0)return 'Осталось: —';if(sec<60)return 'Осталось: ~'+Math.max(1,Math.round(sec))+' сек.';return 'Осталось: ~'+Math.ceil(sec/60)+' мин.'}
function renderSteps(active=0){$('steps').innerHTML=stages.map((s,i)=>'<div class="step" id="step'+(i+1)+'"><div class="head"><span class="dot">'+(i+1)+'</span><b>'+s[1]+'</b></div><small>'+s[2]+'</small><button onclick="toggleStep('+(i+1)+')">⋯ подробнее</button><div class="detail" id="detail'+(i+1)+'">Ожидает запуска.</div></div>').join('');setSteps(active)}
function setSteps(n,status){stages.forEach((s,i)=>{let e=$('step'+(i+1));if(!e)return;e.className='step'+(i+1<n?' done':'')+(i+1===n?' active':'')+(status==='error'&&i+1===n?' error':'');})}function toggleStep(n){$('step'+n).classList.toggle('open')}renderSteps();
async function health(){try{let r=await fetch('/api/health'),d=await r.json();$('service').textContent=r.ok?'онлайн':'ошибка';$('version').textContent=d.app_version||'v1';$('beamver').textContent=d.beamng_version||'0.39';if(d.config?.brand_name)$('brand').textContent=d.config.brand_name;if(d.config?.tagline)$('tagline').textContent=d.config.tagline;if(d.config?.ad_enabled&&d.config?.ad_html){$('adslot').style.display='block';$('adslot').innerHTML=d.config.ad_html}if(d.config?.default_suffix)settings.suffix=d.config.default_suffix}catch(e){$('service').textContent='офлайн'}}health();
function showModal(html,buttons=''){ $('modalbox').innerHTML=html+'<div class="modalfoot">'+buttons+'</div>';$('modal').classList.add('show') }function closeModal(){$('modal').classList.remove('show')}
function firstVisit(){let seen=localStorage.getItem('modforge_version')===('v1');if(!seen){showModal('<h2>Что нового в v1</h2><ul><li>Новая многоэтапная проверка и повторная перепроверка.</li><li>Подробности каждого этапа и примерное оставшееся время.</li><li>Пауза, сброс и просмотр списка проверяемых файлов.</li><li>Настройки имени итогового ZIP и быстрые приоритеты проверки.</li><li>Обновлённый строгий интерфейс и улучшенная обработка структуры мода.</li></ul>','<button class="btn primary" id="nextModal">Далее</button>');$('nextModal').onclick=()=>privacy()}else{} }function privacy(){showModal('<h2>Политика конфиденциальности</h2><p>Файлы нужны для выполнения проверки и временно хранятся на сервере. После завершения обработки рабочие данные удаляются автоматически. Не загружайте пароли, документы или другие личные данные.</p><label><input type="checkbox" id="privacyOk"> Я принимаю условия обработки файлов.</label>','<button class="btn primary" id="privacyNext" disabled>Продолжить</button>');$('privacyOk').onchange=e=>$('privacyNext').disabled=!e.target.checked;$('privacyNext').onclick=()=>instructions()}function instructions(){showModal('<h2>Как пользоваться</h2><ol><li>Выберите ZIP или папку BeamNG-мода.</li><li>При необходимости выберите приоритет проверки.</li><li>Настройте имя результата в «Настройки выдачи».</li><li>Запустите проверку и смотрите подробности каждого этапа.</li><li>После финальной перепроверки скачайте исправленный ZIP.</li></ol><p>ModForge работает с содержимым мода и не запускает полноценный BeamNG.drive.</p>','<button class="btn primary" id="doneIntro">Понятно</button>');$('doneIntro').onclick=()=>{localStorage.setItem('modforge_version','v1');closeModal()}}setTimeout(firstVisit,150);
$('zipBtn').onclick=()=>$('zipInput').click();$('folderBtn').onclick=()=>$('folderInput').click();$('zipInput').onchange=e=>{selected=[...e.target.files];selectedKind='zip';showSelection()};$('folderInput').onchange=e=>{selected=[...e.target.files];selectedKind='folder';showSelection()};function showSelection(){if(!selected.length)return;let total=selected.reduce((s,f)=>s+f.size,0);$('fileInfo').style.display='block';$('fileInfo').innerHTML='<b>'+esc(selectedKind==='zip'?'ZIP':'Папка')+'</b> · '+selected.length+' файлов · '+bytes(total);$('startBtn').disabled=total>maxBytes}
const drop=$('drop');['dragenter','dragover'].forEach(x=>drop.addEventListener(x,e=>{e.preventDefault();drop.classList.add('active')}));['dragleave','drop'].forEach(x=>drop.addEventListener(x,e=>{e.preventDefault();drop.classList.remove('active')}));drop.addEventListener('drop',e=>{selected=[...e.dataTransfer.files];selectedKind='zip';showSelection()});document.querySelectorAll('.quick button').forEach(b=>b.onclick=()=>{$('wishes').value=b.dataset.q});
$('settingsBtn').onclick=()=>showModal('<h2>Настройки выдачи</h2><div class="settingsgrid"><div class="field"><label>Окончание имени файла</label><input id="suffix" value="'+esc(settings.suffix)+'"><div class="muted" style="font-size:11px;margin-top:5px">Например: FIXED → CLEAN → REPAIRED</div></div><div class="field"><label>Формат</label><select disabled><option>ZIP</option></select><div class="muted" style="font-size:11px;margin-top:5px">ZIP — единственный прямой формат скачивания папки через браузер.</div></div></div>','<button class="btn" onclick="closeModal()">Отмена</button><button class="btn primary" id="saveSettings">Сохранить</button>');$('saveSettings').onclick=()=>{settings.suffix=$('suffix').value.trim()||'FIXED';closeModal()};
$('startBtn').onclick=upload;$('clearBtn').onclick=resetAll;function resetAll(){selected=[];selectedKind='';$('zipInput').value='';$('folderInput').value='';$('fileInfo').style.display='none';$('startBtn').disabled=true;$('progressBox').style.display='none';$('result').style.display='none';renderSteps();currentJob=null}
async function upload(){if(!selected.length)return;const fd=new FormData();fd.append('source_kind',selectedKind);fd.append('wishes',$('wishes').value||'');fd.append('output_suffix',settings.suffix||'FIXED');fd.append('output_type',$('outputType').value);selected.forEach(f=>{fd.append('files',f,f.name);fd.append('relative_paths',f.webkitRelativePath||f.name)});$('progressBox').style.display='block';$('result').style.display='none';$('startBtn').disabled=true;renderSteps(1);const xhr=new XMLHttpRequest();xhr.open('POST','/api/analyze');xhr.upload.onprogress=e=>{if(e.lengthComputable){let p=Math.round(e.loaded/e.total*100);$('bar').style.width=Math.min(90,p)+'%';$('progressPct').textContent=p+'%';$('progressText').textContent=p<100?'Загрузка файлов…':'Файл принят, начинается проверка…'}};xhr.onload=()=>{let d={};try{d=JSON.parse(xhr.responseText)}catch(e){}if(xhr.status!==200)return fail(d.detail||'Ошибка загрузки');currentJob=d.job_id;poll()};xhr.onerror=()=>fail('Не удалось отправить файл.');xhr.send(fd)}
async function poll(){try{let r=await fetch('/api/jobs/'+currentJob),j=await r.json();if(!r.ok)throw Error(j.detail||'Задание не найдено');$('progressText').textContent=j.stage_label||j.stage;$('eta').textContent=eta(j.eta_seconds);$('bar').style.width=Math.min(99,j.progress||0)+'%';$('progressPct').textContent=Math.round(j.progress||0)+'%';if(j.stage_index)setSteps(j.stage_index,j.status==='error'?'error':'');if(j.stage_index&&j.stage_detail)$('detail'+j.stage_index).textContent=j.stage_detail;if(j.status==='paused')$('pauseBtn').textContent='Продолжить';else $('pauseBtn').textContent='Пауза';if(j.status==='done'){renderResult(j.report);$('bar').style.width='100%';$('progressPct').textContent='100%';$('progressText').textContent='Готово';$('eta').textContent='Осталось: 0 сек.';setSteps(9);return}if(['error','cancelled'].includes(j.status))return fail(j.error||'Обработка остановлена.');setTimeout(poll,900)}catch(e){fail(e.message)}}
$('pauseBtn').onclick=async()=>{if(!currentJob)return;await fetch('/api/jobs/'+currentJob+'/pause',{method:'POST'});poll()};$('resetJobBtn').onclick=async()=>{if(!currentJob){resetAll();return}await fetch('/api/jobs/'+currentJob+'/cancel',{method:'POST'});resetAll()};$('filesBtn').onclick=async()=>{if(!currentJob)return;let r=await fetch('/api/jobs/'+currentJob+'/files'),d=await r.json();showModal('<h2>Проверяемые файлы</h2><p>Показаны первые 2000 файлов.</p><div class="field" style="max-height:45vh;overflow:auto"><code>'+esc((d.files||[]).join('\n'))+'</code></div>','<button class="btn primary" onclick="closeModal()">Закрыть</button>')};
function renderResult(r){reportCache=r;$('result').style.display='block';$('resultTitle').textContent=r.summary.ok?'Проверка завершена — критичных предупреждений не осталось':'Проверка завершена';$('resultLead').textContent='Исправлено: '+r.summary.fixed+'. Предупреждений после повторной проверки: '+r.summary.warnings+'. Итог: '+(r.summary.ok?'структура прошла финальную проверку.':'часть проблем требует ручной проверки.');$('statGood').textContent=r.summary.ok_checks;$('statFixed').textContent=r.summary.fixed;$('statWarn').textContent=r.summary.warnings;$('statFiles').textContent=r.summary.files_checked;$('issues').innerHTML=(r.issues||[]).map(x=>{let c=x.level==='fixed'?'fixed':x.level==='warning'?'warning':x.level==='ok'?'ok':'info',l=x.level==='fixed'?'ИСПРАВЛЕНО':x.level==='warning'?'ПРЕДУПРЕЖДЕНИЕ':x.level==='ok'?'OK':'ИНФО';return '<div class="issue"><span class="tag '+c+'">'+l+'</span><b>'+esc(x.title)+'</b><small>'+esc(x.details||'')+'</small></div>'}).join('');$('downloadBtn').href=r.download_url;$('downloadBtn').download=r.fixed_archive_name||'modforge_FIXED.zip'}
$('reportBtn').onclick=()=>{if(!reportCache)return;let n=(reportCache.fixed_archive_name||'modforge_FIXED.zip').replace(/\.zip$/i,'_report.json');let a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(reportCache,null,2)],{type:'application/json'}));a.download=n;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)};function fail(msg){$('progressText').textContent='Ошибка';$('eta').textContent='';$('result').style.display='block';$('resultTitle').textContent='Не удалось завершить проверку';$('resultLead').textContent=msg;$('issues').innerHTML='<div class="issue"><span class="tag warning">ОШИБКА</span><b>'+esc(msg)+'</b></div>';$('startBtn').disabled=false}
</script></body></html>'''


def client_id(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    if forwarded:
        return forwarded
    return request.client.host if request.client else "unknown"


def safe_rel(raw: str) -> str:
    raw = (raw or "").replace("\\", "/")
    raw = raw.lstrip("/")
    while raw.startswith("./"):
        raw = raw[2:]
    parts = []
    for part in PurePosixPath(raw).parts:
        if part in ("", "."):
            continue
        if part == "..":
            raise ValueError("Обнаружен небезопасный путь ../")
        parts.append(part)
    out = "/".join(parts)
    if not out or PurePosixPath(out).parts[0].endswith(":"):
        raise ValueError("Некорректный путь файла")
    return out


def read_text(path: Path) -> str:
    try:
        return path.read_text("utf-8", errors="replace")
    except Exception:
        return ""


def case_index(root: Path) -> dict[str, list[str]]:
    result = defaultdict(list)
    for path in root.rglob("*"):
        if path.is_file():
            rel = path.relative_to(root).as_posix()
            result[rel.casefold()].append(rel)
    return result


def resource_variants(ref: str) -> list[str]:
    normalized = ref.replace("\\", "/").lstrip("./")
    if normalized.startswith("/"):
        normalized = normalized[1:]
    return [normalized, normalized.removeprefix("vehicles/"), normalized.removeprefix("art/")]


def resolve_ref(ref: str, files: set[str], ci: dict[str, list[str]]) -> str | None:
    variants = resource_variants(ref)
    for candidate in variants:
        if candidate in files:
            return candidate
        matches = ci.get(candidate.casefold(), [])
        if len(matches) == 1:
            return matches[0]
    for candidate in variants:
        base = Path(candidate).name.casefold()
        matches = [p for p in files if Path(p).name.casefold() == base]
        if len(matches) == 1:
            return matches[0]
    return None


def resolve_candidates(ref: str, files: set[str]) -> list[str]:
    base = Path(ref.replace("\\", "/")).name.casefold()
    return sorted(p for p in files if Path(p).name.casefold() == base)[:8]


def replace_case_reference(path: Path, old: str, new: str) -> bool:
    text = read_text(path)
    pattern = re.compile(re.escape(old).replace(r"\/", r"[\\/]"), re.I)
    updated, count = pattern.subn(new, text, count=1)
    if count:
        path.write_text(updated, "utf-8")
        return True
    return False


def bracket_balance(text: str) -> tuple[bool, str]:
    stack = []
    pairs = {")": "(", "]": "[", "}": "{"}
    quote = None
    line_comment = False
    block_comment = False
    escape = False
    i = 0
    while i < len(text):
        c = text[i]
        if line_comment:
            if c == "\n":
                line_comment = False
            i += 1
            continue
        if block_comment:
            if c == "*" and i + 1 < len(text) and text[i + 1] == "/":
                block_comment = False
                i += 2
                continue
            i += 1
            continue
        if quote:
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == quote:
                quote = None
            i += 1
            continue
        if c in ('"', "'"):
            quote = c
            i += 1
            continue
        if c == "/" and i + 1 < len(text) and text[i + 1] == "/":
            line_comment = True
            i += 2
            continue
        if c == "/" and i + 1 < len(text) and text[i + 1] == "*":
            block_comment = True
            i += 2
            continue
        if c in "([{":
            stack.append(c)
        elif c in ")]}":
            if not stack or stack[-1] != pairs[c]:
                return False, f"Несоответствие скобок около позиции {i}"
            stack.pop()
        i += 1
    if quote:
        return False, "Незакрытая строка"
    if block_comment:
        return False, "Незакрытый блок комментария"
    if stack:
        return False, "Не закрыты скобки/массивы"
    return True, ""


def material_objects(data: object):
    if not isinstance(data, dict):
        return []
    result = []
    for key, value in data.items():
        if isinstance(value, dict) and value.get("class") == "Material":
            result.append((key, value))
    return result


def normalize_glass_materials(path: Path) -> list[dict]:
    text = read_text(path)
    try:
        data = json.loads(text)
    except Exception:
        return []
    changed = []
    for key, mat in material_objects(data):
        identity = " ".join(str(mat.get(k, "")) for k in ("name", "mapTo", "materialTag0", "materialTag1")).lower()
        if not any(token in identity for token in ("glass", "window", "windshield", "windscreen")):
            continue
        updates = {}
        if mat.get("translucent") is not True:
            mat["translucent"] = True
            updates["translucent"] = True
        if not mat.get("translucentBlendOp"):
            mat["translucentBlendOp"] = "PreMulAlpha"
            updates["translucentBlendOp"] = "PreMulAlpha"
        if "castShadows" not in mat:
            mat["castShadows"] = False
            updates["castShadows"] = False
        if "translucentRecvShadows" not in mat:
            mat["translucentRecvShadows"] = True
            updates["translucentRecvShadows"] = True
        if updates:
            changed.append({"material": key, "updates": updates})
    if changed:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", "utf-8")
    return changed


def analyze_tree(root: Path, wishes: str, include_limitations: bool = True) -> dict:
    issues: list[dict] = []
    fixed = 0
    warnings = 0
    ok_checks = 0
    files = [p for p in root.rglob("*") if p.is_file()]
    file_set = {p.relative_to(root).as_posix() for p in files}
    ci = case_index(root)

    duplicates = [v for v in ci.values() if len(v) > 1]
    if duplicates:
        for group in duplicates:
            warnings += 1
            issues.append({"level": "warning", "title": "Дублирующиеся пути без учёта регистра", "details": ", ".join(group)})
    else:
        ok_checks += 1

    for path in files:
        rel = path.relative_to(root).as_posix()
        ext = path.suffix.lower()
        text = read_text(path) if ext in TEXT_EXTS or path.name.endswith(".materials.json") else ""

        if ext in {".json", ".pc"} or path.name.endswith(".materials.json"):
            try:
                json.loads(text)
                ok_checks += 1
            except Exception as exc:
                warnings += 1
                issues.append({"level": "warning", "title": "Файл не удалось разобрать как JSON", "details": f"{rel}: {exc}"})

        if ext == ".jbeam":
            good, msg = bracket_balance(text)
            if good:
                ok_checks += 1
            else:
                warnings += 1
                issues.append({"level": "warning", "title": "JBeam имеет несостыковку скобок/строк", "details": f"{rel}: {msg}"})

        if "NO TEXTURE" in text.upper():
            warnings += 1
            issues.append({"level": "warning", "title": "Найдена явная отметка NO TEXTURE", "details": rel})

        for match in list(RESOURCE_RE.finditer(text))[:MISSING_RESOURCE_MAX]:
            ref = match.group("path").replace("\\", "/")
            resolved = resolve_ref(ref, file_set, ci)
            if resolved is None:
                candidates = resolve_candidates(ref, file_set)
                if len(candidates) == 1 and replace_case_reference(path, ref, candidates[0]):
                    fixed += 1
                    issues.append({"level": "fixed", "title": "Восстановлена ссылка на существующий ресурс", "details": f"{rel}: {ref} → {candidates[0]}"})
                else:
                    warnings += 1
                    detail = f"{rel} → {ref}"
                    if candidates:
                        detail += "; похожие файлы: " + ", ".join(candidates)
                    issues.append({"level": "warning", "title": "Ссылка на ресурс не найдена", "details": detail})
            elif resolved != ref:
                if replace_case_reference(path, ref, resolved):
                    fixed += 1
                    issues.append({"level": "fixed", "title": "Исправлен путь к ресурсу", "details": f"{rel}: {ref} → {resolved}"})
                else:
                    warnings += 1
                    issues.append({"level": "warning", "title": "Найдена ссылка на ресурс с отличием пути", "details": f"{rel}: {ref} → {resolved}"})
            else:
                ok_checks += 1

        if ext == ".json" or path.name.endswith(".materials.json"):
            try:
                parsed = json.loads(read_text(path))
                glass_changes = normalize_glass_materials(path)
                if glass_changes:
                    fixed += len(glass_changes)
                    for change in glass_changes:
                        issues.append({
                            "level": "fixed",
                            "title": "Нормализованы параметры прозрачного материала",
                            "details": f"{rel}: {change['material']} → " + ", ".join(f"{k}={v}" for k, v in change["updates"].items()),
                        })
                else:
                    glass_materials = [key for key, mat in material_objects(parsed) if any(token in " ".join(str(mat.get(k, "")) for k in ("name", "mapTo", "materialTag0", "materialTag1")).lower() for token in ("glass", "window", "windshield", "windscreen"))]
                    if glass_materials:
                        ok_checks += 1
                        issues.append({"level": "ok", "title": "Материалы стекла проверены", "details": ", ".join(glass_materials[:8])})
            except Exception:
                pass

    focus = []
    wl = wishes.lower()
    for word, label in (("стек", "стекло"), ("glass", "стекло"), ("свет", "освещение"), ("light", "освещение"), ("текстур", "текстуры"), ("texture", "текстуры"), ("jbeam", "JBeam"), ("материал", "материалы"), ("material", "материалы")):
        if word in wl and label not in focus:
            focus.append(label)
    if focus:
        issues.append({"level": "ok", "title": "Фокус проверки принят", "details": ", ".join(focus)})

    if include_limitations:
        issues.append({
        "level": "info",
        "title": "Проверка ограничена содержимым архива",
            "details": "Сервис анализирует файлы, ссылки и материалы. Геометрию, отражения и итоговое изображение в запущенной игре эта версия не подтверждает.",
        })

    return {
        "summary": {
            "files_checked": len(files),
            "fixed": fixed,
            "warnings": warnings,
            "ok_checks": ok_checks,
            "ok": warnings == 0,
        },
        "issues": issues,
        "wishes": wishes,
        "focus": focus,
    }


def extract_zip(zip_path: Path, dest: Path) -> tuple[int, int]:
    try:
        archive = ZipFile(zip_path)
    except BadZipFile as exc:
        raise ValueError("Файл не является корректным ZIP-архивом.") from exc
    total = 0
    count = 0
    with archive:
        infos = archive.infolist()
        if len(infos) > MAX_FILES:
            raise ValueError(f"В архиве слишком много файлов: {len(infos)}.")
        for info in infos:
            name = info.filename.replace("\\", "/")
            if info.is_dir():
                continue
            rel = safe_rel(name)
            mode = (info.external_attr >> 16) & 0xFFFF
            if (mode & 0o170000) == 0o120000:
                raise ValueError(f"Архив содержит символическую ссылку: {rel}")
            total += info.file_size
            if total > MAX_UNPACKED:
                raise ValueError("Распакованный архив превышает безопасный лимит анализа.")
            out = dest / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info, "r") as src, out.open("wb") as dst:
                shutil.copyfileobj(src, dst, 8 * 1024 * 1024)
            count += 1
    return count, total


async def save_uploads(files: list[UploadFile], relative_paths: list[str], dest: Path) -> int:
    if len(files) > MAX_FILES:
        raise HTTPException(400, f"Слишком много файлов. Максимум {MAX_FILES}.")
    total = 0
    for index, upload in enumerate(files):
        raw = relative_paths[index] if index < len(relative_paths) else (upload.filename or f"file_{index}")
        rel = safe_rel(raw)
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("wb") as fh:
            while True:
                chunk = await upload.read(8 * 1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_UPLOAD:
                    raise HTTPException(413, "Общий размер загрузки превышает 2 ГБ.")
                fh.write(chunk)
        await upload.close()
    return total


def make_fixed_zip(root: Path, out: Path) -> None:
    with ZipFile(out, "w", ZIP_DEFLATED) as archive:
        for path in root.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(root).as_posix())


async def cleanup_job_later(job_id: str, root: Path) -> None:
    await asyncio.sleep(2 * 60 * 60)
    shutil.rmtree(root, ignore_errors=True)
    jobs.pop(job_id, None)


async def set_stage(job, index, key, label, detail, progress, total_files=0, eta=None):
    job.update(stage=key, stage_index=index, stage_label=label, stage_detail=detail, progress=progress,
               total_files=total_files, eta_seconds=eta)
    await asyncio.sleep(0.05)


async def wait_if_paused(job):
    if job.get("cancel_requested"):
        raise asyncio.CancelledError()
    while job.get("paused") and job.get("status") not in {"error", "done", "cancelled"}:
        if job.get("cancel_requested"):
            raise asyncio.CancelledError()
        await asyncio.sleep(0.4)


def output_name(original_name: str, suffix: str) -> str:
    safe_original = Path(original_name).name or "beamng_mod.zip"
    stem = Path(safe_original).stem
    suffix = re.sub(r"[^A-Za-z0-9._-]+", "_", suffix.strip())[:40] or "FIXED"
    return f"{stem}_{suffix}.zip"


async def run_job(job_id: str, root: Path, original_name: str, source_kind: str, wishes: str, uploaded_bytes: int, output_suffix: str) -> None:
    job = jobs[job_id]
    try:
        await set_stage(job, 1, "prepare", "Подготавливаем файлы", "Проверяем формат, безопасные пути и количество файлов.", 5, 0, 60)
        await wait_if_paused(job)
        payload = root / "payload"
        source = root / "source"
        if source_kind == "zip":
            payload.mkdir(parents=True, exist_ok=True)
            count, unzipped = extract_zip(source / "upload.zip", payload)
            job["source_file_count"] = count
            job["unpacked_bytes"] = unzipped
        else:
            payload = source
            count = sum(1 for p in payload.rglob("*") if p.is_file())
            job["source_file_count"] = count
        total_files = max(1, count)

        await set_stage(job, 2, "structure", "Структура и безопасность", "Проверяем вложенные папки, дубли, небезопасные пути и структуру архива.", 14, total_files, 50)
        await wait_if_paused(job)
        files = [p for p in payload.rglob("*") if p.is_file()]
        job["checked_files"] = len(files)

        await set_stage(job, 3, "syntax", "Конфигурации и синтаксис", "Проверяем JSON, PC, JBeam и другие текстовые конфигурации.", 27, total_files, 40)
        await wait_if_paused(job)
        await asyncio.sleep(0.05)

        await set_stage(job, 4, "resources", "Ресурсы и ссылки", "Ищем потерянные текстуры, модели, конфигурации и ссылки с неправильным регистром.", 40, total_files, 35)
        await wait_if_paused(job)
        await asyncio.sleep(0.05)

        await set_stage(job, 5, "repair", "Автоисправление", "Применяем только изменения, которые можно подтвердить содержимым самого мода.", 54, total_files, 30)
        await wait_if_paused(job)
        report = analyze_tree(payload, wishes)

        await set_stage(job, 6, "deep_repair", "Глубокая проверка исправлений", "После исправлений повторно проверяем изменённые файлы и связи между ними.", 67, total_files, 20)
        await wait_if_paused(job)
        second = analyze_tree(payload, wishes, include_limitations=False)
        # The second pass is the authoritative post-repair pass. Keep only newly discovered warnings.
        first_warn = {(x.get("title"), x.get("details")) for x in report["issues"] if x.get("level") == "warning"}
        new_warn = [x for x in second["issues"] if x.get("level") == "warning" and (x.get("title"), x.get("details")) not in first_warn]
        if new_warn:
            report["issues"].extend(new_warn)
            report["summary"]["warnings"] += len(new_warn)

        await set_stage(job, 7, "recheck", "Полная повторная проверка", "Перепроверяем весь мод после исправлений, чтобы убедиться, что изменения не создали новые проблемы.", 80, total_files, 12)
        await wait_if_paused(job)
        final_check = analyze_tree(payload, wishes, include_limitations=False)
        remaining = [x for x in final_check["issues"] if x.get("level") == "warning"]
        report["summary"]["warnings"] = len(remaining)
        report["summary"]["ok"] = len(remaining) == 0
        report["summary"]["ok_checks"] = max(report["summary"].get("ok_checks", 0), final_check["summary"].get("ok_checks", 0))
        report["issues"] = [x for x in report["issues"] if x.get("level") != "warning"] + remaining

        await set_stage(job, 8, "final", "Финальная проверка выдачи", "Проверяем, что итоговый архив можно собрать и скачать с выбранным именем.", 92, total_files, 5)
        await wait_if_paused(job)
        fixed_name = output_name(original_name, output_suffix)
        fixed = root / fixed_name
        make_fixed_zip(payload, fixed)
        if not fixed.exists() or fixed.stat().st_size == 0:
            raise ValueError("Итоговый архив не удалось создать.")

        report.update(archive_name=original_name, source_kind=source_kind, uploaded_bytes=uploaded_bytes,
                      app_version=APP_VERSION, beamng_version=BEAMNG_VERSION,
                      fixed_archive_name=fixed_name, output_type="zip", download_url=f"/api/jobs/{job_id}/download",
                      limitations=[
                          "Не запускает сам BeamNG.drive и не выполняет полноценный визуальный рендер сцены.",
                          "Не может гарантировать исправление неизвестной логики Lua или физики без запуска игры.",
                          "Не скачивает сторонние ассеты из интернета и не копирует закрытые игровые ресурсы BeamNG.",
                          "PNG/JPG и другие обычные документы вне структуры BeamNG-мода не являются отдельным поддерживаемым продуктом сервиса."
                      ])
        (root / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
        await set_stage(job, 9, "done", "Готово", "Мод прошёл финальную проверку. Архив подготовлен к скачиванию.", 100, total_files, 0)
        job.update(status="done", report=report, output=str(fixed), eta_seconds=0)
    except asyncio.CancelledError:
        job.update(status="cancelled", stage="cancelled", stage_label="Остановлено пользователем", stage_detail="Обработка остановлена.", progress=0)
    except Exception as exc:
        job.update(status="error", stage="error", stage_index=9, stage_label="Ошибка", stage_detail=str(exc), progress=0, error=str(exc), eta_seconds=None)
    finally:
        asyncio.create_task(cleanup_job_later(job_id, root))


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(HTML)


@app.get("/api/health")
async def health():
    return {"ok": True, "service": APP_NAME, "app_version": APP_VERSION, "beamng_version": BEAMNG_VERSION, "max_upload_bytes": MAX_UPLOAD, "config": CONFIG}


@app.post("/api/analyze")
async def analyze(
    request: Request,
    source_kind: str = Form("zip"),
    wishes: str = Form(""),
    files: list[UploadFile] = File(...),
    relative_paths: list[str] = Form(default=[]),
    output_suffix: str = Form("FIXED"),
    output_type: str = Form("zip"),
):
    cid = client_id(request)
    remaining = int(large_cooldowns.get(cid, 0) - time.time())
    if remaining > 0:
        raise HTTPException(429, f"Большая загрузка временно ограничена. Повторите через {remaining // 60} мин {remaining % 60:02d} сек.")
    if not files:
        raise HTTPException(400, "Выберите ZIP или папку.")
    content_length = int(request.headers.get("content-length", "0") or 0)
    if content_length > MAX_UPLOAD + 10 * 1024 * 1024:
        raise HTTPException(413, "Загрузка превышает лимит 2 ГБ.")

    job_id = uuid.uuid4().hex
    root = WORK_ROOT / job_id
    root.mkdir(parents=True)
    source = root / "source"
    source.mkdir()
    original_name = files[0].filename or "beamng_mod.zip"
    try:
        if source_kind == "zip":
            if len(files) != 1:
                raise HTTPException(400, "Для ZIP выберите один файл.")
            total = 0
            upload = files[0]
            out = source / "upload.zip"
            with out.open("wb") as fh:
                while True:
                    chunk = await upload.read(8 * 1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_UPLOAD:
                        raise HTTPException(413, "Файл превышает 2 ГБ.")
                    fh.write(chunk)
            await upload.close()
        else:
            total = await save_uploads(files, relative_paths, source)
        if total >= LARGE_JOB_THRESHOLD:
            large_cooldowns[cid] = time.time() + LARGE_JOB_COOLDOWN
        jobs[job_id] = {"status": "queued", "stage": "upload", "stage_index": 1, "stage_label": "Файл принят. Запускаем проверку…", "stage_detail": "Подготавливаем задачу.", "progress": 2, "created_at": time.time(), "report": None, "paused": False, "cancel_requested": False, "eta_seconds": 60}
        asyncio.create_task(run_job(job_id, root, original_name, source_kind, wishes, total, output_suffix))
        return {"job_id": job_id, "status": "queued", "uploaded_bytes": total}
    except Exception:
        shutil.rmtree(root, ignore_errors=True)
        raise


@app.get("/api/jobs/{job_id}")
async def status(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Задание не найдено или срок его хранения истёк.")
    return {k: v for k, v in job.items() if k != "output"}


@app.get("/api/jobs/{job_id}/download")
async def download(job_id: str):
    job = jobs.get(job_id)
    if not job or job.get("status") != "done":
        raise HTTPException(404, "Готовый архив ещё недоступен.")
    path = Path(job["output"])
    if not path.exists():
        raise HTTPException(404, "Файл уже удалён.")
    filename = path.name.replace('"', "_")
    return FileResponse(path, filename=filename, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.post("/api/jobs/{job_id}/pause")
async def pause_job(job_id: str):
    job = jobs.get(job_id)
    if not job or job.get("status") not in {"queued", "running"}:
        raise HTTPException(404, "Задание не активно.")
    job["paused"] = not job.get("paused", False)
    job["status"] = "paused" if job["paused"] else "running"
    return {"ok": True, "paused": job["paused"]}


@app.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id: str):
    job = jobs.get(job_id)
    if not job or job.get("status") in {"done", "error", "cancelled"}:
        raise HTTPException(404, "Задание уже завершено.")
    job["status"] = "cancelled"
    job["cancel_requested"] = True
    return {"ok": True}


@app.get("/api/jobs/{job_id}/files")
async def job_files(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Задание не найдено.")
    root = Path(job.get("output", "")) if job.get("output") else WORK_ROOT / job_id / "payload"
    if root.name.endswith(".zip"):
        root = root.parent / "payload"
    if not root.exists():
        raise HTTPException(404, "Текущие файлы больше недоступны.")
    files = [p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()]
    return {"files": files[:2000], "truncated": len(files) > 2000}


@app.get("/robots.txt")
async def robots():
    return PlainTextResponse("User-agent: *\nAllow: /\n", media_type="text/plain")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), workers=1)
