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
MAX_UPLOAD = 2 * 1024 * 1024 * 1024
MAX_UNPACKED = 4 * 1024 * 1024 * 1024
MAX_FILES = 12000
LARGE_JOB_THRESHOLD = 1 * 1024 * 1024 * 1024
LARGE_JOB_COOLDOWN = 15 * 60
WORK_ROOT = Path(os.environ.get("MODFORGE_WORK_ROOT", "/tmp/modforge"))
ASSET_ROOT = Path(__file__).resolve().parent / "assets"
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
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#0a0a0a">
<meta name="description" content="ModForge — проверка и безопасное исправление BeamNG модов.">
<link rel="icon" type="image/png" href="/assets/logo.png">
<title>ModForge — BeamNG Mod Repair</title>
<style>
:root{--bg:#080808;--panel:#111;--panel2:#151515;--line:#2a2a2a;--line2:#3a3a3a;--text:#f5f5f5;--muted:#9b9b9b;--orange:#ff7a18;--orange2:#ff9d4d;--red:#ff6b6b;--yellow:#f2c14e;--blue:#78bfff;--green:#6fdf9d}
*{box-sizing:border-box}html{background:var(--bg);color-scheme:dark}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 Inter,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif}button,input,textarea{font:inherit}a{color:inherit}.shell{width:min(1440px,100%);margin:auto;padding:22px clamp(14px,3vw,42px) 46px}.top{display:flex;align-items:center;justify-content:space-between;gap:20px;padding:4px 0 20px;border-bottom:1px solid var(--line)}.brand{display:flex;align-items:center;gap:12px;min-width:0}.brand img{width:42px;height:42px;border-radius:10px;object-fit:contain;background:#0f0f0f;border:1px solid var(--line)}.brand h1{margin:0;font-size:21px;line-height:1.1;white-space:nowrap}.brand small{display:block;color:var(--muted);margin-top:4px;font-size:12px}.status{border:1px solid var(--line);color:var(--muted);padding:7px 10px;border-radius:8px;font-size:12px;white-space:nowrap}.banner{margin:22px 0 24px;display:none;border:1px solid var(--line);background:#0f0f0f;overflow:hidden;border-radius:12px}.banner img{display:block;width:100%;height:auto;max-height:48vh;object-fit:cover}.layout{display:grid;grid-template-columns:minmax(0,1.25fr) minmax(280px,.75fr);gap:20px}.card{background:var(--panel);border:1px solid var(--line);border-radius:14px}.main{padding:clamp(20px,3vw,34px)}.side{padding:24px}.eyebrow{display:inline-block;color:var(--orange);border:1px solid #5a3318;padding:5px 8px;border-radius:7px;font-size:11px;text-transform:uppercase;letter-spacing:.04em}h2{font-size:clamp(30px,4vw,48px);line-height:1.03;max-width:850px;margin:17px 0 12px;letter-spacing:-.03em}h3{margin:0 0 14px;font-size:17px}p{color:var(--muted);margin:0 0 17px}.drop{margin-top:24px;padding:30px 22px;border:1px dashed #4a4a4a;border-radius:12px;background:#0d0d0d;text-align:center;transition:.15s}.drop.active{border-color:var(--orange);background:#14100c}.drop .icon{font-size:24px;color:var(--orange)}.drop h3{margin:8px 0 4px}.drop p{font-size:13px;margin-bottom:16px}.actions{display:flex;gap:9px;flex-wrap:wrap}.center{justify-content:center}.btn{appearance:none;border:1px solid transparent;border-radius:8px;padding:10px 14px;font-weight:700;cursor:pointer;transition:.15s;text-decoration:none;display:inline-flex;align-items:center;justify-content:center;min-height:42px}.btn:hover{filter:brightness(1.08)}.btn:disabled{opacity:.45;cursor:not-allowed;filter:none}.primary{background:var(--orange);color:#160b03}.secondary{background:#191919;border-color:var(--line2);color:var(--text)}.ghost{background:transparent;border-color:var(--line);color:var(--muted)}.fileinfo{display:none;margin-top:14px;text-align:left;padding:12px;border:1px solid var(--line);border-radius:10px;background:#101010}.fileinfo strong{display:block}.hint{font-size:12px;color:var(--muted);margin-top:4px}.grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:14px}.field label{display:block;font-size:12px;color:#d2d2d2;margin:0 0 7px}.field textarea{width:100%;min-height:118px;resize:vertical;background:#0c0c0c;border:1px solid var(--line);border-radius:9px;color:var(--text);padding:11px;outline:none}.field textarea:focus{border-color:var(--orange)}.feature{padding:13px 0;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;gap:12px}.feature:last-of-type{border-bottom:0}.feature span:last-child{color:var(--orange);font-weight:700}.info{margin-top:16px;padding:13px;border:1px solid var(--line);border-left:3px solid var(--orange);background:#101010;border-radius:8px;color:#bdbdbd;font-size:12px}.section{margin-top:20px;padding:24px}.process{display:grid;grid-template-columns:repeat(5,1fr);gap:8px}.step{min-height:90px;padding:12px;border:1px solid var(--line);border-radius:9px;background:#0d0d0d;color:var(--muted)}.step b{display:block;color:var(--text);margin-bottom:5px}.step.active{border-color:#784015;background:#17110b;color:#d8d8d8}.step.done{border-color:#5b5b5b}.progress{display:none;margin-top:16px}.bar{height:8px;background:#0b0b0b;border:1px solid var(--line);border-radius:99px;overflow:hidden}.bar i{display:block;height:100%;width:0;background:var(--orange);transition:width .2s}.progressrow{display:flex;justify-content:space-between;gap:12px;margin-top:7px;font-size:12px;color:var(--muted)}.result{display:none}.summary{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}.stat{padding:15px;border:1px solid var(--line);border-radius:9px;background:#0d0d0d}.stat .n{font-size:26px;font-weight:800}.stat small{color:var(--muted)}.good{color:var(--green)}.bad{color:var(--red)}.warn{color:var(--yellow)}.issues{display:grid;gap:8px;margin-top:13px}.issue{padding:13px;border:1px solid var(--line);border-radius:9px;background:#0d0d0d}.tag{display:inline-block;padding:3px 6px;border-radius:5px;font-size:10px;font-weight:800;margin-right:7px}.tag.fixed{background:#341818;color:#ff8e8e}.tag.warning{background:#302615;color:#f7d878}.tag.info{background:#152535;color:#99d4ff}.tag.ok{background:#173025;color:#86e9ac}.issue small{display:block;color:var(--muted);margin-top:6px;word-break:break-word}.downloadbox{display:flex;flex-wrap:wrap;gap:9px;margin-top:14px}.footer{margin-top:28px;padding-top:18px;border-top:1px solid var(--line);display:flex;justify-content:space-between;gap:18px;flex-wrap:wrap;color:#747474;font-size:12px}.supportLink{display:none}.adbox{display:none;margin-top:20px;min-height:80px;padding:16px;border:1px dashed #383838;border-radius:9px;color:#7c7c7c}.hidden{display:none!important}
@media(max-width:980px){.layout{grid-template-columns:1fr}.process{grid-template-columns:1fr 1fr}.side{order:2}}
@media(max-width:640px){.shell{padding:14px 10px 32px}.top{align-items:flex-start}.brand h1{font-size:19px}.brand img{width:38px;height:38px}.status{font-size:11px}.main,.side,.section{padding:18px}.grid2{grid-template-columns:1fr}.process{grid-template-columns:1fr}.summary{grid-template-columns:1fr 1fr}.drop{padding:24px 15px}.downloadbox .btn{width:100%}}
@media(min-width:1800px){body{font-size:17px}.shell{padding-top:32px}.main{padding:44px}}
@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important;transition:none!important}}
</style>
</head>
<body>
<div class="shell">
<header class="top">
  <div class="brand"><img src="/assets/logo.png" alt="ModForge" onerror="this.style.visibility='hidden'"><div><h1 id="brandName">ModForge</h1><small id="brandTagline">BeamNG mod repair</small></div></div>
  <div class="status" id="serviceStatus">● проверка сервиса…</div>
