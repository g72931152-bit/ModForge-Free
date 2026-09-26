from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import quote
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

APP_NAME = "ModForge"
APP_VERSION = "v1 (0.28)"
BEAMNG_VERSION = "0.39"
MAX_UPLOAD = 2 * 1024 * 1024 * 1024
MAX_UNPACKED = 4 * 1024 * 1024 * 1024
MAX_FILES = 12000
LARGE_JOB_THRESHOLD = 1 * 1024 * 1024 * 1024
LARGE_JOB_COOLDOWN = 15 * 60
JOB_RETENTION = int(os.environ.get("MODFORGE_JOB_RETENTION", str(24 * 60 * 60)))
WORK_ROOT = Path(os.environ.get("MODFORGE_WORK_ROOT", "/tmp/modforge"))
FEEDBACK_PATH = Path(os.environ.get("MODFORGE_FEEDBACK_PATH", str(WORK_ROOT / "feedback.json")))
BASE_DIR = Path(__file__).resolve().parent
ASSET_ROOT = BASE_DIR / "assets"
CONFIG_PATH = BASE_DIR / "site_config.json"
WORK_ROOT.mkdir(parents=True, exist_ok=True)
ASSET_ROOT.mkdir(parents=True, exist_ok=True)

jobs: dict[str, dict] = {}
large_cooldowns: dict[str, float] = {}
feedback_lock = threading.Lock()
app = FastAPI(title=APP_NAME, docs_url=None, redoc_url=None)
app.mount("/assets", StaticFiles(directory=ASSET_ROOT), name="assets")

@app.on_event("startup")
async def restore_cleanup_tasks():
    for job_id, job in list(jobs.items()):
        if job.get("status") in {"done", "error", "cancelled"}:
            root = Path(job.get("root", ""))
            if root.exists():
                asyncio.create_task(cleanup_job_later(job_id, root))

SUPPORTED_SINGLE = {
    ".jbeam", ".pc", ".json", ".jsonc", ".lua", ".materials", ".cs", ".cfg", ".prefab",
    ".dae", ".cdae", ".dds", ".png", ".jpg", ".jpeg", ".tga", ".bmp", ".gif",
    ".mis", ".forest", ".ter", ".level.json", ".materials.json",
}
TEXT_EXTS = {".json", ".jsonc", ".jbeam", ".pc", ".lua", ".cs", ".cfg", ".materials", ".prefab", ".mis", ".forest"}
RESOURCE_EXTS = r"dds|png|jpe?g|tga|bmp|gif|dae|cdae|jbeam|json|pc|cdb|lua|materials|prefab|mis|forest|ter"
RESOURCE_RE = re.compile(rf"(?P<path>[A-Za-z0-9_@%+~.\-]+(?:[\\/][A-Za-z0-9_@%+~.\-]+)*\.(?:{RESOURCE_EXTS}))", re.I)
MAX_RESOURCE_REFS_PER_FILE = 220

DEFAULT_CONFIG = {
    "brand_name": APP_NAME,
    "tagline": "Проверка и безопасное исправление модов BeamNG.drive",
    "support_url": "",
    "support_label": "Поддержать проект",
    "ad_enabled": False,
    "ad_html": "",
    "default_suffix": "FIXED",
    "release_version": APP_VERSION,
    "beamng_version": BEAMNG_VERSION,
    "privacy_version": "2026-09-26",
}

STAGES = [
    ("intake", "Приём", "Проверяем формат, размер и безопасность входа.", 6),
    ("structure", "Структура", "Ищем дубли, странные пути и нарушения структуры.", 8),
    ("syntax", "Конфигурации", "Проверяем JSON, PC, JBeam и текстовые конфигурации.", 11),
    ("resources", "Ресурсы", "Сопоставляем внутренние ссылки с файлами.", 13),
    ("materials", "Материалы", "Проверяем стекло, материалы и явные NO TEXTURE.", 10),
    ("deep", "Глубокая проверка", "Проверяем связанные данные и подозрительные места.", 10),
    ("repair", "Исправление", "Применяем только подтверждённые безопасные исправления.", 18),
    ("verify", "Проверка исправлений", "Проверяем каждый изменённый файл.", 10),
    ("recheck", "Повторная проверка", "Запускаем полный контроль мода после изменений.", 9),
    ("package", "Сборка", "Создаём результат в выбранном формате.", 3),
    ("final", "Финал", "Открываем и проверяем итоговый файл перед выдачей.", 2),
]
TOTAL_WEIGHT = sum(x[3] for x in STAGES)

ERRORS = {
    "MF-404": "API-адрес не найден. Интерфейс открылся, но backend отвечает маршрутом 404.",
    "MF-502": "Backend вернул некорректный ответ. Попробуйте обновить страницу.",
    "MF-503": "Backend временно недоступен. Render мог уснуть или перезапускаться.",
    "MF-TIMEOUT": "Ответ сервера не пришёл вовремя. Проверьте соединение и повторите попытку.",
    "MF-413": "Файл слишком большой для текущего лимита 2 ГБ.",
    "MF-415": "Формат файла пока не поддерживается ModForge.",
    "MF-422": "Файл не похож на поддерживаемый BeamNG-ресурс.",
    "MF-409": "Слишком большая предыдущая загрузка временно ограничила новые задания.",
}


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    try:
        incoming = json.loads(CONFIG_PATH.read_text("utf-8"))
        if isinstance(incoming, dict):
            for key in cfg:
                if key in incoming:
                    cfg[key] = incoming[key]
    except Exception:
        pass
    return cfg