</header>
<div class="banner" id="banner"><img src="/assets/banner.png" alt="ModForge" onerror="this.parentElement.style.display='none'"></div>
<main>
<section class="layout">
<div class="card main">
  <span class="eyebrow">BeamNG • ZIP / ПАПКА • автоматическая обработка</span>
  <h2>Проверить мод. Исправить возможное. Получить чистый архив.</h2>
  <p>ModForge анализирует структуру мода, ссылки на ресурсы, JBeam, JSON, PC и материалы. Однозначные проблемы исправляются автоматически, а спорные места остаются в отчёте с пояснением.</p>
  <div class="drop" id="drop">
    <div class="icon">↑</div>
    <h3>Перетащите ZIP или выберите файлы мода</h3>
    <p>Поддерживается ZIP и выбор папки через файловый менеджер. Лимит приложения — 2 ГБ.</p>
    <div class="actions center"><button class="btn primary" id="zipBtn">Выбрать ZIP</button><button class="btn secondary" id="folderBtn">Выбрать папку</button></div>
    <input id="zipInput" type="file" accept=".zip,application/zip" hidden>
    <input id="folderInput" type="file" webkitdirectory directory multiple hidden>
    <div class="fileinfo" id="fileInfo"></div>
  </div>
  <div class="grid2">
    <div class="field"><label for="wishes">Что проверить в первую очередь</label><textarea id="wishes" placeholder="Например: стекло, материалы салона, освещение, NO TEXTURE, ссылки на текстуры."></textarea></div>
    <div class="info"><b>Что делает автоисправление</b><br><br>• восстанавливает уникальные ссылки на существующие файлы;<br>• исправляет только регистр путей, когда найден единственный вариант;<br>• нормализует безопасные параметры прозрачных материалов;<br>• сохраняет спорные проблемы в отчёте вместо рискованной подмены файлов.</div>
  </div>
  <div class="progress" id="progressBox"><div class="bar"><i id="bar"></i></div><div class="progressrow"><span id="progressText">Подготовка…</span><span id="progressPct">0%</span></div></div>
  <div class="actions" style="margin-top:16px"><button class="btn primary" id="startBtn" disabled>Начать проверку</button><button class="btn ghost" id="clearBtn">Сбросить</button></div>