CONFIG = load_config()


def persist_job(job_id: str):
    job = jobs.get(job_id)
    if not job: return
    root = Path(job.get("root", ""))
    if not root: return
    try:
        meta = {k:v for k,v in job.items() if not k.startswith("_") and k not in {"output", "root", "report_path", "report"}}
        meta["job_id"] = job_id
        meta["root"] = str(root)
        meta["output"] = job.get("output")
        meta["report_path"] = job.get("report_path")
        meta["report"] = job.get("report")
        (root / "job.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), "utf-8")
    except Exception:
        pass


def restore_persisted_jobs():
    for meta_path in WORK_ROOT.glob("*/job.json"):
        try:
            meta = json.loads(meta_path.read_text("utf-8"))
            job_id = str(meta.get("job_id") or meta_path.parent.name)
            status = meta.get("status")
            if status not in {"done", "error", "cancelled"}: continue
            root = Path(meta.get("root") or meta_path.parent)
            if not root.exists(): continue
            meta["root"] = str(root)
            meta["_cancel_event"] = threading.Event()
            meta["_pause_event"] = threading.Event()
            jobs[job_id] = meta
        except Exception:
            continue


restore_persisted_jobs()


def load_feedback() -> list[dict]:
    try:
        data = json.loads(FEEDBACK_PATH.read_text("utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_feedback(items: list[dict]) -> None:
    FEEDBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = FEEDBACK_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(items[-500:], ensure_ascii=False, indent=2), "utf-8")
    tmp.replace(FEEDBACK_PATH)


def clean_feedback_item(item: dict) -> dict:
    return {k: item.get(k) for k in ("id", "name", "message", "created_at", "status", "replies", "reports")}


def service_error(code: str, message: str, status: int) -> HTTPException:
    return HTTPException(status, detail={"code": code, "message": message})


def public_job(job: dict) -> dict:
    return {k: v for k, v in job.items() if not k.startswith("_") and k not in {"output", "root", "report_path"}}


def safe_rel(raw: str) -> str:
    raw = (raw or "").replace("\\", "/").lstrip("/")
    parts = []
    for part in raw.split("/"):
        if not part or part == ".":
            continue
        if part == "..":
            raise ValueError("Обнаружен небезопасный путь файла.")
        parts.append(part)
    if not parts:
        raise ValueError("Пустой путь файла.")
    return "/".join(parts)


def read_text(path: Path, limit: int = 1_500_000) -> str:
    try:
        data = path.read_bytes()
        return data[:limit].decode("utf-8", errors="replace")
    except Exception:
        return ""


def path_set(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


def case_index(files: set[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for rel in files:
        out.setdefault(rel.casefold(), []).append(rel)
    return out


def resolve_ref(ref: str, files: set[str], ci: dict[str, list[str]]) -> str | None:
    ref = ref.replace("\\", "/").lstrip("./")
    if ref in files:
        return ref
    matches = ci.get(ref.casefold(), [])
    if len(matches) == 1:
        return matches[0]
    base = Path(ref).name.casefold()
    matches = [p for p in files if Path(p).name.casefold() == base]
    return matches[0] if len(matches) == 1 else None


def candidates_for(ref: str, files: set[str]) -> list[str]:
    base = Path(ref.replace("\\", "/")).name.casefold()
    return sorted(p for p in files if Path(p).name.casefold() == base)[:8]


def replace_reference(path: Path, old: str, new: str) -> bool:
    text = read_text(path)
    if not text:
        return False
    pattern = re.compile(re.escape(old).replace(r"\/", r"[\\/]"), re.I)
    updated, count = pattern.subn(new, text, count=1)
    if not count:
        return False
    path.write_text(updated, "utf-8")
    return True


def bracket_balance(text: str) -> tuple[bool, str]:
    stack: list[str] = []
    pairs = {")": "(", "]": "[", "}": "{"}
    quote: str | None = None
    line_comment = False
    block_comment = False
    escape = False
    i = 0
    while i < len(text):
        c = text[i]
        if line_comment:
            if c == "\n": line_comment = False
            i += 1; continue
        if block_comment:
            if c == "*" and i + 1 < len(text) and text[i + 1] == "/":
                block_comment = False; i += 2; continue
            i += 1; continue
        if quote:
            if escape: escape = False
            elif c == "\\": escape = True
            elif c == quote: quote = None
            i += 1; continue
        if c in ('"', "'"):
            quote = c; i += 1; continue
        if c == "/" and i + 1 < len(text) and text[i + 1] == "/":
            line_comment = True; i += 2; continue
        if c == "/" and i + 1 < len(text) and text[i + 1] == "*":
            block_comment = True; i += 2; continue
        if c in "([{": stack.append(c)
        elif c in ")]}":
            if not stack or stack[-1] != pairs[c]:
                return False, f"Несоответствие скобок около позиции {i}"
            stack.pop()
        i += 1
    if quote: return False, "Незакрытая строка"
    if block_comment: return False, "Незакрытый комментарий"
    if stack: return False, "Не закрыты скобки/массивы"
    return True, ""


def material_objects(data: object) -> list[tuple[str, dict]]:
    if not isinstance(data, dict): return []
    out = []
    for key, value in data.items():
        if isinstance(value, dict) and str(value.get("class", "")).lower() == "material":
            out.append((str(key), value))
    return out


def material_identity(mat: dict) -> str:
    return " ".join(str(mat.get(k, "")) for k in ("name", "mapTo", "materialTag0", "materialTag1")).lower()


def repair_glass(path: Path) -> list[dict]:
    try: data = json.loads(read_text(path))
    except Exception: return []
    if not isinstance(data, dict): return []
    changes = []
    for key, mat in material_objects(data):
        identity = material_identity(mat)
        if not any(token in identity for token in ("glass", "window", "windshield", "windscreen")):
            continue
        updates = {}
        if mat.get("translucent") is not True:
            mat["translucent"] = True; updates["translucent"] = True
        if not mat.get("translucentBlendOp"):
            mat["translucentBlendOp"] = "PreMulAlpha"; updates["translucentBlendOp"] = "PreMulAlpha"
        if mat.get("castShadows") is True:
            mat["castShadows"] = False; updates["castShadows"] = False
        if mat.get("translucentRecvShadows") is not True:
            mat["translucentRecvShadows"] = True; updates["translucentRecvShadows"] = True
        if updates: changes.append({"material": key, "updates": updates})
    if changes:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", "utf-8")
    return changes


def should_check_text(path: Path) -> bool:
    return path.suffix.lower() in TEXT_EXTS or path.name.lower().endswith(".materials.json") or path.name.lower().endswith(".level.json")


def check_cancel_pause(job: dict) -> None:
    if job["_cancel_event"].is_set():
        raise RuntimeError("__CANCELLED__")
    while job["_pause_event"].is_set():
        job["status"] = "paused"
        if job["_cancel_event"].is_set():
            raise RuntimeError("__CANCELLED__")
        time.sleep(0.20)
    if job.get("status") == "paused": job["status"] = "running"


def make_progress(job: dict, stage_index: int, stage_done: float) -> int:
    completed = sum(STAGES[i][3] for i in range(stage_index))
    weight = STAGES[stage_index][3]
    progress = int(round(((completed + weight * max(0.0, min(1.0, stage_done))) / TOTAL_WEIGHT) * 100))
    elapsed = max(0.1, time.time() - job["started_at"])
    if progress >= 3:
        job["eta_seconds"] = max(0, int(elapsed * (100 / max(progress, 1) - 1)))
    job["progress"] = progress
    job["stage_progress"] = int(stage_done * 100)
    return progress


def stage_start(job: dict, index: int, detail: str) -> None:
    key, label, description, _ = STAGES[index]
    job.update(stage_index=index + 1, stage=key, stage_label=label, stage_detail=detail or description, stage_progress=0, status="running")
    make_progress(job, index, 0)
    persist_job(next((jid for jid,j in jobs.items() if j is job), ""))


def scan_structure(root: Path, job: dict) -> list[dict]:
    files = [p for p in root.rglob("*") if p.is_file()]
    rels = [p.relative_to(root).as_posix() for p in files]
    ci = case_index(set(rels))
    issues = []
    for group in (g for g in ci.values() if len(g) > 1):
        issues.append({"level": "warning", "stage": "structure", "title": "Дублирующиеся пути без учёта регистра", "details": ", ".join(group)})
    total = max(1, len(files))
    for idx, path in enumerate(files, 1):
        check_cancel_pause(job); make_progress(job, 1, idx / total)
    return issues


def scan_syntax(root: Path, job: dict) -> list[dict]:
    files = [p for p in root.rglob("*") if p.is_file() and should_check_text(p)]
    issues = []; total = max(1, len(files))
    for idx, path in enumerate(files, 1):
        check_cancel_pause(job); text = read_text(path); ext = path.suffix.lower(); rel = path.relative_to(root).as_posix()
        if ext in {".json", ".pc"} or path.name.lower().endswith((".materials.json", ".level.json")):
            try: json.loads(text)
            except Exception as exc: issues.append({"level": "warning", "stage": "syntax", "title": "Конфигурация не разобрана как JSON", "details": f"{rel}: {exc}"})
        if ext == ".jbeam":
            ok, msg = bracket_balance(text)
            if not ok: issues.append({"level": "warning", "stage": "syntax", "title": "JBeam имеет несостыковку синтаксиса", "details": f"{rel}: {msg}"})
        make_progress(job, 2, idx / total)
    return issues


def scan_resources(root: Path, job: dict) -> list[dict]:
    files = [p for p in root.rglob("*") if p.is_file()]; file_set = {p.relative_to(root).as_posix() for p in files}; ci = case_index(file_set)
    text_files = [p for p in files if should_check_text(p)]; issues=[]; total=max(1,len(text_files))
    for idx, path in enumerate(text_files, 1):
        check_cancel_pause(job); text=read_text(path); rel=path.relative_to(root).as_posix()
        for match in list(RESOURCE_RE.finditer(text))[:MAX_RESOURCE_REFS_PER_FILE]:
            ref=match.group("path").replace("\\","/")
            if resolve_ref(ref,file_set,ci) is None:
                candidates=candidates_for(ref,file_set); detail=f"{rel} → {ref}"
                if candidates: detail += "; похожие: " + ", ".join(candidates)
                issues.append({"level":"warning","stage":"resources","title":"Внутренняя ссылка не подтверждена","details":detail})
        make_progress(job,3,idx/total)
    return issues


def scan_materials(root: Path, job: dict) -> list[dict]:
    files=[p for p in root.rglob("*") if p.is_file() and (p.suffix.lower()==".json" or p.name.lower().endswith(".materials.json"))]
    issues=[]; total=max(1,len(files))
    for idx,path in enumerate(files,1):
        check_cancel_pause(job); rel=path.relative_to(root).as_posix(); text=read_text(path)
        if "NO TEXTURE" in text.upper(): issues.append({"level":"warning","stage":"materials","title":"Найдена явная отметка NO TEXTURE","details":rel})
        try: data=json.loads(text)
        except Exception: data=None
        if isinstance(data,dict):
            glass=[key for key,mat in material_objects(data) if any(t in material_identity(mat) for t in ("glass","window","windshield","windscreen"))]
            if glass: issues.append({"level":"ok","stage":"materials","title":"Материалы стекла найдены","details":f"{rel}: {', '.join(glass[:10])}"})
        make_progress(job,4,idx/total)
    return issues


def scan_deep(root: Path, job: dict) -> list[dict]:
    files=[p for p in root.rglob("*") if p.is_file()]; issues=[]; total=max(1,len(files))
    for idx,path in enumerate(files,1):
        check_cancel_pause(job)
        rel=path.relative_to(root).as_posix(); size=path.stat().st_size
        if path.suffix.lower() in {".dds",".cdae",".dae"} and size == 0:
            issues.append({"level":"warning","stage":"deep","title":"Пустой ресурс","details":rel})
        if path.name.startswith(".") or "__MACOSX" in rel:
            issues.append({"level":"info","stage":"deep","title":"Служебный файл","details":rel})
        make_progress(job,5,idx/total)
    return issues


def repair_tree(root: Path, job: dict) -> list[dict]:
    files=[p for p in root.rglob("*") if p.is_file()]; file_set={p.relative_to(root).as_posix() for p in files}; ci=case_index(file_set)
    issues=[]; total=max(1,len(files))
    for idx,path in enumerate(files,1):
        check_cancel_pause(job); rel=path.relative_to(root).as_posix()
        if should_check_text(path):
            text=read_text(path)
            for match in list(RESOURCE_RE.finditer(text))[:MAX_RESOURCE_REFS_PER_FILE]:
                ref=match.group("path").replace("\\","/"); resolved=resolve_ref(ref,file_set,ci)
                if resolved and resolved != ref and replace_reference(path,ref,resolved):
                    issues.append({"level":"fixed","stage":"repair","title":"Исправлена внутренняя ссылка","details":f"{rel}: {ref} → {resolved}"})
                elif resolved is None:
                    candidates=candidates_for(ref,file_set)
                    if len(candidates)==1 and replace_reference(path,ref,candidates[0]):
                        issues.append({"level":"fixed","stage":"repair","title":"Восстановлена ссылка на найденный ресурс","details":f"{rel}: {ref} → {candidates[0]}"})
        if path.suffix.lower()==".json" or path.name.lower().endswith(".materials.json"):
            for change in repair_glass(path):
                detail=", ".join(f"{k}={v}" for k,v in change["updates"].items())
                issues.append({"level":"fixed","stage":"repair","title":"Нормализованы параметры материала стекла","details":f"{rel}: {change['material']} → {detail}"})
        make_progress(job,6,idx/total)
    return issues


def verify_tree(root: Path, job: dict, stage_idx: int) -> list[dict]:
    files=[p for p in root.rglob("*") if p.is_file()]; file_set={p.relative_to(root).as_posix() for p in files}; ci=case_index(file_set)
    issues=[]; text_files=[p for p in files if should_check_text(p)]; total=max(1,len(text_files))
    for idx,path in enumerate(text_files,1):
        check_cancel_pause(job); rel=path.relative_to(root).as_posix(); text=read_text(path)
        if path.suffix.lower() in {".json",".pc"} or path.name.lower().endswith((".materials.json",".level.json")):
            try: json.loads(text)
            except Exception as exc: issues.append({"level":"warning","stage":"verify","title":"JSON всё ещё некорректен после изменений","details":f"{rel}: {exc}"})
        if path.suffix.lower()==".jbeam":
            ok,msg=bracket_balance(text)
            if not ok: issues.append({"level":"warning","stage":"verify","title":"JBeam всё ещё требует проверки","details":f"{rel}: {msg}"})
        for match in list(RESOURCE_RE.finditer(text))[:MAX_RESOURCE_REFS_PER_FILE]:
            ref=match.group("path").replace("\\","/")
            if resolve_ref(ref,file_set,ci) is None: issues.append({"level":"warning","stage":"verify","title":"Ресурс всё ещё не найден","details":f"{rel} → {ref}"})
        make_progress(job,stage_idx,idx/total)
    return issues


def output_name(original: str, suffix: str, force_zip=False) -> str:
    suffix = re.sub(r"[^A-Za-z0-9._-]+", "_", (suffix or "FIXED").strip())[:48] or "FIXED"
    if force_zip: return f"{Path(original).stem or 'beamng_mod'}_{suffix}.zip"
    p=Path(original); return f"{p.stem or 'beamng_file'}_{suffix}{p.suffix}"


def package_zip(root: Path, out: Path, job: dict) -> None:
    files=[p for p in root.rglob("*") if p.is_file()]; total=max(1,len(files))
    with ZipFile(out,"w",ZIP_DEFLATED,compresslevel=6) as archive:
        for idx,path in enumerate(files,1):
            check_cancel_pause(job); archive.write(path,path.relative_to(root).as_posix()); make_progress(job,9,idx/total)


def likely_supported_folder(root: Path) -> bool:
    files=[p for p in root.rglob("*") if p.is_file()]
    if not files: return False
    exts={p.suffix.lower() for p in files}
    top={p.relative_to(root).parts[0].lower() for p in files if p.relative_to(root).parts}
    return bool(exts & (SUPPORTED_SINGLE-{".png",".jpg",".jpeg",".tga",".bmp",".gif"})) or bool(top.intersection({"vehicles","levels","scripts","art","settings","lua","mods"}))


def extract_zip(zip_path: Path, dest: Path) -> tuple[int,int]:
    try: archive=ZipFile(zip_path)
    except BadZipFile as exc: raise ValueError("Файл не является корректным ZIP-архивом.") from exc
    total=0; count=0
    with archive:
        infos=archive.infolist()
        if len(infos)>MAX_FILES: raise ValueError(f"В архиве слишком много файлов: {len(infos)}.")
        for info in infos:
            if info.is_dir(): continue
            rel=safe_rel(info.filename); total += info.file_size
            if total>MAX_UNPACKED: raise ValueError("Распакованный архив превышает безопасный лимит 4 ГБ.")
            mode=(info.external_attr>>16)&0xFFFF
            if (mode&0o170000)==0o120000: raise ValueError(f"Архив содержит символическую ссылку: {rel}")
            out=dest/rel; out.parent.mkdir(parents=True,exist_ok=True)
            with archive.open(info,"r") as src, out.open("wb") as outf:
                shutil.copyfileobj(src,outf,8*1024*1024)
            count += 1
    return count,total


async def save_folder_uploads(files: list[UploadFile], manifest: list[str], dest: Path) -> int:
    if not files: raise ValueError("Выбранная папка не содержит файлов.")
    if len(files)>MAX_FILES: raise ValueError(f"Слишком много файлов. Максимум {MAX_FILES}.")
    raw_paths=[safe_rel(manifest[i] if i<len(manifest) else (files[i].filename or f"file_{i}")) for i in range(len(files))]
    roots=[p.split("/",1)[0] for p in raw_paths]; strip_root=len(set(roots))==1 and all("/" in p for p in raw_paths)
    total=0
    for i,upload in enumerate(files):
        rel=raw_paths[i]; rel=rel.split("/",1)[1] if strip_root and "/" in rel else rel; rel=safe_rel(rel)
        out=dest/rel; out.parent.mkdir(parents=True,exist_ok=True)
        with out.open("wb") as fh:
            while True:
                chunk=await upload.read(8*1024*1024)
                if not chunk: break
                total+=len(chunk)
                if total>MAX_UPLOAD: raise ValueError("Общий размер загрузки превышает 2 ГБ.")
                fh.write(chunk)
        await upload.close()
    return total


async def save_single(upload: UploadFile, dest: Path) -> int:
    name=Path(upload.filename or "resource").name; ext=name.lower()
    if ext.endswith(".materials.json"): supported=True
    else: supported=Path(ext).suffix.lower() in SUPPORTED_SINGLE
    if not supported: raise ValueError("MF-415: этот тип файла пока не поддерживается ModForge.")
    out=dest/name; total=0
    with out.open("wb") as fh:
        while True:
            chunk=await upload.read(8*1024*1024)
            if not chunk: break
            total += len(chunk)
            if total>MAX_UPLOAD: raise ValueError("MF-413: файл превышает лимит 2 ГБ.")
            fh.write(chunk)
    await upload.close(); return total


def focus_from(priority: list[str], wishes: str) -> list[str]:
    mapping={"textures":"Текстуры","glass":"Стекло","jbeam":"JBeam","lighting":"Освещение","all":"Всё"}
    out=[mapping[x] for x in priority if x in mapping]; wl=wishes.lower()
    for word,label in (("текстур","Текстуры"),("texture","Текстуры"),("стек","Стекло"),("glass","Стекло"),("jbeam","JBeam"),("свет","Освещение"),("light","Освещение")):
        if word in wl and label not in out: out.append(label)
    return out


def report_summary(issues: list[dict], files_checked: int, fixed: int) -> dict:
    warnings=sum(1 for i in issues if i.get("level")=="warning"); oks=sum(1 for i in issues if i.get("level")=="ok")
    return {"files_checked":files_checked,"fixed":fixed,"warnings":warnings,"ok_checks":oks,"ok":warnings==0}


async def run_job(job_id: str, root: Path, original_name: str, source_kind: str, source_name: str, wishes: str, priority: list[str], uploaded_bytes: int, output_suffix: str, output_type: str) -> None:
    job=jobs[job_id]
    try:
        payload=root/"payload"; payload.mkdir(parents=True,exist_ok=True); source=root/"source"
        stage_start(job,0,"Проверяем формат, размер и безопасно готовим рабочую копию.")
        if source_kind=="zip": count,unpacked=await asyncio.to_thread(extract_zip,source/"upload.zip",payload)
        elif source_kind=="folder":
            await asyncio.to_thread(shutil.copytree,source,payload,dirs_exist_ok=True); count=sum(1 for p in payload.rglob("*") if p.is_file()); unpacked=sum(p.stat().st_size for p in payload.rglob("*") if p.is_file()); make_progress(job,0,1)
        else:
            src=next(payload.parent.joinpath("source").iterdir()); dst=payload/src.name; await asyncio.to_thread(shutil.copy2,src,dst); count=1; unpacked=dst.stat().st_size; make_progress(job,0,1)
        job["source_file_count"]=count; job["unpacked_bytes"]=unpacked
        if source_kind in {"zip","folder"} and not await asyncio.to_thread(likely_supported_folder,payload):
            raise ValueError("MF-422: содержимое не похоже на поддерживаемый BeamNG.drive мод или ресурсный набор.")
        issues=[]
        stage_start(job,1,"Проверяем структуру, имена и дублирование файлов."); issues.extend(await asyncio.to_thread(scan_structure,payload,job))
        stage_start(job,2,"Проверяем JSON, PC, JBeam и текстовые конфигурации."); issues.extend(await asyncio.to_thread(scan_syntax,payload,job))
        stage_start(job,3,"Сопоставляем внутренние ссылки с реально существующими файлами."); issues.extend(await asyncio.to_thread(scan_resources,payload,job))
        stage_start(job,4,"Проверяем материалы, стекло и явные признаки отсутствующих текстур."); issues.extend(await asyncio.to_thread(scan_materials,payload,job))
        stage_start(job,5,"Ищем дополнительные проблемы, которые требуют особого внимания."); issues.extend(await asyncio.to_thread(scan_deep,payload,job))
        stage_start(job,6,"Применяем только подтверждённые безопасные исправления."); repairs=await asyncio.to_thread(repair_tree,payload,job); issues.extend(repairs); fixed=sum(1 for i in repairs if i.get("level")=="fixed")
        stage_start(job,7,"Проверяем изменённые файлы сразу после ремонта."); issues.extend(await asyncio.to_thread(verify_tree,payload,job,7))
        stage_start(job,8,"Повторно запускаем полный контроль после исправлений."); issues.extend(await asyncio.to_thread(verify_tree,payload,job,8))
        focus=focus_from(priority,wishes)
        if source_kind=="single" and output_type=="same":
            original=next(p for p in payload.iterdir() if p.is_file()); out_name=output_name(source_name or original_name,output_suffix,False); out_path=root/out_name; shutil.copy2(original,out_path); make_progress(job,9,1)
        else:
            stage_start(job,9,"Собираем результат с сохранением структуры мода."); out_name=output_name(source_name or original_name,output_suffix,True); out_path=root/out_name; await asyncio.to_thread(package_zip,payload,out_path,job)
        stage_start(job,10,"Проверяем итоговый файл перед выдачей.")
        if out_path.suffix.lower()==".zip":
            with ZipFile(out_path,"r") as zf:
                infos=zf.infolist()
                if not infos: raise ValueError("Итоговый ZIP пуст.")
                for info in infos: safe_rel(info.filename)
        elif out_path.stat().st_size==0:
            raise ValueError("Итоговый файл пуст.")
        make_progress(job,10,1)
        report_issues=issues+([{"level":"ok","stage":"focus","title":"Приоритет принят","details":", ".join(focus)}] if focus else [])
        report={"service":APP_NAME,"app_version":APP_VERSION,"beamng_version":BEAMNG_VERSION,"source_name":source_name or original_name,"source_kind":source_kind,"output_type":output_type,"output_name":out_name,"uploaded_bytes":uploaded_bytes,"wishes":wishes,"priority":priority,"focus":focus,"summary":report_summary(report_issues,count,fixed),"issues":report_issues,"limitations":["ModForge не запускает BeamNG.drive для живого 3D-рендера.","ModForge не обещает исправить неизвестную Lua-логику, физику и ошибки, для которых нужен реальный запуск игры.","ModForge не скачивает и не копирует закрытые игровые ассеты BeamNG.","Отдельные изображения и другие поддерживаемые ресурсы можно анализировать, но их пиксельное содержимое автоматически не редактируется."],"download_url":f"/api/jobs/{job_id}/download","report_url":f"/api/jobs/{job_id}/report"}
        report_path=root/"report.json"; report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2),"utf-8")
        job.update(report=report,output=str(out_path),report_path=str(report_path),fixed_archive_name=out_name,download_url=f"/api/jobs/{job_id}/download",report_url=f"/api/jobs/{job_id}/report",status="done",stage_progress=100,progress=100,eta_seconds=0,stage_label="Готово",stage_detail="Финальная проверка завершена. Файл готов к скачиванию.",stage_index=len(STAGES))
        persist_job(job_id)
    except RuntimeError as exc:
        if str(exc)=="__CANCELLED__": job.update(status="cancelled",stage_label="Остановлено",stage_detail="Обработка остановлена пользователем.",progress=0,eta_seconds=None)
        else: job.update(status="error",stage_label="Ошибка",stage_detail=str(exc),error=str(exc),eta_seconds=None)
        persist_job(job_id)
    except Exception as exc:
        msg=str(exc); job.update(status="error",stage_label="Ошибка",stage_detail=msg,error=msg,eta_seconds=None); persist_job(job_id)
    finally:
        asyncio.create_task(cleanup_job_later(job_id,root))


async def cleanup_job_later(job_id: str, root: Path):
    await asyncio.sleep(JOB_RETENTION); shutil.rmtree(root,ignore_errors=True); jobs.pop(job_id,None)
    now = time.time()
    for cid in [k for k, v in list(large_cooldowns.items()) if v < now]:
        large_cooldowns.pop(cid, None)


@app.get("/", response_class=HTMLResponse)
async def index(): return HTMLResponse((BASE_DIR/"index.html").read_text("utf-8"))

@app.get("/api/health")
async def health():
    return {"ok":True,"service":APP_NAME,"app_version":APP_VERSION,"beamng_version":BEAMNG_VERSION,"max_upload_bytes":MAX_UPLOAD,"supported_single":sorted(SUPPORTED_SINGLE),"config":CONFIG,"stages":[{"key":k,"label":l,"description":d,"weight":w} for k,l,d,w in STAGES]}

@app.post("/api/analyze")
async def analyze(request: Request, source_kind: str=Form("zip"), source_name: str=Form(""), wishes: str=Form(""), priority_json: str=Form("[]"), files: list[UploadFile]=File(...), manifest_json: str=Form("[]"), output_suffix: str=Form("FIXED"), output_type: str=Form("zip")):
    if source_kind not in {"zip","folder","single"}: raise service_error("MF-415","Поддерживаемые входы: ZIP, папка и отдельные BeamNG-ресурсы.",400)
    if output_type not in {"zip","same"}: raise service_error("MF-415","Для этого режима выбран неподдерживаемый формат выдачи.",400)
    cid=request.headers.get("x-forwarded-for","").split(",")[0].strip() or (request.client.host if request.client else "unknown")
    remaining=int(large_cooldowns.get(cid,0)-time.time())
    if remaining>0: raise service_error("MF-409",f"MF-409: повторная большая загрузка будет доступна через {remaining//60} мин {remaining%60:02d} сек.",429)
    if not files: raise service_error("MF-422","Файлы не выбраны.",400)
    if source_kind=="zip" and (len(files)!=1 or not (files[0].filename or "").lower().endswith(".zip")): raise service_error("MF-415","Для ZIP нужен один .zip файл.",400)
    if source_kind=="single" and len(files)!=1: raise service_error("MF-415","Для режима отдельного файла выберите ровно один файл.",400)
    if len(files)>MAX_FILES: raise service_error("MF-422",f"Слишком много файлов. Максимум {MAX_FILES}.",400)
    try: priority=json.loads(priority_json); priority=priority if isinstance(priority,list) else []
    except Exception: priority=[]
    try: manifest=json.loads(manifest_json); manifest=manifest if isinstance(manifest,list) else []
    except Exception: manifest=[]
    job_id=uuid.uuid4().hex; root=WORK_ROOT/job_id; source=root/"source"; root.mkdir(parents=True,exist_ok=True); source.mkdir(parents=True,exist_ok=True)
    original_name=files[0].filename or "beamng_resource"; total=0
    try:
        if source_kind=="zip":
            out=source/"upload.zip"
            with out.open("wb") as fh:
                while True:
                    chunk=await files[0].read(8*1024*1024)
                    if not chunk: break
                    total += len(chunk)
                    if total>MAX_UPLOAD: raise service_error("MF-413","Файл превышает лимит 2 ГБ.",413)
                    fh.write(chunk)
            await files[0].close(); final_source_name=Path(original_name).name
        elif source_kind=="folder":
            total=await save_folder_uploads(files,manifest,source); roots=[str(x).replace("\\","/").split("/",1)[0] for x in manifest if x]; final_source_name=source_name or (roots[0] if roots else "beamng_mod"); output_type="zip"
        else:
            total=await save_single(files[0],source); final_source_name=Path(original_name).name
        if total>=LARGE_JOB_THRESHOLD: large_cooldowns[cid]=time.time()+LARGE_JOB_COOLDOWN
        jobs[job_id]={"status":"queued","stage":"queued","stage_index":0,"stage_label":"Файл принят","stage_detail":"Проверяем доступность рабочей задачи…","stage_progress":0,"progress":0,"eta_seconds":60,"created_at":time.time(),"started_at":time.time(),"report":None,"error":None,"fixed_archive_name":None,"download_url":None,"report_url":None,"root":str(root),"output":None,"report_path":None,"_cancel_event":threading.Event(),"_pause_event":threading.Event()}
        persist_job(job_id)
        asyncio.create_task(run_job(job_id,root,original_name,source_kind,final_source_name,wishes[:5000],priority,total,output_suffix,output_type))
        return {"job_id":job_id,"status":"queued","uploaded_bytes":total}
    except HTTPException:
        shutil.rmtree(root,ignore_errors=True); raise
    except ValueError as exc:
        shutil.rmtree(root,ignore_errors=True); raise service_error("MF-422",str(exc),400)
    except Exception:
        shutil.rmtree(root,ignore_errors=True); raise service_error("MF-503","Не удалось подготовить рабочую задачу на сервере.",503)

@app.get("/api/jobs/{job_id}")
async def status(job_id:str):
    job=jobs.get(job_id)
    if not job: raise service_error("MF-404","Задание не найдено или срок его хранения истёк.",404)
    return public_job(job)

@app.post("/api/jobs/{job_id}/pause")
async def pause_job(job_id:str):
    job=jobs.get(job_id)
    if not job or job.get("status") in {"done","error","cancelled"}: raise service_error("MF-404","Задание уже завершено.",404)
    if job["_pause_event"].is_set(): job["_pause_event"].clear(); job["status"]="running"
    else: job["_pause_event"].set(); job["status"]="paused"
    return {"ok":True,"paused":job["_pause_event"].is_set()}

@app.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id:str):
    job=jobs.get(job_id)
    if not job or job.get("status") in {"done","error","cancelled"}: raise service_error("MF-404","Задание уже завершено.",404)
    job["_cancel_event"].set(); job["_pause_event"].clear(); job["status"]="cancelling"; return {"ok":True}

@app.get("/api/jobs/{job_id}/files")
async def job_files(job_id:str):
    job=jobs.get(job_id)
    if not job: raise service_error("MF-404","Задание не найдено.",404)
    root=Path(job["root"])/"payload"
    if not root.exists(): raise service_error("MF-404","Рабочие файлы уже недоступны.",404)
    files=[p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()]
    return {"files":files[:3000],"truncated":len(files)>3000}

@app.head("/api/jobs/{job_id}/download")
async def download_head(job_id: str):
    job = jobs.get(job_id)
    if not job or job.get("status") != "done": raise service_error("MF-404", "Готовый файл ещё недоступен.", 404)
    path = Path(job.get("output") or "")
    if not path.exists(): raise service_error("MF-404", "Готовый файл больше не найден.", 404)
    return JSONResponse(status_code=200, content=None, headers={"X-ModForge-Artifact": path.name, "Cache-Control": "no-store"})

@app.get("/api/jobs/{job_id}/download")
async def download(job_id:str):
    job=jobs.get(job_id)
    if not job or job.get("status")!="done": raise service_error("MF-404","Готовый файл ещё недоступен.",404)
    path=Path(job["output"])
    if not path.exists(): raise service_error("MF-404","Готовый файл больше не найден.",404)
    filename=path.name; media="application/zip" if path.suffix.lower()==".zip" else "application/octet-stream"
    return FileResponse(path,media_type=media,headers={"Content-Disposition":f"attachment; filename=\"{filename.replace('\"','_')}\"; filename*=UTF-8''{quote(filename)}"})

@app.get("/api/jobs/{job_id}/report")
async def report_download(job_id:str):
    job=jobs.get(job_id)
    if not job or job.get("status")!="done": raise service_error("MF-404","Отчёт ещё недоступен.",404)
    path=Path(job["report_path"]); filename=f"{Path(job['fixed_archive_name']).stem}_report.json"
    return FileResponse(path,media_type="application/json",headers={"Content-Disposition":f"attachment; filename=\"{filename}\"; filename*=UTF-8''{quote(filename)}"})

@app.get("/api/feedback")
async def feedback_list():
    with feedback_lock:
        items = load_feedback()
        public = []
        for item in reversed(items):
            cleaned = clean_feedback_item(item)
            cleaned["reports"] = min(int(cleaned.get("reports") or 0), 99)
            public.append(cleaned)
        return {"items": public[:100]}

@app.post("/api/feedback")
async def feedback_create(request: Request):
    try: data = await request.json()
    except Exception: data = {}
    name = str(data.get("name") or "Гость").strip()[:40] or "Гость"
    message = str(data.get("message") or "").strip()[:1200]
    if len(message) < 2: raise service_error("MF-422", "Сообщение слишком короткое.", 400)
    item = {"id": uuid.uuid4().hex[:12], "name": name, "message": message, "created_at": int(time.time()*1000), "status": "открыто", "replies": [], "reports": 0}
    with feedback_lock:
        items = load_feedback(); items.append(item); save_feedback(items)
    return {"ok": True, "item": clean_feedback_item(item)}

@app.post("/api/feedback/{feedback_id}/reply")
async def feedback_reply(feedback_id: str, request: Request):
    try: data = await request.json()
    except Exception: data = {}
    name = str(data.get("name") or "Гость").strip()[:40] or "Гость"
    message = str(data.get("message") or "").strip()[:1200]
    if len(message) < 2: raise service_error("MF-422", "Ответ слишком короткий.", 400)
    with feedback_lock:
        items = load_feedback(); item = next((x for x in items if x.get("id") == feedback_id), None)
        if not item: raise service_error("MF-404", "Сообщение не найдено.", 404)
        item.setdefault("replies", []).append({"id": uuid.uuid4().hex[:12], "name": name, "message": message, "created_at": int(time.time()*1000)})
        item["replies"] = item["replies"][-40:]
        save_feedback(items)
        return {"ok": True, "item": clean_feedback_item(item)}

@app.post("/api/feedback/{feedback_id}/report")
async def feedback_report(feedback_id: str, request: Request):
    try: data = await request.json()
    except Exception: data = {}
    with feedback_lock:
        items = load_feedback(); item = next((x for x in items if x.get("id") == feedback_id), None)
        if not item: raise service_error("MF-404", "Сообщение не найдено.", 404)
        item["reports"] = int(item.get("reports") or 0) + 1
        save_feedback(items)
        return {"ok": True, "reports": item["reports"]}

@app.get("/robots.txt")
async def robots(): return PlainTextResponse("User-agent: *\nAllow: /\n",media_type="text/plain")

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    detail=exc.detail
    if isinstance(detail,dict) and "code" in detail: return JSONResponse(status_code=exc.status_code,content={"ok":False,"code":detail["code"],"message":detail.get("message","")})
    return JSONResponse(status_code=exc.status_code,content={"ok":False,"code":f"MF-{exc.status_code}","message":str(detail)})