</div>
<div class="card side">
  <h3>Проверки</h3>
  <div class="feature"><span>Структура ZIP</span><span>✓</span></div>
  <div class="feature"><span>JBeam / PC / JSON</span><span>✓</span></div>
  <div class="feature"><span>Поиск ресурсов</span><span>✓</span></div>
  <div class="feature"><span>Восстановление ссылок</span><span>Авто</span></div>
  <div class="feature"><span>Материалы стекла</span><span>Авто</span></div>
  <div class="feature"><span>NO TEXTURE</span><span>Проверка</span></div>
  <div class="info"><b>Визуальная проверка в самой игре</b><br>В этой версии сервис анализирует файлы и материалы, но не подменяет результат реального запуска BeamNG. Полноценный 3D-рендер — отдельный этап развития сервиса.</div>
  <div class="info"><b>Большие архивы</b><br>Лимит ModForge — до 2 ГБ. На бесплатной инфраструктуре очень большие загрузки всё равно могут зависеть от доступных ресурсов платформы.</div>
</div>
</section>
<section class="card section"><h3>Этапы проверки</h3><div class="process"><div class="step" id="s1"><b>01 · Загрузка</b>Приём ZIP или папки.</div><div class="step" id="s2"><b>02 · Структура</b>Пути, архив, содержимое.</div><div class="step" id="s3"><b>03 · Анализ</b>JBeam, материалы, ресурсы.</div><div class="step" id="s4"><b>04 · Исправление</b>Только безопасные изменения.</div><div class="step" id="s5"><b>05 · Результат</b>Отчёт и готовый ZIP.</div></div></section>
<section class="card section result" id="result"><h3 id="resultTitle">Результат</h3><p id="resultLead"></p><div class="summary"><div class="stat"><div class="n good" id="statGood">0</div><small>Проверок OK</small></div><div class="stat"><div class="n bad" id="statFixed">0</div><small>Исправлено</small></div><div class="stat"><div class="n warn" id="statWarn">0</div><small>Осталось предупреждений</small></div><div class="stat"><div class="n" id="statFiles">0</div><small>Файлов проверено</small></div></div><div class="issues" id="issues"></div><div class="downloadbox"><a class="btn primary" id="downloadBtn" style="display:none">Скачать исправленный ZIP</a><button class="btn secondary" id="reportBtn" style="display:none">Скачать отчёт JSON</button></div></section>
<section class="card section" id="supportSection" style="display:none"><h3>Поддержать ModForge</h3><p>Поддержка помогает развивать сервис, добавлять новые проверки и улучшать автоматическое исправление модов.</p><a class="btn secondary" id="supportBtn" target="_blank" rel="noopener">Поддержать проект</a></section>
<div class="adbox" id="adbox"></div>
</main>
<footer class="footer"><span>ModForge · временная обработка файлов</span><span id="footerSupport"></span></footer>
</div>
<script>
const $=id=>document.getElementById(id);let selected=[];let selectedKind='';let reportCache=null;let siteConfig={};const maxBytes=2*1024*1024*1024;
function bytes(n){let u=['B','KB','MB','GB'],i=0;while(n>=1024&&i<3){n/=1024;i++}return n.toFixed(i?1:0)+' '+u[i]}
function setStep(n){for(let i=1;i<=5;i++){const e=$('s'+i);e.className='step'+(i===n?' active':i<n?' done':'')}}
function setStatus(t){$('serviceStatus').textContent='● '+t}
async function health(){try{const r=await fetch('/api/health');const d=await r.json();setStatus(r.ok?'сервис работает':'сервис недоступен');siteConfig=d.config||{};document.title=(siteConfig.brand_name||'ModForge')+' — BeamNG Mod Repair';$('brandName').textContent=siteConfig.brand_name||'ModForge';$('brandTagline').textContent=siteConfig.tagline||'BeamNG mod repair';if(siteConfig.support_url){$('supportSection').style.display='block';$('supportBtn').href=siteConfig.support_url;$('supportBtn').textContent=siteConfig.support_label||'Поддержать проект';$('footerSupport').innerHTML='<a href="'+siteConfig.support_url.replace(/"/g,'&quot;')+'" target="_blank" rel="noopener">Поддержка проекта</a>'}if(siteConfig.ad_enabled&&siteConfig.ad_html){$('adbox').style.display='block';$('adbox').innerHTML=siteConfig.ad_html}}catch(e){setStatus('проверка не удалась')}}health();
$('zipBtn').onclick=()=>$('zipInput').click();$('folderBtn').onclick=()=>$('folderInput').click();
$('zipInput').onchange=e=>{selected=[...e.target.files];selectedKind='zip';showSelection()};$('folderInput').onchange=e=>{selected=[...e.target.files];selectedKind='folder';showSelection()};
function showSelection(){if(!selected.length)return;const total=selected.reduce((s,f)=>s+f.size,0);$('fileInfo').style.display='block';$('fileInfo').innerHTML='<strong>'+esc(selectedKind==='zip'?'ZIP':'Папка')+': '+selected.length+' файл(ов)</strong><div class="hint">'+bytes(total)+' · '+(total<=maxBytes?'готово к отправке':'слишком большой объём')+'</div>';$('startBtn').disabled=total>maxBytes}
const drop=$('drop');['dragenter','dragover'].forEach(x=>drop.addEventListener(x,e=>{e.preventDefault();drop.classList.add('active')}));['dragleave','drop'].forEach(x=>drop.addEventListener(x,e=>{e.preventDefault();drop.classList.remove('active')}));drop.addEventListener('drop',e=>{selected=[...e.dataTransfer.files];selectedKind='zip';showSelection()});
$('clearBtn').onclick=()=>{selected=[];selectedKind='';$('zipInput').value='';$('folderInput').value='';$('fileInfo').style.display='none';$('startBtn').disabled=true;$('result').style.display='none';$('progressBox').style.display='none';for(let i=1;i<=5;i++)$('s'+i).className='step';$('issues').innerHTML='';$('wishes').value=''};
$('startBtn').onclick=upload;
function upload(){const fd=new FormData();fd.append('source_kind',selectedKind);fd.append('wishes',$('wishes').value||'');selected.forEach(f=>{fd.append('files',f,f.name);fd.append('relative_paths',f.webkitRelativePath||f.name)});$('progressBox').style.display='block';$('startBtn').disabled=true;setStep(1);const xhr=new XMLHttpRequest();xhr.open('POST','/api/analyze');xhr.upload.onprogress=e=>{if(e.lengthComputable){const p=Math.round(e.loaded/e.total*100);$('bar').style.width=p+'%';$('progressPct').textContent=p+'%';$('progressText').textContent=p<100?'Загрузка файлов…':'Запуск анализа…'}};xhr.onload=()=>{let d={};try{d=JSON.parse(xhr.responseText)}catch(e){}if(xhr.status!==200)return fail(d.detail||'Ошибка загрузки');poll(d.job_id)};xhr.onerror=()=>fail('Не удалось отправить файл.');xhr.send(fd)}
async function poll(id){try{const r=await fetch('/api/jobs/'+id);const j=await r.json();if(r.status!==200)throw new Error(j.detail||'Задание не найдено');$('progressText').textContent=j.stage_label||j.stage;$('bar').style.width=Math.min(99,j.progress||0)+'%';$('progressPct').textContent=Math.min(99,j.progress||0)+'%';if(j.stage_index)setStep(j.stage_index);if(j.status==='done'){renderResult(j.report,j.report.download_url,j.report.fixed_archive_name);$('bar').style.width='100%';$('progressPct').textContent='100%';$('progressText').textContent='Готово';setStep(5);return}if(j.status==='error')return fail(j.error||'Ошибка обработки');setTimeout(()=>poll(id),1000)}catch(e){fail(e.message)}}
function esc(s){return String(s).replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]))}
function renderResult(r,url,fixedName){reportCache=r;$('result').style.display='block';$('resultTitle').textContent=r.summary.ok?'Мод в порядке':'Проверка завершена';$('resultLead').textContent=r.summary.ok?'Критичных проблем и безопасных исправлений не обнаружено.':'Проверка завершена. Исправлено: '+r.summary.fixed+'. Осталось предупреждений: '+r.summary.warnings+'.';$('statGood').textContent=r.summary.ok_checks;$('statFixed').textContent=r.summary.fixed;$('statWarn').textContent=r.summary.warnings;$('statFiles').textContent=r.summary.files_checked;$('issues').innerHTML=r.issues.map(x=>{const cls=x.level==='fixed'?'fixed':x.level==='warning'?'warning':x.level==='info'?'info':'ok';const lab=x.level==='fixed'?'ИСПРАВЛЕНО':x.level==='warning'?'ПРЕДУПРЕЖДЕНИЕ':x.level==='info'?'ИНФО':'OK';return '<div class="issue"><span class="tag '+cls+'">'+lab+'</span><strong>'+esc(x.title)+'</strong><small>'+esc(x.details||'')+'</small></div>'}).join('');$('downloadBtn').style.display='inline-flex';$('downloadBtn').href=url;$('downloadBtn').setAttribute('download',fixedName||'modforge_fixed.zip');$('reportBtn').style.display='inline-flex'}
$('reportBtn').onclick=()=>{if(!reportCache)return;const name=((reportCache.archive_name||'modforge').replace(/\.zip$/i,'')||'modforge')+'_report.json';const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(reportCache,null,2)],{type:'application/json'}));a.download=name;document.body.appendChild(a);a.click();setTimeout(()=>{URL.revokeObjectURL(a.href);a.remove()},1000)};
function fail(msg){$('startBtn').disabled=false;$('progressText').textContent='Ошибка';$('result').style.display='block';$('resultTitle').textContent='Не удалось завершить проверку';$('resultLead').textContent=msg;$('issues').innerHTML='<div class="issue"><span class="tag fixed">ОШИБКА</span><strong>'+esc(msg)+'</strong></div>'}
</script>
</body></html>'''


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


def analyze_tree(root: Path, wishes: str) -> dict:
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


async def run_job(job_id: str, root: Path, original_name: str, source_kind: str, wishes: str, uploaded_bytes: int) -> None:
    job = jobs[job_id]
    try:
        job.update(stage="structure", stage_index=2, stage_label="Проверяем структуру и пути…", progress=15, status="running")
        payload = root / "payload"
        source = root / "source"
        if source_kind == "zip":
            payload.mkdir(parents=True, exist_ok=True)
            count, unzipped = extract_zip(source / "upload.zip", payload)
            job["source_file_count"] = count
            job["unpacked_bytes"] = unzipped
        else:
            payload = source
            job["source_file_count"] = sum(1 for p in payload.rglob("*") if p.is_file())

        job.update(stage="analyze", stage_index=3, stage_label="Анализируем ресурсы, JBeam, материалы и конфигурации…", progress=35)
        await asyncio.sleep(0.05)
        report = analyze_tree(payload, wishes)
        report.update(archive_name=original_name, source_kind=source_kind, uploaded_bytes=uploaded_bytes)

        job.update(stage="repair", stage_index=4, stage_label="Применяем безопасные исправления…", progress=65)
        await asyncio.sleep(0.05)
        job.update(stage="report", stage_index=5, stage_label="Готовим отчёт и исправленный ZIP…", progress=85)
        safe_original = Path(original_name).name or "beamng_mod.zip"
        fixed_name = f"{Path(safe_original).stem}_FIXED.zip"
        fixed = root / fixed_name
        make_fixed_zip(payload, fixed)
        report["fixed_archive_name"] = fixed_name
        report["download_url"] = f"/api/jobs/{job_id}/download"
        (root / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
        job.update(status="done", stage="done", stage_index=5, stage_label="Готово", progress=100, report=report, output=str(fixed))
    except Exception as exc:
        job.update(status="error", stage="error", stage_index=5, stage_label="Ошибка", progress=0, error=str(exc))
    finally:
        asyncio.create_task(cleanup_job_later(job_id, root))


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(HTML)


@app.get("/api/health")
async def health():
    return {"ok": True, "service": APP_NAME, "max_upload_bytes": MAX_UPLOAD, "config": CONFIG}


@app.post("/api/analyze")
async def analyze(
    request: Request,
    source_kind: str = Form("zip"),
    wishes: str = Form(""),
    files: list[UploadFile] = File(...),
    relative_paths: list[str] = Form(default=[]),
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
        jobs[job_id] = {"status": "queued", "stage": "upload", "stage_index": 1, "stage_label": "Файл принят. Запускаем проверку…", "progress": 5, "created_at": time.time(), "report": None}
        asyncio.create_task(run_job(job_id, root, original_name, source_kind, wishes, total))
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


@app.get("/robots.txt")
async def robots():
    return PlainTextResponse("User-agent: *\nAllow: /\n", media_type="text/plain")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), workers=1)
