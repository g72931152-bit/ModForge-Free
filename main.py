from __future__ import annotations

import asyncio
import hashlib
import stat
from contextlib import asynccontextmanager
import difflib
import json
import os
import re
import shutil
import smtplib
import threading
import time
import uuid
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import quote
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

APP_NAME = "ModForge"
APP_VERSION = "v1"
SITE_VERSION = "0.42"
RELEASE_ID = f"v1 ({SITE_VERSION})"
BEAMNG_VERSION = "0.39"
BEAMNG_PROFILE_NOTE = "Целевой профиль ModForge v1 для BeamNG.drive 0.39. Версия 0.42 относится к самому сайту/релизной ветке ModForge; живая игра в backend не запускается."
MAX_UPLOAD = 2 * 1024 * 1024 * 1024
MAX_UNPACKED = 4 * 1024 * 1024 * 1024
MAX_FILES = 12000
MAX_SINGLE_FILE_UNPACKED = 512 * 1024 * 1024
MAX_PATH_DEPTH = 32
MAX_ARCHIVE_RATIO = 200.0
MAX_ACTIVE_JOBS_PER_CLIENT = 2
MAX_ACTIVE_JOBS_GLOBAL = 8
JOB_TIMEOUT_SECONDS = int(os.environ.get("MODFORGE_JOB_TIMEOUT", str(30 * 60)))
MAX_COMPARE_UPLOAD = 1024 * 1024 * 1024
MAX_DIFF_CHARS = 12000
MAX_DIFF_FILES = 80
MAX_INSPECTOR_FILES = 20000
MAX_TEXTURE_WARN_BYTES = 8 * 1024 * 1024
MAX_GEOMETRY_WARN_BYTES = 50 * 1024 * 1024
LARGE_JOB_THRESHOLD = 1 * 1024 * 1024 * 1024
LARGE_JOB_COOLDOWN = 15 * 60
JOB_RETENTION = int(os.environ.get("MODFORGE_JOB_RETENTION", str(7 * 24 * 60 * 60)))
BASE_DIR = Path(__file__).resolve().parent
# Never use /tmp as the default job store: it can disappear on restart/redeploy.
DATA_ROOT = Path(os.environ.get("MODFORGE_DATA_ROOT", str(BASE_DIR / "data"))).resolve()
WORK_ROOT = Path(os.environ.get("MODFORGE_WORK_ROOT", str(DATA_ROOT / "jobs"))).resolve()
FEEDBACK_PATH = Path(os.environ.get("MODFORGE_FEEDBACK_PATH", str(DATA_ROOT / "feedback.json"))).resolve()
ASSET_ROOT = BASE_DIR / "assets"
CONFIG_PATH = BASE_DIR / "site_config.json"
WORK_ROOT.mkdir(parents=True, exist_ok=True)
ASSET_ROOT.mkdir(parents=True, exist_ok=True)

jobs: dict[str, dict] = {}
large_cooldowns: dict[str, float] = {}
feedback_lock = threading.Lock()
email_state = {"configured": False, "last_ok": None, "last_error": None, "last_sent_at": None}
async def restore_cleanup_tasks():
    # Terminal jobs keep their artifacts for JOB_RETENTION. Interrupted jobs are rebuilt
    # from the persisted source copy after a backend restart, so a browser closing or a
    # process restart does not force the user to upload the mod again.
    for job_id, job in list(jobs.items()):
        root = Path(job.get("root", ""))
        if not root.exists():
            continue
        if job.get("status") in {"done", "error", "cancelled"}:
            asyncio.create_task(cleanup_job_later(job_id, root))
        elif job.get("status") in {"queued", "running", "processing", "paused", "rebuilding"}:
            source = root / "source"
            if not source.exists():
                continue
            shutil.rmtree(root / "payload", ignore_errors=True)
            job["status"] = "queued"
            job["stage_index"] = 0
            job["progress"] = 0
            job["stage_progress"] = 0
            job["eta_seconds"] = None
            job["stage_label"] = "Восстановление после перезапуска"
            job["stage_detail"] = "Продолжаем задачу из сохранённой исходной копии."
            job["_cancel_event"] = threading.Event()
            job["_pause_event"] = threading.Event()
            job["_timeout_event"] = threading.Event()
            persist_job(job_id)
            asyncio.create_task(run_job(job_id, root, job.get("original_name") or job.get("source_name") or "beamng_mod", job.get("source_kind") or "zip", job.get("source_name") or "beamng_mod", str(job.get("wishes") or ""), job.get("priority") if isinstance(job.get("priority"), list) else [], int(job.get("uploaded_bytes") or 0), str(job.get("output_suffix") or "FIXED"), str(job.get("output_type") or "zip"), str(job.get("repair_mode") or "standard"), str(job.get("task_mode") or "repair"), str(job.get("modification_request") or ""), str(job.get("network_profile") or "standard")))


@asynccontextmanager
async def lifespan(_app):
    await restore_cleanup_tasks()
    for job_id, job in list(jobs.items()):
        if job.get("status") in {"queued", "running", "processing", "paused", "rebuilding"}:
            asyncio.create_task(job_timeout_watchdog(job_id, JOB_TIMEOUT_SECONDS))
    yield


app = FastAPI(title=APP_NAME, docs_url=None, redoc_url=None, lifespan=lifespan)
app.mount("/assets", StaticFiles(directory=ASSET_ROOT), name="assets")

SUPPORTED_SINGLE = {
    ".jbeam", ".pc", ".json", ".jsonc", ".lua", ".materials", ".cs", ".cfg", ".prefab",
    ".dae", ".cdae", ".dds", ".png", ".jpg", ".jpeg", ".tga", ".bmp", ".gif", ".ogg", ".wav", ".mp3", ".flac",
    ".mis", ".forest", ".ter", ".level.json", ".materials.json",
}
TEXT_EXTS = {".json", ".jsonc", ".jbeam", ".pc", ".lua", ".cs", ".cfg", ".materials", ".prefab", ".mis", ".forest"}
RESOURCE_EXTS = r"dds|png|jpe?g|tga|bmp|gif|dae|cdae|jbeam|json|pc|cdb|lua|materials|prefab|mis|forest|ter|ogg|wav|mp3|flac"
RESOURCE_RE = re.compile(rf"(?P<path>[A-Za-z0-9_@%+~.\-]+(?:[\\/][A-Za-z0-9_@%+~.\-]+)*\.(?:{RESOURCE_EXTS}))", re.I)
MAX_RESOURCE_REFS_PER_FILE = 220

REPAIR_MODES = {
    "standard": {"label": "Стандартный", "description": "Рекомендуется. Только подтверждённые низкорисковые исправления.", "aggressiveness": 1},
    "medium": {"label": "Средний", "description": "Более глубокая проверка ссылок и типовых JBeam-проблем; спорные места остаются предупреждениями.", "aggressiveness": 2},
    "aggressive": {"label": "Агрессивный", "description": "Максимальный эвристический ремонт распознаваемых структур; сомнительные места всё равно помечаются отдельно.", "aggressiveness": 3},
}

OWNER_EMAIL = "ptornsaso0h@gmail.com"
SMTP_HOST = os.environ.get("MODFORGE_SMTP_HOST", "").strip()
SMTP_PORT = int(os.environ.get("MODFORGE_SMTP_PORT", "587"))
SMTP_USER = os.environ.get("MODFORGE_SMTP_USER", "").strip()
SMTP_PASSWORD = os.environ.get("MODFORGE_SMTP_PASSWORD", "")
SMTP_FROM = os.environ.get("MODFORGE_SMTP_FROM", SMTP_USER or OWNER_EMAIL).strip()
SMTP_TLS = os.environ.get("MODFORGE_SMTP_TLS", "1").lower() not in {"0", "false", "no"}
SMTP_SSL = os.environ.get("MODFORGE_SMTP_SSL", "0").lower() not in {"0", "false", "no"}
SMTP_TIMEOUT = int(os.environ.get("MODFORGE_SMTP_TIMEOUT", "20"))
ADMIN_KEY = os.environ.get("MODFORGE_ADMIN_KEY", "").strip()

DEFAULT_CONFIG = {
    "brand_name": APP_NAME,
    "tagline": "Проверка и безопасное исправление модов BeamNG.drive",
    "support_url": "",
    "support_label": "Поддержать проект",
    "ad_enabled": False,
    "ad_html": "",
    "default_suffix": "FIXED",
    "release_version": APP_VERSION,
    "repair_modes": REPAIR_MODES,
    "owner_email": OWNER_EMAIL,
    "email_notifications": bool(SMTP_HOST and SMTP_USER and SMTP_PASSWORD),
    "beamng_version": BEAMNG_VERSION,
    "site_version": SITE_VERSION,
    "release_id": RELEASE_ID,
    "network_profiles": {"standard": 2, "balanced": 5, "aggressive": 20},
    "network_parallelism": {"standard": 2, "balanced": 4, "aggressive": 8},
    "privacy_version": "2026-09-26",
}

STAGES = [
    ("intake", "Приём", "Проверяем формат, размер и безопасность входа.", 5),
    ("request", "Ваш запрос", "Разбираем то, что пользователь попросил проверить или изменить.", 8),
    ("focused", "Прицельная проверка", "Сначала проверяем выбранные пользователем области.", 13),
    ("structure", "Структура", "Ищем дубли, странные пути и нарушения структуры.", 7),
    ("syntax", "Конфигурации", "Проверяем JSON, PC, JBeam и текстовые конфигурации.", 10),
    ("resources", "Ресурсы", "Сопоставляем внутренние ссылки с файлами.", 11),
    ("materials", "Материалы", "Проверяем текстуры, стекло, NO TEXTURE и материалы света.", 10),
    ("vehicle", "Автомобиль", "Проверяем колёса, slotType, JBeam-связи и базовые физические аномалии.", 10),
    ("common", "Типовые проблемы", "После прицельной проверки ищем распространённые ошибки сторонних модов.", 8),
    ("deep", "Глубокая проверка", "Проверяем связанные данные и подозрительные места.", 6),
    ("repair", "Исправление", "Применяем подтверждённые исправления или пользовательские изменения.", 7),
    ("verify", "Проверка изменений", "Проверяем изменённые файлы сразу после ремонта.", 6),
    ("recheck", "Повторная проверка", "Запускаем полный контроль результата после изменений.", 7),
    ("package", "Сборка", "Создаём результат с сохранением структуры мода.", 2),
    ("final", "Финал", "Открываем и проверяем итоговый файл перед выдачей.", 1),
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
    if not job.get("root"): return
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
            if status not in {"queued", "running", "processing", "paused", "done", "error", "cancelled", "rebuilding"}: continue
            root = Path(meta.get("root") or meta_path.parent)
            if not root.exists(): continue
            meta["root"] = str(root)
            if status == "rebuilding":
                meta["status"] = "done"
                meta["eta_seconds"] = 0
            meta["_cancel_event"] = threading.Event()
            meta["_pause_event"] = threading.Event()
            meta["_timeout_event"] = threading.Event()
            meta["job_id"] = job_id
            jobs[job_id] = meta
            # Watchdog is started by the lifespan after all jobs are loaded.
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
    tmp.write_text(json.dumps(items[-5000:], ensure_ascii=False, indent=2), "utf-8")
    tmp.replace(FEEDBACK_PATH)


def clean_feedback_item(item: dict) -> dict:
    cleaned = {k: item.get(k) for k in ("id", "name", "message", "created_at", "status", "replies", "reports")}
    # Email addresses are private; never expose them through the public API.
    cleaned["replies"] = [
        {k: r.get(k) for k in ("id", "name", "message", "created_at", "author")}
        for r in (item.get("replies") or [])
    ]
    return cleaned


def _smtp_send(msg: EmailMessage) -> None:
    if not (SMTP_HOST and SMTP_USER and SMTP_PASSWORD):
        raise RuntimeError("SMTP не настроен: задайте MODFORGE_SMTP_HOST, MODFORGE_SMTP_USER и MODFORGE_SMTP_PASSWORD.")
    email_state["configured"] = True
    if SMTP_SSL:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT) as smtp:
            smtp.login(SMTP_USER, SMTP_PASSWORD)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT) as smtp:
            smtp.ehlo()
            if SMTP_TLS:
                smtp.starttls()
                smtp.ehlo()
            smtp.login(SMTP_USER, SMTP_PASSWORD)
            smtp.send_message(msg)


def send_owner_email(subject: str, body: str, reply_to: str = "") -> None:
    """Send an owner notification. The user's email becomes Reply-To so the owner can answer directly from mail."""
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = SMTP_FROM or OWNER_EMAIL
    msg["To"] = OWNER_EMAIL
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(body)
    _smtp_send(msg)


def send_user_email(to_email: str, subject: str, body: str) -> None:
    if not to_email:
        return
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = SMTP_FROM or OWNER_EMAIL
    msg["To"] = to_email
    msg["Reply-To"] = SMTP_FROM or OWNER_EMAIL
    msg.set_content(body)
    _smtp_send(msg)


def schedule_email(fn, *args) -> None:
    if not (SMTP_HOST and SMTP_USER and SMTP_PASSWORD):
        email_state["configured"] = False
        email_state["last_error"] = "SMTP не настроен."
        return
    email_state["configured"] = True
    threading.Thread(target=lambda: _safe_email(fn, *args), daemon=True).start()


def _safe_email(fn, *args) -> None:
    try:
        fn(*args)
        email_state["last_ok"] = True
        email_state["last_error"] = None
        email_state["last_sent_at"] = int(time.time() * 1000)
    except Exception as exc:
        email_state["last_ok"] = False
        email_state["last_error"] = str(exc)[:500]
        print(f"[ModForge email] {exc}", flush=True)


def is_admin(request: Request) -> bool:
    supplied = request.headers.get("x-modforge-admin-key", "")
    return bool(ADMIN_KEY and supplied and supplied == ADMIN_KEY)



def request_client_id(request: Request) -> str:
    direct = request.client.host if request.client else "unknown"
    if os.environ.get("MODFORGE_TRUST_PROXY", "0").lower() in {"1", "true", "yes"}:
        forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        return forwarded or direct
    return direct

def service_error(code: str, message: str, status: int) -> HTTPException:
    return HTTPException(status, detail={"code": code, "message": message})


def public_job(job: dict) -> dict:
    return {k: v for k, v in job.items() if not k.startswith("_") and k not in {"output", "root", "report_path"}}


def safe_rel(raw: str) -> str:
    raw = (raw or "").replace("\\", "/").lstrip("/")
    if "\x00" in raw or re.match(r"^[A-Za-z]:", raw):
        raise ValueError("Обнаружен небезопасный путь файла.")
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


def _is_glass_material(mat: dict) -> bool:
    identity = material_identity(mat)
    return any(token in identity for token in ("glass", "window", "windshield", "windscreen"))


def _material_maps(mat: dict) -> list[tuple[str, str]]:
    fields = ("baseColorMap", "opacityMap", "normalMap", "roughnessMap", "metallicMap", "aoMap", "ambientOcclusionMap", "emissiveMap")
    out = []
    for field in fields:
        value = mat.get(field)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str): out.append((field, item))
        elif isinstance(value, str):
            out.append((field, value))
    stages = mat.get("Stages")
    if isinstance(stages, list):
        for stage in stages:
            if not isinstance(stage, dict): continue
            for field in fields:
                value = stage.get(field)
                if isinstance(value, list):
                    for item in value:
                        if isinstance(item, str): out.append((field, item))
                elif isinstance(value, str):
                    out.append((field, value))
    return out


def _resource_exists(root: Path, ref: str, resource_index: set[str] | None = None) -> bool:
    normalized = ref.replace("\\", "/").lstrip("/")
    if resource_index is None:
        if (root / normalized).is_file(): return True
        wanted = normalized.casefold()
        return any(p.as_posix().casefold() == wanted for p in root.rglob("*"))
    return normalized.casefold() in resource_index


def repair_glass(path: Path, root: Path | None = None, resource_index: set[str] | None = None) -> list[dict]:
    try: data = json.loads(read_text(path))
    except Exception: return []
    if not isinstance(data, dict): return []
    changes = []
    for key, mat in material_objects(data):
        if not _is_glass_material(mat): continue
        updates = {}
        if mat.get("translucent") is not True:
            mat["translucent"] = True; updates["translucent"] = True
        if mat.get("translucentBlendOp") != "PreMulAlpha":
            mat["translucentBlendOp"] = "PreMulAlpha"; updates["translucentBlendOp"] = "PreMulAlpha"
        if mat.get("castShadows") is not False:
            mat["castShadows"] = False; updates["castShadows"] = False
        if mat.get("translucentRecvShadows") is not True:
            mat["translucentRecvShadows"] = True; updates["translucentRecvShadows"] = True
        if mat.get("version") is None:
            mat["version"] = 1.5; updates["version"] = 1.5

        stages = mat.get("Stages")
        if not isinstance(stages, list) or not stages:
            stages = [{}, {}, {}, {}]
            mat["Stages"] = stages
            updates["Stages"] = "создана современная структура материала"
        stage = stages[0] if isinstance(stages[0], dict) else {}
        stages[0] = stage

        broken = []
        if root is not None:
            for field, ref in _material_maps(mat):
                if ref and not _resource_exists(root, ref, resource_index):
                    broken.append((field, ref))
        if broken:
            broken_fields = {field.split(".")[-1] for field, _ in broken}
            stage_list = [st for st in stages if isinstance(st, dict)]
            for st in stage_list:
                for field in ("baseColorMap", "opacityMap", "normalMap", "roughnessMap", "metallicMap", "aoMap", "ambientOcclusionMap", "emissiveMap"):
                    if field in broken_fields:
                        st.pop(field, None)
            if "baseColorMap" in broken_fields:
                stage["baseColorFactor"] = [0.20, 0.28, 0.34, 1.0]
            if "opacityMap" in broken_fields or "baseColorMap" in broken_fields:
                stage["opacityFactor"] = 0.34
            stage.setdefault("roughnessFactor", 0.08)
            updates["missing_glass_texture"] = f"fallback без внешней текстуры; {len(broken)} отсутствующих ссылок"
        if updates:
            changes.append({"material": key, "updates": updates})
    if changes:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", "utf-8")
    return changes


def should_check_text(path: Path) -> bool:
    return path.suffix.lower() in TEXT_EXTS or path.name.lower().endswith(".materials.json") or path.name.lower().endswith(".level.json")


def check_cancel_pause(job: dict) -> None:
    if job.get("_timeout_event") and job["_timeout_event"].is_set():
        raise RuntimeError("__TIMEOUT__")
    if job["_cancel_event"].is_set():
        raise RuntimeError("__CANCELLED__")
    while job["_pause_event"].is_set():
        job["status"] = "paused"
        if job["_cancel_event"].is_set():
            raise RuntimeError("__CANCELLED__")
        time.sleep(0.20)
    if job.get("status") == "paused": job["status"] = "running"


def stage_start(job: dict, stage_index: int, label: str | None = None, detail: str | None = None) -> None:
    job["_stage_index"] = stage_index
    job["status"] = "running"
    job["stage_index"] = stage_index + 1
    job["stage_label"] = label or STAGES[stage_index][1]
    job["stage_detail"] = detail or STAGES[stage_index][2]
    job["stage_progress"] = 0
    check_cancel_pause(job)
    persist_job(job.get("job_id", ""))


def detect_focus(priority: list[str], wishes: str) -> list[str]:
    mapping = {
        "textures": "Текстуры", "glass": "Стекло", "jbeam": "JBeam",
        "lighting": "Освещение", "configs": "Конфигурации", "wheels": "Колёса",
        "sounds": "Звуки", "materials": "Материалы", "all": "Полная проверка"
    }
    out=[]
    for x in priority:
        if x in mapping and mapping[x] not in out and x != "all": out.append(mapping[x])
    wl=(wishes or "").lower()
    for tokens,label in [
        (("текстур","texture","no texture"),"Текстуры"),
        (("стекл","glass","window","windshield","windscreen"),"Стекло"),
        (("jbeam","джбим","физик"),"JBeam"),
        (("свет","освещ","light","glowmap","фонар"),"Освещение"),
        (("конфиг","configuration","config","pc"),"Конфигурации"),
        (("колес","wheel","шина","tire"),"Колёса"),
        (("звук","sound","audio"),"Звуки"),
        (("материал","material"),"Материалы"),
    ]:
        if any(t in wl for t in tokens) and label not in out: out.append(label)
    return out or (["Полная проверка"] if "all" in priority else [])


def scan_request(root: Path, job: dict, priority: list[str], wishes: str, task_mode: str) -> list[dict]:
    focus = detect_focus(priority, wishes)
    job["focus"] = focus
    issues=[]
    if task_mode == "modify":
        issues.append({"level":"info","stage":"request","title":"Режим изменения выбран","details": wishes.strip() or "Пользователь не описал изменение."})
    if focus:
        issues.append({"level":"ok","stage":"request","title":"Приоритет принят","details": ", ".join(focus)})
    else:
        issues.append({"level":"info","stage":"request","title":"Особых приоритетов нет","details":"После этапа запроса будет выполнена полная проверка типовых проблем."})
    return issues


def scan_focused(root: Path, job: dict, priority: list[str], wishes: str) -> list[dict]:
    focus = detect_focus(priority, wishes)
    if not focus or "Полная проверка" in focus: return [{"level":"info","stage":"focused","title":"Прицельная проверка пропущена","details":"Выбрана полная последовательная проверка; сначала она проходит общий анализ."}]
    issues=[]
    texts=[p for p in root.rglob("*") if p.is_file() and should_check_text(p)]
    resource_index={p.relative_to(root).as_posix().casefold() for p in root.rglob("*") if p.is_file()}
    need_res=any(x in focus for x in ("Текстуры","Освещение","Звуки","Материалы"))
    need_j=any(x in focus for x in ("JBeam","Колёса"))
    need_glass="Стекло" in focus
    need_cfg="Конфигурации" in focus
    for p in texts:
        check_cancel_pause(job); rel=p.relative_to(root).as_posix(); txt=read_text(p)
        if need_res:
            for m in list(RESOURCE_RE.finditer(txt))[:MAX_RESOURCE_REFS_PER_FILE]:
                ref=m.group("path").replace("\\","/")
                ext=Path(ref).suffix.lower()
                wanted=("Текстуры" in focus and ext in {".dds",".png",".jpg",".jpeg",".tga",".bmp"}) or ("Звуки" in focus and ext in {".ogg",".wav",".mp3"}) or ("Освещение" in focus and ("light" in m.group("path").lower() or ext in {".dds",".png",".jpg",".jpeg"}))
                if wanted and resolve_ref(ref, resource_index, case_index(resource_index)) is None:
                    issues.append({"level":"warning","stage":"focused","title":"Приоритетный ресурс не найден","details":f"{rel} → {ref}"})
        if need_j and p.suffix.lower()==".jbeam":
            ok,msg=bracket_balance(txt)
            if not ok: issues.append({"level":"warning","stage":"focused","title":"JBeam требует внимания","details":f"{rel}: {msg}"})
            if "Колёса" in focus and '"pressureWheels"' in txt and '"node1"' not in txt:
                issues.append({"level":"warning","stage":"focused","title":"Pressure wheel секция выглядит неполной","details":rel})
        if need_cfg and p.suffix.lower() in {".pc", ".json"}:
            try: json.loads(txt)
            except Exception as exc: issues.append({"level":"warning","stage":"focused","title":"Приоритетная конфигурация не разбирается как JSON","details":f"{rel}: {exc}"})
    if need_glass:
        issues.extend(scan_materials(root, job))
    if not issues: issues.append({"level":"ok","stage":"focused","title":"Прицельных ошибок не найдено","details":"Выбранные пользователем области прошли первую проверку."})
    return issues
def make_progress(job: dict, stage_index: int, stage_done: float) -> int:
    stage_index = int(job.get("_stage_index", stage_index))
    stage_index = max(0, min(stage_index, len(STAGES)-1))
    completed = sum(STAGES[i][3] for i in range(stage_index))
    weight = STAGES[stage_index][3]
    progress = int(round(((completed + weight * max(0.0, min(1.0, stage_done))) / TOTAL_WEIGHT) * 100))
    job["stage_progress"] = int(round(max(0.0, min(1.0, stage_done))*100))
    job["progress"] = progress
    started = float(job.get("started_at") or time.time())
    elapsed = max(0.1, time.time() - started)
    ratio = max(0.01, (completed + weight * max(0.0, min(1.0, stage_done))) / TOTAL_WEIGHT)
    if ratio >= 0.03 and elapsed >= 2.0:
        remaining = elapsed * (1.0-ratio) / ratio
        previous=job.get("eta_seconds")
        if isinstance(previous,(int,float)) and previous>0: remaining=0.65*float(previous)+0.35*remaining
        job["eta_seconds"] = int(max(0, round(remaining)))
    return progress

def scan_materials(root: Path, job: dict) -> list[dict]:
    files=[p for p in root.rglob("*") if p.is_file() and (p.suffix.lower()==".json" or p.name.lower().endswith(".materials.json"))]
    issues=[]; total=max(1,len(files))
    resource_index={p.relative_to(root).as_posix().casefold() for p in root.rglob("*") if p.is_file()}
    for idx,path in enumerate(files,1):
        check_cancel_pause(job); rel=path.relative_to(root).as_posix(); text=read_text(path)
        if "NO TEXTURE" in text.upper(): issues.append({"level":"warning","stage":"materials","title":"Найдена явная отметка NO TEXTURE","details":rel})
        try: data=json.loads(text)
        except Exception: data=None
        if isinstance(data,dict):
            glass=[key for key,mat in material_objects(data) if _is_glass_material(mat)]
            if glass: issues.append({"level":"ok","stage":"materials","title":"Материалы стекла найдены","details":f"{rel}: {', '.join(glass[:10])}"})
            for key, mat in material_objects(data):
                if not _is_glass_material(mat): continue
                for field, ref in _material_maps(mat):
                    if ref and not _resource_exists(root, ref, resource_index):
                        issues.append({"level":"warning","stage":"materials","title":"У стекла отсутствует текстурный ресурс","details":f"{rel}: {key}.{field} → {ref}"})
        make_progress(job,4,idx/total)
    return issues


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
            if '"slotType"' not in text and re.search(r'"information"\s*:', text, re.I):
                issues.append({"level":"warning","stage":"syntax","title":"В JBeam отсутствует slotType","details":rel})
        make_progress(job, 2, idx / total)
    return issues


def parallel_map_files(paths: list[Path], fn, job: dict) -> list:
    from concurrent.futures import ThreadPoolExecutor
    if not paths:
        return []
    workers = max(1, min(int(job.get("scan_workers", 2) or 2), len(paths)))
    if workers == 1:
        return [fn(p) for p in paths]
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="modforge-scan") as pool:
        return list(pool.map(fn, paths))

def scan_resources(root: Path, job: dict) -> list[dict]:
    files, file_set, ci = cached_indexes(root, job)
    text_files = [p for p in files if should_check_text(p)]
    total=max(1,len(text_files)); issues=[]
    def one(path: Path):
        text=read_text(path); rel=path.relative_to(root).as_posix(); out=[]
        for match in list(RESOURCE_RE.finditer(text))[:MAX_RESOURCE_REFS_PER_FILE]:
            ref=match.group("path").replace("\\","/")
            if resolve_ref(ref,file_set,ci) is None:
                candidates=candidates_for(ref,file_set); detail=f"{rel} → {ref}"
                if candidates: detail += "; похожие: " + ", ".join(candidates)
                out.append({"level":"warning","stage":"resources","title":"Внутренняя ссылка не подтверждена","details":detail})
        return out
    for idx, out in enumerate(parallel_map_files(text_files, one, job), 1):
        check_cancel_pause(job); issues.extend(out); make_progress(job,3,idx/total)
    return issues


def scan_lighting(root: Path, job: dict) -> list[dict]:
    files=[p for p in root.rglob("*") if p.is_file()]; texts=[p for p in files if should_check_text(p)]
    file_set={p.relative_to(root).as_posix() for p in files}; ci=case_index(file_set)
    issues=[]; found=0
    for p in texts:
        check_cancel_pause(job); t=read_text(p); rel=p.relative_to(root).as_posix(); low=t.lower()
        if any(token in low for token in ('glowmap','light','emissive','flare')):
            found+=1
            for m in RESOURCE_RE.finditer(t):
                ref=m.group('path').replace('\\','/')
                if Path(ref).suffix.lower() in {'.dds','.png','.jpg','.jpeg','.tga'} and resolve_ref(ref,file_set,ci) is None:
                    if any(k in ref.lower() for k in ('light','glow','lamp','emiss')):
                        issues.append({'level':'warning','stage':'materials','title':'В освещении не найден ресурс','details':f'{rel} → {ref}'})
    if found and not issues: issues.append({'level':'ok','stage':'materials','title':'Освещение найдено и ссылочно согласовано','details':f'Файлов с light/glowmap/emissive: {found}'})
    return issues


def scan_common_issues(root: Path, job: dict) -> list[dict]:
    issues=[]
    files, file_set, ci = cached_indexes(root, job)
    jbeams=[p for p in files if p.suffix.lower()=='.jbeam']
    pcs=[p for p in files if p.suffix.lower()=='.pc']
    info_json=[p for p in files if p.name.lower()=='info.json']
    sounds={p.name.casefold() for p in files if p.suffix.lower() in {'.ogg','.wav','.mp3','.flac'}}
    for p in files:
        check_cancel_pause(job); rel=p.relative_to(root).as_posix(); name=p.name.lower()
        if name in {'thumbs.db','.ds_store'} or '__macosx' in rel.lower():
            issues.append({'level':'info','stage':'common','title':'Служебный файл в архиве','details':rel})
        if p.suffix.lower() in {'.dds','.cdae','.dae','.png','.jpg','.jpeg'} and p.stat().st_size==0:
            issues.append({'level':'warning','stage':'common','title':'Пустой графический ресурс','details':rel})
    texts=[p for p in files if should_check_text(p)]
    missing_sound_refs=0
    unresolved=0
    for p in texts:
        t=read_text(p); rel=p.relative_to(root).as_posix(); low=t.lower()
        if 'no texture' in low:
            issues.append({'level':'warning','stage':'common','title':'Обнаружена строка NO TEXTURE','details':rel})
        if p.suffix.lower()=='.pc' and '"model"' not in t:
            issues.append({'level':'warning','stage':'common','title':'PC-конфигурация без model','details':rel})
        if p.suffix.lower()=='.jbeam':
            if re.search(r'"slotType"\s*:',t,re.I) is None and re.search(r'"information"\s*:',t,re.I):
                issues.append({'level':'warning','stage':'common','title':'JBeam без slotType в блоке, похожем на деталь','details':rel})
            if re.search(r'"slots"\s*:\s*\[?\s*\]',t,re.I):
                issues.append({'level':'warning','stage':'common','title':'Пустой slots-список','details':rel})
            if re.search(r'"id"\s*:\s*""',t,re.I):
                issues.append({'level':'warning','stage':'common','title':'Пустой идентификатор детали','details':rel})
        for m in RESOURCE_RE.finditer(t):
            ref=m.group('path').replace('\\','/')
            if Path(ref).suffix.lower() in {'.ogg','.wav','.mp3','.flac'} and resolve_ref(ref,file_set,ci) is None:
                missing_sound_refs += 1
            if resolve_ref(ref,file_set,ci) is None:
                unresolved += 1
    if missing_sound_refs:
        issues.append({'level':'warning','stage':'common','title':'Ссылки на отсутствующие звуки','details':f'Не подтверждено ссылок: {missing_sound_refs}'})
    if jbeams and not info_json:
        issues.append({'level':'info','stage':'common','title':'У автомобиля нет info.json','details':'Это не всегда ошибка, но без него карточка машины в редакторе может быть неполной.'})
    if len(pcs)>12:
        issues.append({'level':'info','stage':'common','title':'Большой набор PC-конфигураций','details':f'Найдено конфигураций: {len(pcs)}; проверка каждой может заметно увеличить время.'})
    # Unresolved references are counted during the same text pass to avoid rereading every file.
    if unresolved:
        issues.append({'level':'warning','stage':'common','title':'Повторно подтверждены отсутствующие ресурсы','details':f'Ссылок без локального файла: {unresolved}. Для исправления ModForge ищет однозначный локальный кандидат.'})
    if not issues: issues.append({'level':'ok','stage':'common','title':'В типовом наборе ошибок ничего критичного не найдено','details':'Пост-скан распространённых проблем сторонних модов завершён.'})
    return issues


def scan_deep(root: Path, job: dict) -> list[dict]:
    files=cached_files(root, job); issues=[]; total=max(1,len(files))
    for idx,path in enumerate(files,1):
        check_cancel_pause(job)
        rel=path.relative_to(root).as_posix(); size=path.stat().st_size
        if path.suffix.lower() in {".dds",".cdae",".dae"} and size == 0:
            issues.append({"level":"warning","stage":"deep","title":"Пустой ресурс","details":rel})
        if path.name.startswith(".") or "__MACOSX" in rel:
            issues.append({"level":"info","stage":"deep","title":"Служебный файл","details":rel})
        make_progress(job,5,idx/total)
    return issues



def fuzzy_resource_candidate(ref: str, files: set[str]) -> str | None:
    base=Path(ref.replace('\\','/')).name.casefold(); stem=Path(base).stem; ext=Path(base).suffix
    scored=[]
    for p in files:
        pp=Path(p)
        if pp.suffix.casefold()!=ext.casefold(): continue
        name=pp.name.casefold(); score=(100 if name==base else 0)+(50 if pp.stem.casefold()==stem else 0)
        a=re.sub(r'[^a-z0-9]','',stem); b=re.sub(r'[^a-z0-9]','',pp.stem.casefold())
        if a and b: score+=min(30,len(os.path.commonprefix([a,b]))*2)
        if name.startswith(stem) or stem.startswith(pp.stem.casefold()): score+=15
        if score>=55: scored.append((score,p))
    scored.sort(reverse=True)
    if not scored or (len(scored)>1 and scored[0][0]-scored[1][0]<10): return None
    return scored[0][1]

def repair_json_syntax(path: Path) -> tuple[bool,str]:
    raw=read_text(path)
    if not raw: return False,''
    cleaned=re.sub(r',\s*([}\]])',r'\1',raw)
    if cleaned==raw: return False,''
    try: json.loads(cleaned)
    except Exception: return False,''
    path.write_text(cleaned,'utf-8'); return True,'Удалены недопустимые завершающие запятые.'

def _jbeam_string_tokens(text: str) -> set[str]:
    return {m.group(1) for m in re.finditer(r'"([^"\n\r]+)"', text)}

def _wheel_refs(text: str) -> list[tuple[str,str,str]]:
    blocks=[]
    for m in re.finditer(r'(?P<name>"[^"\n]+")\s*:\s*\{(?P<body>[^{}]{0,2400})\}', text, re.S):
        body=m.group('body')
        if 'node1' in body.lower() or 'node2' in body.lower():
            n1m=re.search(r'"node1"\s*:\s*"([^"\n]+)"', body, re.I)
            n2m=re.search(r'"node2"\s*:\s*"([^"\n]+)"', body, re.I)
            if n1m or n2m:
                blocks.append((m.group('name').strip('"'), n1m.group(1) if n1m else '', n2m.group(1) if n2m else ''))
    return blocks

def scan_vehicle_health(root: Path, job: dict) -> list[dict]:
    files=cached_files(root, job); jbeams=[p for p in files if p.suffix.lower()==".jbeam"]
    if not jbeams: return []
    issues=[]; resource_index={p.relative_to(root).as_posix().casefold() for p in files}
    for p in jbeams:
        check_cancel_pause(job); text=read_text(p); rel=p.relative_to(root).as_posix()
        if '"pressureWheels"' in text:
            refs=_wheel_refs(text); tokens=_jbeam_string_tokens(text)
            for wheel,n1,n2 in refs:
                for side,ref in (("node1",n1),("node2",n2)):
                    if ref and ref not in tokens: issues.append({'level':'warning','stage':'vehicle','title':'Связь колеса с узлом не подтверждена','details':f'{rel}: {wheel}.{side} → {ref}'})
            if re.search(r'"(?:wheelDir|wheelAxis)"\s*:\s*\[\s*0\s*,\s*0\s*,\s*0\s*\]',text,re.I):
                issues.append({'level':'warning','stage':'vehicle','title':'Нулевой вектор направления колеса','details':rel})
        if re.search(r'"slotType"\s*:', text, re.I) is None and re.search(r'"parts"\s*:', text, re.I):
            issues.append({'level':'warning','stage':'vehicle','title':'В конфигурационном JBeam-файле не найден slotType','details':rel})
    if not issues: issues.append({'level':'ok','stage':'vehicle','title':'Связи автомобиля выглядят согласованными','details':f'Проверено JBeam-файлов: {len(jbeams)}'})
    return issues

def repair_vehicle_refs(path: Path, mode: str) -> list[dict]:
    if mode not in {'medium','aggressive'} or path.suffix.lower()!='.jbeam': return []
    text=read_text(path); tokens=_jbeam_string_tokens(text); changes=[]
    for wheel,n1,n2 in _wheel_refs(text):
        for side,ref in (("node1",n1),("node2",n2)):
            if not ref or ref in tokens: continue
            candidates=difflib.get_close_matches(ref, list(tokens), n=2, cutoff=0.72 if mode=='medium' else 0.60)
            candidates=[c for c in candidates if len(c)>1]
            if len(candidates)==1 and candidates[0]!=ref:
                pattern=rf'("{re.escape(side)}"\s*:\s*")'+re.escape(ref)+r'(")'
                updated,n=re.subn(pattern,rf'\g<1>{candidates[0]}\g<2>',text,count=1)
                if n: text=updated; changes.append((wheel,side,ref,candidates[0]))
    if changes:
        path.write_text(text,'utf-8')
        return [{'level':'fixed','stage':'repair','title':'Восстановлены очевидные связи узлов колёс','details':f'{path.name}: {w}.{s} {a} → {b}'} for w,s,a,b in changes]
    return []

def repair_wheel_axes(path: Path, mode: str) -> list[dict]:
    if mode!='aggressive' or path.suffix.lower()!='.jbeam': return []
    text=read_text(path); changes=[]
    text,n1=re.subn(r'("wheelDir"\s*:\s*)\[\s*0\s*,\s*0\s*,\s*0\s*\]',r'\g<1>[0, 0, 1]',text,flags=re.I)
    if n1: changes.append(f'wheelDir={n1}')
    text,n2=re.subn(r'("wheelAxis"\s*:\s*)\[\s*0\s*,\s*0\s*,\s*0\s*\]',r'\g<1>[1, 0, 0]',text,flags=re.I)
    if n2: changes.append(f'wheelAxis={n2}')
    if not changes: return []
    path.write_text(text,'utf-8')
    return [{'level':'fixed','stage':'repair','title':'Исправлены нулевые направления колёс','details':f'{path.name}: {", ".join(changes)} — применено только к явно нулевым векторам.'}]

def repair_physics_values(path: Path, mode: str) -> list[dict]:
    if mode not in {'medium','aggressive'} or path.suffix.lower()!='.jbeam': return []
    text=read_text(path); changes=0
    for key in ('beamStrength','beamDeform','nodeWeight','nodeWeightFactor'):
        text,n=re.subn(rf'("{re.escape(key)}"\s*:\s*)-?0+(?:\.0+)?',rf'\g<1>1',text,flags=re.I); changes+=n
    if not changes: return []
    path.write_text(text,'utf-8')
    return [{'level':'fixed','stage':'repair','title':'Нормализованы очевидно нулевые параметры физики','details':f'{path.name}: изменено значений — {changes}; эвристический ремонт.'}]

def parse_modification_request(text: str) -> dict:
    t=(text or '').lower()
    req={'suspension':None,'engine_percent':None,'engine_rpm_percent':None,'configs':0,'notes':[]}
    if any(x in t for x in ('мягк','soft suspension','смягч')): req['suspension']='soft'
    elif any(x in t for x in ('жёст','жест','hard suspension','harder suspension')): req['suspension']='hard'
    m=re.search(r'(?:двигател|мотор|engine).{0,80}?(?:\+|на|до)?\s*(\d{1,3})\s*%',t)
    if m: req['engine_percent']=int(m.group(1))
    elif any(x in t for x in ('ускор','мощн','быстрее','больше мощ')): req['engine_percent']=10
    if any(x in t for x in ('обороты','rpm','лимит оборот')): req['engine_rpm_percent']=10
    cm=re.search(r'(?:добав(?:ь|ить)|создай|сделай).{0,40}?(\d+)\s*(?:конфиг|configuration)',t)
    if cm: req['configs']=max(1,min(8,int(cm.group(1))))
    elif any(x in t for x in ('больше конфигурац','ещё конфиг','дополнительные конфиг')): req['configs']=2
    return req


def _scale_numeric_value(match, factor):
    try: return match.group(1)+str(round(float(match.group(2))*factor, 6))+match.group(3)
    except Exception: return match.group(0)


def apply_modification_request(root: Path, request_text: str, job: dict) -> list[dict]:
    req=parse_modification_request(request_text); issues=[]; files=[p for p in root.rglob('*') if p.is_file()]; jbeams=[p for p in files if p.suffix.lower()=='.jbeam'];
    if req['suspension'] and jbeams:
        factor_s, factor_d=(0.82,0.88) if req['suspension']=='soft' else (1.20,1.14)
        for p in jbeams:
            check_cancel_pause(job); text=read_text(p); changes=0
            for key,factor in (("spring",factor_s),("beamSpring",factor_s),("damp",factor_d),("beamDamp",factor_d),("springExpansion",factor_s),("dampExpansion",factor_d)):
                pat=rf'("{re.escape(key)}"\s*:\s*)(-?\d+(?:\.\d+)?)(\s*[,}}])'
                text,n=re.subn(pat,lambda m,f=factor:_scale_numeric_value(m,f),text,flags=re.I); changes+=n
            if changes:
                p.write_text(text,'utf-8'); issues.append({'level':'fixed','stage':'modify','title':f'Подвеска сделана {"мягче" if req["suspension"]=="soft" else "жёстче"}','details':f'{p.relative_to(root).as_posix()}: изменено числовых параметров — {changes}'})
    if req['engine_percent']:
        factor=1+req['engine_percent']/100
        for p in jbeams:
            check_cancel_pause(job); text=read_text(p); changes=0
            for key in ('torque','torqueBoost','maxTorque','peakTorque'):
                pat=rf'("{re.escape(key)}"\s*:\s*)(-?\d+(?:\.\d+)?)(\s*[,}}])'
                text,n=re.subn(pat,lambda m,f=factor:_scale_numeric_value(m,f),text,flags=re.I); changes+=n
            if changes:
                p.write_text(text,'utf-8'); issues.append({'level':'fixed','stage':'modify','title':f'Тяга двигателя изменена на +{req["engine_percent"]}%','details':f'{p.relative_to(root).as_posix()}: изменено значений — {changes}. Эвристически, требуется тест в игре.'})
    if req['engine_rpm_percent']:
        factor=1+req['engine_rpm_percent']/100
        for p in jbeams:
            text=read_text(p); changes=0
            for key in ('maxRPM','maxRpm','idleRPM'):
                pat=rf'("{re.escape(key)}"\s*:\s*)(-?\d+(?:\.\d+)?)(\s*[,}}])'
                text,n=re.subn(pat,lambda m,f=factor:_scale_numeric_value(m,f),text,flags=re.I); changes+=n
            if changes:
                p.write_text(text,'utf-8'); issues.append({'level':'fixed','stage':'modify','title':f'Диапазон оборотов изменён на +{req["engine_rpm_percent"]}%','details':p.relative_to(root).as_posix()})
    if req['configs']:
        pcs=[p for p in files if p.suffix.lower()=='.pc']
        if pcs:
            created=0
            for src in pcs[:1]:
                raw=read_text(src)
                try: data=json.loads(raw)
                except Exception: data=None
                if isinstance(data,dict):
                    stem=src.stem
                    for i in range(1,req['configs']+1):
                        out=src.with_name(f'{stem}_ModForge_{i}.pc')
                        if out.exists(): continue
                        clone=json.loads(json.dumps(data))
                        clone.setdefault('vars', {})['$modforgeVariant']=i
                        out.write_text(json.dumps(clone,ensure_ascii=False,indent=2)+'\n','utf-8'); created+=1
            if created: issues.append({'level':'fixed','stage':'modify','title':'Созданы дополнительные PC-конфигурации','details':f'Добавлено: {created}. Они основаны на первой найденной конфигурации и требуют проверки в игре.'})
        else:
            issues.append({'level':'warning','stage':'modify','title':'Конфигурации не добавлены','details':'В моде не найден исходный .pc-файл, от которого безопасно создать варианты.'})
    if not issues:
        issues.append({'level':'warning','stage':'modify','title':'Изменение не распознано автоматически','details':'Опишите пожелание конкретнее: например «сделать подвеску мягче на 15%» или «увеличить тягу двигателя на 10%».'})
    return issues


def repair_tree(root: Path, job: dict) -> list[dict]:
    mode=job.get('repair_mode','standard')
    files=[p for p in root.rglob('*') if p.is_file()]; file_set={p.relative_to(root).as_posix() for p in files}; ci=case_index(file_set)
    resource_index={x.casefold() for x in file_set}
    issues=[]; total=max(1,len(files))
    for idx,path in enumerate(files,1):
        check_cancel_pause(job); rel=path.relative_to(root).as_posix()
        if should_check_text(path):
            text=read_text(path)
            for match in list(RESOURCE_RE.finditer(text))[:MAX_RESOURCE_REFS_PER_FILE]:
                ref=match.group('path').replace('\\','/'); resolved=resolve_ref(ref,file_set,ci)
                if resolved and resolved!=ref and replace_reference(path,ref,resolved): issues.append({'level':'fixed','stage':'repair','title':'Исправлена внутренняя ссылка','details':f'{rel}: {ref} → {resolved}'})
                elif resolved is None:
                    candidates=candidates_for(ref,file_set); chosen=candidates[0] if len(candidates)==1 else None
                    if mode in {'medium','aggressive'} and not chosen: chosen=fuzzy_resource_candidate(ref,file_set)
                    if chosen and replace_reference(path,ref,chosen): issues.append({'level':'fixed','stage':'repair','title':'Восстановлена ссылка на найденный ресурс','details':f'{rel}: {ref} → {chosen}'})
        if mode in {'medium','aggressive'} and (path.suffix.lower()=='.json' or path.name.lower().endswith(('.materials.json','.level.json'))):
            ok,msg=repair_json_syntax(path)
            if ok: issues.append({'level':'fixed','stage':'repair','title':'Исправлен синтаксис конфигурации','details':f'{rel}: {msg}'})
        if path.suffix.lower()=='.json' or path.name.lower().endswith('.materials.json'):
            for change in repair_glass(path, root=root, resource_index=resource_index):
                detail=', '.join(f'{k}={v}' for k,v in change['updates'].items())
                issues.append({'level':'fixed','stage':'repair','title':'Нормализованы параметры материала стекла','details':f'{rel}: {change["material"]} → {detail}'})
        if path.suffix.lower()=='.jbeam':
            issues.extend(repair_vehicle_refs(path,mode))
            issues.extend(repair_wheel_axes(path,mode))
            issues.extend(repair_physics_values(path,mode))
        make_progress(job,7,idx/total)
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



def _vehicle_identity_tokens(root: Path) -> list[str]:
    ids=set(); vehicles=root/'vehicles'
    if not vehicles.exists(): return []
    for p in vehicles.rglob('*.jbeam'):
        rel=p.relative_to(vehicles)
        ids.add(p.stem.casefold())
        if rel.parts: ids.add(rel.parts[0].casefold())
    return sorted(ids)


def is_vehicle_mod(root: Path) -> bool:
    return (root/'vehicles').exists() and any(p.suffix.lower()=='.jbeam' for p in root.rglob('*') if p.is_file())


def _json_load_with_comments(text: str):
    try:
        return json.loads(text)
    except Exception:
        stripped = re.sub(r'/\*.*?\*/', '', text, flags=re.S)
        stripped = re.sub(r'(^|\s)//.*', r'\1', stripped)
        stripped = re.sub(r',\s*([}\]])', r'\1', stripped)
        return json.loads(stripped)


def _append_modforge_name(data: dict) -> bool:
    changed = False
    for key in list(data.keys()):
        if str(key).casefold() not in {'name', 'brand'}:
            continue
        value = data.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        if re.search(r'\bModForge\b', value, re.I):
            continue
        data[key] = value.rstrip() + ' ModForge'
        changed = True
        # Prefer a single visible marker; don't append to both brand and name.
        break
    if not changed and isinstance(data.get('Name'), str) and data.get('Name').strip():
        if not re.search(r'\bModForge\b', data['Name'], re.I):
            data['Name'] = data['Name'].rstrip() + ' ModForge'
            changed = True
    return changed


def _vehicle_preview_candidates(vehicle_dir: Path) -> list[Path]:
    exts={'.png','.jpg','.jpeg','.webp'}
    candidates=[]
    for p in vehicle_dir.rglob('*'):
        if not p.is_file() or p.suffix.lower() not in exts:
            continue
        name=p.name.casefold()
        rel=p.relative_to(vehicle_dir)
        # Only likely preview/thumbnail files, never arbitrary texture atlases.
        score=0
        if any(token in name for token in ('thumbnail','thumb','preview','default')): score += 10
        if name.startswith('info_'): score += 8
        if p.stem.casefold() == vehicle_dir.name.casefold(): score += 8
        if rel.parent == Path('.'): score += 4
        if score: candidates.append((score,p))
    candidates.sort(key=lambda item: (-item[0], str(item[1]).casefold()))
    return [p for _,p in candidates[:24]]


def _apply_logo_watermark(image_path: Path, logo_path: Path) -> bool:
    try:
        from PIL import Image
        with Image.open(image_path) as base:
            base = base.convert('RGBA')
            with Image.open(logo_path) as logo:
                logo = logo.convert('RGBA')
                # Compact, visible marker that works on the small vehicle card/thumbnail.
                target_w=max(34, min(110, int(base.width * 0.20)))
                ratio=target_w / max(1, logo.width)
                target_h=max(1, int(logo.height * ratio))
                logo=logo.resize((target_w,target_h), Image.Resampling.LANCZOS)
                alpha=logo.getchannel('A').point(lambda a: int(a*0.88))
                logo.putalpha(alpha)
                pad=max(6, int(min(base.width, base.height)*0.025))
                base.alpha_composite(logo, (max(0, base.width-logo.width-pad), pad))
            if image_path.suffix.lower() in {'.jpg','.jpeg'}:
                base=base.convert('RGB')
                base.save(image_path, quality=92, optimize=True)
            else:
                base.save(image_path, optimize=True)
        return True
    except Exception:
        return False


def inject_modforge_status(root: Path, job: dict) -> None:
    """Brand repaired vehicle mods without requiring users to add a UI app manually.

    BeamNG's official vehicle docs state that brand/name are shown in the vehicle selector.
    The built-in vehicle card also relies on vehicle preview imagery, so we brand that preview
    and write a marker file instead of installing a separate UI app layout.
    """
    if not is_vehicle_mod(root): return
    if (root/'modforge_applied.json').exists():
        return
    logo_path=ASSET_ROOT/'logo.png'
    branded=[]
    watermarked=[]
    vehicles_root=root/'vehicles'
    for vehicle_dir in sorted([p for p in vehicles_root.iterdir() if p.is_dir()], key=lambda p: p.name.casefold()):
        jbeams=list(vehicle_dir.rglob('*.jbeam'))
        if not jbeams:
            continue
        info_candidates=[p for p in vehicle_dir.rglob('info.json') if p.is_file()]
        for info_path in info_candidates:
            try:
                raw=info_path.read_text('utf-8-sig')
                data=_json_load_with_comments(raw)
                if not isinstance(data, dict):
                    continue
                if _append_modforge_name(data):
                    info_path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n','utf-8')
                    branded.append(info_path.relative_to(root).as_posix())
            except Exception:
                continue
        if logo_path.exists():
            for image_path in _vehicle_preview_candidates(vehicle_dir):
                if _apply_logo_watermark(image_path, logo_path):
                    watermarked.append(image_path.relative_to(root).as_posix())
    marker={
        'service':'ModForge',
        'version':APP_VERSION,
        'repair_mode':job.get('repair_mode','standard'),
        'status':'repaired-artifact',
        'vehicle_ids':_vehicle_identity_tokens(root),
        'branding':{
            'vehicle_name_suffix':' ModForge',
            'thumbnail_watermark':bool(watermarked),
            'info_files':branded,
            'preview_files':watermarked,
        },
        'activation':'Статический знак ModForge добавлен в данные автомобиля: название и доступные preview/thumbnail-файлы. Отдельный UI Apps больше не требуется.'
    }
    (root/'modforge_applied.json').write_text(json.dumps(marker,ensure_ascii=False,indent=2),'utf-8')


def package_zip(root: Path, out: Path, job: dict, with_branding: bool = True) -> None:
    if with_branding:
        inject_modforge_status(root, job)
    files=[p for p in root.rglob("*") if p.is_file()]; total=max(1,len(files))
    with ZipFile(out,"w",ZIP_DEFLATED,compresslevel=6) as archive:
        for idx,path in enumerate(files,1):
            check_cancel_pause(job); archive.write(path,path.relative_to(root).as_posix()); make_progress(job,10,idx/total)


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
        count,total = _validate_zip_infos(infos)
        for info in infos:
            if info.is_dir(): continue
            rel=safe_rel(info.filename)
            out=dest/rel
            out.parent.mkdir(parents=True,exist_ok=True)
            with archive.open(info,"r") as src, out.open("wb") as outf:
                copied=0
                while True:
                    chunk=src.read(8*1024*1024)
                    if not chunk: break
                    copied += len(chunk)
                    if copied > MAX_SINGLE_FILE_UNPACKED:
                        raise ValueError(f"Файл внутри архива превышает безопасный предел: {rel}")
                    outf.write(chunk)
    return count,total


async def save_folder_uploads(files: list[UploadFile], manifest: list[str], dest: Path) -> int:
    if not files: raise ValueError("Выбранная папка не содержит файлов.")
    if len(files)>MAX_FILES: raise ValueError(f"Слишком много файлов. Максимум {MAX_FILES}.")
    raw_paths=[safe_rel(manifest[i] if i<len(manifest) else (files[i].filename or f"file_{i}")) for i in range(len(files))]
    roots=[p.split("/",1)[0] for p in raw_paths]; strip_root=len(set(roots))==1 and all("/" in p for p in raw_paths)
    total=0
    for i,upload in enumerate(files):
        rel=raw_paths[i]; rel=rel.split("/",1)[1] if strip_root and "/" in rel else rel; rel=safe_rel(rel)
        if len(Path(rel).parts) > MAX_PATH_DEPTH: raise ValueError(f"Слишком глубокая структура папки: {rel}")
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



# ─────────────────────────────────────────────────────────────
# V1 (0.42) diagnostic / repair workbench layer
# ─────────────────────────────────────────────────────────────
HEALTH_CATEGORIES = ["Structure", "Syntax", "Resources", "Materials", "Vehicle", "Configs", "Performance"]

ISSUE_CATEGORY_RULES = [
    ("performance", "Performance"),
    ("materials", "Materials"),
    ("текстур", "Materials"),
    ("glass", "Materials"),
    ("стекл", "Materials"),
    ("vehicle", "Vehicle"),
    ("колес", "Vehicle"),
    ("wheel", "Vehicle"),
    ("jbeam", "Vehicle"),
    ("configs", "Configs"),
    ("конфигурац", "Configs"),
    ("pc-", "Configs"),
    ("syntax", "Syntax"),
    ("синтаксис", "Syntax"),
    ("json", "Syntax"),
    ("resources", "Resources"),
    ("ресурс", "Resources"),
    ("ссылк", "Resources"),
    ("structure", "Structure"),
    ("структур", "Structure"),
    ("duplicate", "Structure"),
    ("дублик", "Structure"),
]

REPAIR_RULES = {
    "RES-CASE": {
        "category": "RESOURCES", "detection": "Reference resolves to a single existing path with different casing/spelling separators.",
        "fix": "replace_reference", "severity": "ERROR", "confidence": "SAFE", "verification": "resolve_ref"
    },
    "RES-UNIQUE": {
        "category": "RESOURCES", "detection": "Missing reference has exactly one basename candidate in the resource index.",
        "fix": "replace_reference", "severity": "ERROR", "confidence": "SAFE", "verification": "resolve_ref"
    },
    "RES-FUZZY": {
        "category": "RESOURCES", "detection": "Missing reference has one high-confidence fuzzy candidate under medium/aggressive repair mode.",
        "fix": "replace_reference", "severity": "ERROR", "confidence": "HEURISTIC", "verification": "resolve_ref"
    },
    "JSON-TRAILING-COMMA": {
        "category": "JSON", "detection": "Removing trailing commas produces valid JSON.",
        "fix": "repair_json_syntax", "severity": "ERROR", "confidence": "SAFE", "verification": "json.loads"
    },
    "MAT-GLASS-FALLBACK": {
        "category": "MATERIALS", "detection": "Glass material references one or more missing maps and can be given a local fallback material definition.",
        "fix": "repair_glass", "severity": "ERROR", "confidence": "MANUAL REVIEW", "verification": "json.loads + local refs"
    },
    "JBEAM-WHEEL-REF": {
        "category": "VEHICLE", "detection": "Wheel node reference is missing but a single close JBeam token can be identified.",
        "fix": "repair_vehicle_refs", "severity": "ERROR", "confidence": "HEURISTIC", "verification": "token/reference re-scan"
    },
    "JBEAM-WHEEL-AXIS": {
        "category": "VEHICLE", "detection": "Wheel direction/axis is explicitly [0,0,0] and aggressive repair is enabled.",
        "fix": "repair_wheel_axes", "severity": "WARNING", "confidence": "HEURISTIC", "verification": "non-zero vector re-scan"
    },
    "JBEAM-PHYSICS-ZERO": {
        "category": "VEHICLE", "detection": "Known physics scalar is explicitly zero in medium/aggressive repair mode.",
        "fix": "repair_physics_values", "severity": "WARNING", "confidence": "HEURISTIC", "verification": "numeric re-scan"
    },
}


def issue_category(item: dict) -> str:
    explicit = str(item.get("category") or "").strip()
    if explicit in HEALTH_CATEGORIES:
        return explicit
    hay = f"{item.get('stage','')} {item.get('title','')} {item.get('details','')}".lower()
    for token, category in ISSUE_CATEGORY_RULES:
        if token in hay:
            return category
    return "Structure"


def issue_severity(item: dict) -> str:
    explicit = str(item.get("severity") or "").upper().replace(" ", "_")
    if explicit in {"CRITICAL", "ERROR", "WARNING", "INFO"}:
        return explicit
    level = str(item.get("level") or "").lower()
    if level == "ok":
        return "INFO"
    hay = f"{item.get('title','')} {item.get('details','')}".lower()
    if any(x in hay for x in ("unsafe", "архивная бомба", "path traversal", "resource exhaustion")):
        return "CRITICAL"
    if any(x in hay for x in ("не разбирается", "несостыков", "синтаксис", "всё ещё некоррект", "не найден", "не найд", "отсутств")):
        return "ERROR"
    if level in {"warning", "fixed"}:
        return "WARNING"
    return "INFO"


def issue_confidence(item: dict) -> str:
    explicit = str(item.get("confidence") or "").upper().replace(" ", "_")
    if explicit in {"SAFE", "PROBABLE", "HEURISTIC", "MANUAL_REVIEW"}:
        return explicit
    hay = f"{item.get('title','')} {item.get('details','')}".lower()
    if any(x in hay for x in ("эврист", "fuzzy", "похож", "связан", "подозрит")):
        return "HEURISTIC"
    if any(x in hay for x in ("ручн", "требует проверки", "требует тест", "в игре", "не подтвержд")):
        return "MANUAL_REVIEW"
    if any(x in hay for x in ("точно", "явн", "валид", "коррект", "изменена ссылка")):
        return "SAFE"
    if any(x in hay for x in ("не найден", "отсутств", "похоже")):
        return "PROBABLE"
    return "SAFE" if str(item.get("level") or "").lower() == "ok" else "PROBABLE"


def infer_rule_id(item: dict) -> str | None:
    explicit = item.get("rule_id")
    if explicit:
        return str(explicit)
    hay = f"{item.get('title','')} {item.get('details','')}".lower()
    if "завершающ" in hay and "запят" in hay or "синтаксис конфигурации" in hay:
        return "JSON-TRAILING-COMMA"
    if "внутреннюю ссылку" in hay and "исправ" in hay:
        return "RES-CASE"
    if "восстановлена ссылка" in hay:
        return "RES-UNIQUE"
    if "эвристичес" in hay and "ссыл" in hay:
        return "RES-FUZZY"
    if "стекл" in hay and "материал" in hay:
        return "MAT-GLASS-FALLBACK"
    if "связи узлов кол" in hay:
        return "JBEAM-WHEEL-REF"
    if "направления кол" in hay or "wheelaxis" in hay or "wheeldir" in hay:
        return "JBEAM-WHEEL-AXIS"
    if "параметр" in hay and "физик" in hay:
        return "JBEAM-PHYSICS-ZERO"
    return None


def normalize_issues(issues: list[dict]) -> list[dict]:
    out = []
    for raw in issues:
        x = dict(raw)
        level = str(x.get("level") or "warning").lower()
        x["status"] = "fixed" if level == "fixed" else ("verified" if level == "ok" else "unresolved")
        x["severity"] = issue_severity(x)
        x["confidence"] = issue_confidence(x)
        x["category"] = issue_category(x)
        x["rule_id"] = infer_rule_id(x)
        x["verification"] = str(x.get("verification") or "manual review")
        if x.get("file") is None:
            details = str(x.get("details") or "")
            m = re.match(r"([^:]+):\s", details)
            if m and "/" in m.group(1):
                x["file"] = m.group(1)
        out.append(x)
    return out


def health_from_issues(issues: list[dict], scanned: set[str] | None = None) -> dict:
    scanned = scanned or set(HEALTH_CATEGORIES)
    by_category = {}
    for category in HEALTH_CATEGORIES:
        rows = [x for x in issues if x.get("category") == category]
        unresolved = [x for x in rows if x.get("status") == "unresolved"]
        crit = sum(1 for x in unresolved if x.get("severity") == "CRITICAL")
        err = sum(1 for x in unresolved if x.get("severity") == "ERROR")
        warn = sum(1 for x in unresolved if x.get("severity") == "WARNING")
        if category not in scanned:
            state = "NOT_SCANNED"
        elif crit or err:
            state = "FAIL"
        elif warn:
            state = "REVIEW"
        else:
            state = "PASS"
        by_category[category] = {
            "status": state,
            "critical": crit,
            "errors": err,
            "warnings": warn,
            "verified": sum(1 for x in rows if x.get("status") == "verified"),
            "fixed": sum(1 for x in rows if x.get("status") == "fixed"),
            "issue_count": len(rows),
        }
    failed = sum(1 for x in by_category.values() if x["status"] == "FAIL")
    review = sum(1 for x in by_category.values() if x["status"] == "REVIEW")
    overall = "FAIL" if failed else ("REVIEW" if review else "PASS")
    return {"overall": overall, "categories": by_category, "failed_categories": failed, "review_categories": review}


def _text_plausibly_json(path: Path) -> bool:
    return path.suffix.lower() in {".json", ".pc"} or path.name.lower().endswith((".materials.json", ".level.json"))


def build_repair_preview(root: Path, mode: str, task_mode: str = "repair", modification_request: str = "") -> dict:
    files = [p for p in root.rglob("*") if p.is_file()]
    file_set = {p.relative_to(root).as_posix() for p in files}
    ci = case_index(file_set)
    plans = []
    seen = set()

    def add(rule_id, path, action, safe, confidence, reason, preview):
        rel = path.relative_to(root).as_posix() if isinstance(path, Path) else str(path)
        key = (rule_id, rel, action, preview)
        if key in seen:
            return
        seen.add(key)
        rule = REPAIR_RULES.get(rule_id, {})
        plans.append({
            "rule_id": rule_id, "category": rule.get("category", "STRUCTURE"), "file": rel,
            "action": action, "safe": bool(safe), "confidence": confidence,
            "severity": rule.get("severity", "WARNING"), "reason": reason, "preview": preview,
            "verification": rule.get("verification", "re-scan"),
        })

    if task_mode == "modify":
        req = parse_modification_request(modification_request)
        for p in files:
            if p.suffix.lower() == ".jbeam":
                text = read_text(p)
                if req.get("suspension"):
                    add("JBEAM-PHYSICS-ZERO", p, "scale suspension values", False, "MANUAL_REVIEW", "Изменение подвески — эвристический Mod Lab запрос.", "Изменит spring/damp-параметры.")
                if req.get("engine_percent") or req.get("engine_rpm_percent"):
                    add("JBEAM-PHYSICS-ZERO", p, "scale engine values", False, "MANUAL_REVIEW", "Изменение двигателя выполняется текстовым правилом Mod Lab.", "Изменит torque/RPM параметры.")
            if req.get("configs") and p.suffix.lower() == ".pc":
                add("JSON-TRAILING-COMMA", p, "clone config", False, "MANUAL_REVIEW", "Конфигурации будут созданы на базе найденного PC.", f"До {req['configs']} новых .pc вариантов.")
        if not plans and any(int(v or 0) for k, v in req.items() if k == "configs"):
            pass
    else:
        for p in files:
            if should_check_text(p):
                text = read_text(p)
                for match in list(RESOURCE_RE.finditer(text))[:MAX_RESOURCE_REFS_PER_FILE]:
                    ref = match.group("path").replace("\\", "/")
                    resolved = resolve_ref(ref, file_set, ci)
                    if resolved and resolved != ref:
                        add("RES-CASE", p, "replace reference", True, "SAFE", "Ссылка однозначно разрешается в существующий путь.", f"{ref} → {resolved}")
                    elif resolved is None:
                        candidates = candidates_for(ref, file_set)
                        if len(candidates) == 1:
                            add("RES-UNIQUE", p, "replace reference", True, "SAFE", "Найден ровно один локальный кандидат с тем же именем файла.", f"{ref} → {candidates[0]}")
                        elif mode in {"medium", "aggressive"}:
                            chosen = fuzzy_resource_candidate(ref, file_set)
                            if chosen:
                                add("RES-FUZZY", p, "replace reference", False, "HEURISTIC", "Выбран не точный, а эвристически похожий ресурс.", f"{ref} → {chosen}")
                if _text_plausibly_json(p):
                    raw = read_text(p)
                    cleaned = re.sub(r',\s*([}\]])', r'\1', raw)
                    if cleaned != raw:
                        try:
                            json.loads(cleaned)
                        except Exception:
                            pass
                        else:
                            add("JSON-TRAILING-COMMA", p, "remove trailing commas", True, "SAFE", "После удаления завершающих запятых JSON разбирается валидно.", "JSON syntax repair")
            if p.suffix.lower() == ".json" or p.name.lower().endswith(".materials.json"):
                try:
                    data = json.loads(read_text(p))
                except Exception:
                    data = None
                if isinstance(data, dict):
                    for key, mat in material_objects(data):
                        if not _is_glass_material(mat):
                            continue
                        broken = []
                        for field, ref in _material_maps(mat):
                            if ref and not _resource_exists(root, ref):
                                broken.append((field, ref))
                        if broken:
                            add("MAT-GLASS-FALLBACK", p, "material fallback", False, "MANUAL_REVIEW", "У материала стекла есть отсутствующие карты; будет применён fallback без внешней текстуры.", f"{key}: {len(broken)} missing map(s)")
            if p.suffix.lower() == ".jbeam":
                text = read_text(p); tokens = _jbeam_string_tokens(text)
                for wheel, n1, n2 in _wheel_refs(text):
                    for side, ref in (("node1", n1), ("node2", n2)):
                        if ref and ref not in tokens:
                            cand = difflib.get_close_matches(ref, list(tokens), n=2, cutoff=0.72 if mode == "medium" else 0.60)
                            if len(cand) == 1:
                                add("JBEAM-WHEEL-REF", p, "repair wheel node reference", False, "HEURISTIC", "Найдена одна близкая JBeam-ссылка.", f"{wheel}.{side}: {ref} → {cand[0]}")
                if mode == "aggressive" and re.search(r'"(?:wheelDir|wheelAxis)"\s*:\s*\[\s*0\s*,\s*0\s*,\s*0\s*\]', text, re.I):
                    add("JBEAM-WHEEL-AXIS", p, "set non-zero wheel vector", False, "HEURISTIC", "Вектор явно равен нулю; это запрещённая для ремонта эвристика без игровых данных.", "wheelDir/wheelAxis fallback")
                if mode in {"medium", "aggressive"} and re.search(r'"(?:beamStrength|beamDeform|nodeWeight|nodeWeightFactor)"\s*:\s*-?0+(?:\.0+)?', text, re.I):
                    add("JBEAM-PHYSICS-ZERO", p, "normalize physics scalar", False, "HEURISTIC", "Параметр физики явно равен нулю; значение будет поднято до 1.", "0 → 1")

    files_to_change = sorted({p["file"] for p in plans})
    return {
        "mode": mode, "task_mode": task_mode, "files_to_change": len(files_to_change),
        "safe_changes": sum(1 for p in plans if p["safe"]),
        "heuristic_changes": sum(1 for p in plans if not p["safe"]),
        "manual_review_required": sum(1 for p in plans if p["confidence"] == "MANUAL_REVIEW"),
        "expected_remaining_review": sum(1 for p in plans if not p["safe"]),
        "unresolved_before_repair": 0,
        "plans": plans[:MAX_DIFF_FILES],
        "rules": sorted(REPAIR_RULES.keys()),
        "note": "Preview основан только на фактических файлах и текущих repair rules; он не гарантирует игровой результат без проверки в BeamNG.drive.",
    }


def snapshot_for_preview(root: Path, preview: dict) -> dict:
    snap = {}
    for item in preview.get("plans", [])[:MAX_DIFF_FILES]:
        rel = item.get("file")
        if not rel:
            continue
        path = root / rel
        if not path.is_file():
            continue
        raw = path.read_bytes()
        record = {"sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}
        if should_check_text(path) and len(raw) <= 700_000:
            record["text"] = raw.decode("utf-8", errors="replace")
        snap[rel] = record
    return snap


def collect_diffs(root: Path, before: dict, reasons: list[dict] | None = None) -> list[dict]:
    reasons = reasons or []
    reason_map = {}
    for item in reasons:
        f = item.get("file") or ""
        reason_map.setdefault(f, []).append(item.get("title") or item.get("reason") or item.get("rule_id") or "Repair rule")
    diffs = []
    for rel, old in before.items():
        path = root / rel
        if not path.is_file():
            diffs.append({"file": rel, "status": "removed", "before_sha256": old.get("sha256"), "after_sha256": None, "reasons": reason_map.get(rel, [])})
            continue
        new_raw = path.read_bytes()
        new_sha = hashlib.sha256(new_raw).hexdigest()
        if new_sha == old.get("sha256"):
            continue
        item = {"file": rel, "status": "changed", "before_sha256": old.get("sha256"), "after_sha256": new_sha, "before_size": old.get("size", 0), "after_size": len(new_raw), "reasons": reason_map.get(rel, [])}
        if "text" in old and should_check_text(path) and len(new_raw) <= 700_000:
            after = new_raw.decode("utf-8", errors="replace")
            diff_text = "".join(difflib.unified_diff(old["text"].splitlines(True), after.splitlines(True), fromfile=f"BEFORE/{rel}", tofile=f"AFTER/{rel}", n=3))
            item["before"] = old["text"][:MAX_DIFF_CHARS]
            item["after"] = after[:MAX_DIFF_CHARS]
            item["diff"] = diff_text[:MAX_DIFF_CHARS]
        else:
            item["diff"] = "Binary or large-text resource: hash/size diff only."
        diffs.append(item)
        if len(diffs) >= MAX_DIFF_FILES:
            break
    # New files created by repair / Mod Lab.
    before_names = set(before)
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if rel in before_names:
            continue
        if rel.startswith("history/"):
            continue
        if rel not in {x["file"] for x in diffs} and len(diffs) < MAX_DIFF_FILES:
            raw = path.read_bytes()
            diffs.append({"file": rel, "status": "added", "before_sha256": None, "after_sha256": hashlib.sha256(raw).hexdigest(), "before_size": 0, "after_size": len(raw), "reasons": reason_map.get(rel, [])})
    return diffs


def hash_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def build_resource_inspector(root: Path) -> dict:
    files = [p for p in root.rglob("*") if p.is_file()][:MAX_INSPECTOR_FILES]
    rel_to_path = {p.relative_to(root).as_posix(): p for p in files}
    refs = []
    ref_by_target = {rel: [] for rel in rel_to_path}
    refs_by_source = {rel: [] for rel in rel_to_path}
    file_set = set(rel_to_path)
    ci = case_index(file_set)
    for p in files:
        if not should_check_text(p):
            continue
        rel = p.relative_to(root).as_posix()
        text = read_text(p)
        for match in list(RESOURCE_RE.finditer(text))[:MAX_RESOURCE_REFS_PER_FILE]:
            ref = match.group("path").replace("\\", "/")
            resolved = resolve_ref(ref, file_set, ci)
            record = {"source": rel, "reference": ref, "resolved": resolved}
            refs.append(record)
            refs_by_source.setdefault(rel, []).append(ref)
            if resolved:
                ref_by_target.setdefault(resolved, []).append(rel)
    by_hash = {}
    rows = []
    for rel, p in rel_to_path.items():
        try:
            sha = hash_file(p)
            size = p.stat().st_size
        except OSError:
            continue
        referenced_by = sorted(set(ref_by_target.get(rel, [])))[:80]
        problems = []
        if len(by_hash.get((size, sha), [])) > 1:
            problems.append("duplicate_hash")
        if not referenced_by and Path(rel).suffix.lower() in {".dds", ".png", ".jpg", ".jpeg", ".tga", ".bmp", ".gif", ".dae", ".cdae", ".ogg", ".wav", ".mp3", ".flac"}:
            problems.append("unused_candidate")
        rows.append({"path": rel, "size": size, "sha256": sha, "references": refs_by_source.get(rel, [])[:80], "referenced_by": referenced_by, "problems": problems, "status": "DUPLICATE" if "duplicate_hash" in problems else ("UNUSED_CANDIDATE" if "unused_candidate" in problems else "OK")})
        by_hash.setdefault((size, sha), []).append(rel)
    duplicates = [paths for paths in by_hash.values() if len(paths) > 1]
    duplicate_paths = {path for group in duplicates for path in group}
    for row in rows:
        if row["path"] in duplicate_paths and "duplicate_hash" not in row["problems"]:
            row["problems"].append("duplicate_hash")
            row["status"] = "DUPLICATE"
    unused = [r["path"] for r in rows if not r["referenced_by"] and Path(r["path"]).suffix.lower() in {".dds", ".png", ".jpg", ".jpeg", ".tga", ".bmp", ".gif", ".dae", ".cdae", ".ogg", ".wav", ".mp3", ".flac"}]
    missing = [x for x in refs if x["resolved"] is None]
    shared = [{"path": r["path"], "referenced_by": r["referenced_by"]} for r in rows if len(r["referenced_by"]) > 1]
    tree = {}
    for row in rows:
        cursor = tree
        parts = Path(row["path"]).parts
        for part in parts[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[parts[-1]] = {"size": row["size"], "status": row["status"]}
    return {
        "files": rows,
        "references": refs[:10000],
        "missing_references": missing[:5000],
        "unused_resources": unused[:5000],
        "duplicates": duplicates[:1000],
        "shared_dependencies": shared[:5000],
        "tree": tree,
        "file_count": len(rows), "reference_count": len(refs),
    }


def performance_scan(root: Path, inspector: dict) -> dict:
    issues = []
    for row in inspector.get("files", []):
        ext = Path(row["path"]).suffix.lower()
        if ext in {".png", ".jpg", ".jpeg", ".tga", ".bmp", ".dds"} and row["size"] >= MAX_TEXTURE_WARN_BYTES:
            issues.append({"level": "warning", "stage": "performance", "category": "Performance", "title": "Большая текстура", "details": f"{row['path']} — {row['size']} bytes; проверьте размер/сжатие текстуры."})
        if ext in {".dae", ".cdae"} and row["size"] >= MAX_GEOMETRY_WARN_BYTES:
            issues.append({"level": "warning", "stage": "performance", "category": "Performance", "title": "Большой геометрический ресурс", "details": f"{row['path']} — {row['size']} bytes; это потенциальный источник нагрузки, не прогноз FPS."})
    for paths in inspector.get("duplicates", []):
        issues.append({"level": "info", "stage": "performance", "category": "Performance", "title": "Дублирующийся ресурс", "details": "Одинаковый SHA-256: " + ", ".join(paths[:8]) + ("…" if len(paths) > 8 else "")})
    for path in inspector.get("unused_resources", [])[:1200]:
        issues.append({"level": "info", "stage": "performance", "category": "Performance", "title": "Ресурс не используется найденными локальными ссылками", "details": path})
    return {"issues": issues, "large_resources": sum(1 for x in issues if x.get("title") == "Большая текстура"), "duplicate_groups": len(inspector.get("duplicates", [])), "unused_count": len(inspector.get("unused_resources", []))}


def cleaner_candidates(root: Path) -> list[str]:
    names = {"thumbs.db", ".ds_store", "desktop.ini"}
    out = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        low = p.name.lower()
        if low in names or "/__macosx/" in f"/{rel.lower()}/" or low.startswith("._"):
            out.append(rel)
            continue
        if re.search(r"(?:\.bak|\.backup|\.tmp|~)$", low) or re.search(r"(?:^|[._-])backup(?:[._-]|$)", low):
            out.append(rel)
    return sorted(set(out))


def clean_tree_safe(root: Path) -> list[str]:
    removed = []
    for rel in cleaner_candidates(root):
        p = root / rel
        if not p.is_file():
            continue
        try:
            p.unlink()
            removed.append(rel)
        except OSError:
            continue
    # Remove empty __MACOSX directories only after deleting safe contents.
    for d in sorted([p for p in root.rglob("*") if p.is_dir() and p.name.lower() == "__macosx"], key=lambda p: len(p.parts), reverse=True):
        try:
            d.rmdir()
        except OSError:
            pass
    return removed


def save_history_snapshot(root: Path, history_root: Path, stage: str, job: dict) -> str:
    history_root.mkdir(parents=True, exist_ok=True)
    out = history_root / f"{stage}.zip"
    with ZipFile(out, "w", ZIP_DEFLATED, compresslevel=6) as zf:
        files = [p for p in root.rglob("*") if p.is_file()]
        for p in files:
            check_cancel_pause(job)
            zf.write(p, p.relative_to(root).as_posix())
    return str(out)


def history_listing(job: dict) -> dict:
    root = Path(job["root"]); h = root / "history"
    stages = []
    original = root / "source"
    if original.exists():
        stages.append({"stage": "original", "available": True, "source": "source"})
    for stage in ("repair", "optimized", "mod_lab"):
        path = h / f"{stage}.zip"
        stages.append({"stage": stage, "available": path.exists(), "size": path.stat().st_size if path.exists() else 0})
    return {"stages": stages, "note": "Original source copy is preserved separately and is never overwritten by repair/release operations."}


def security_zip_summary(zip_path: Path) -> dict:
    with ZipFile(zip_path, "r") as zf:
        infos = zf.infolist()
        total = sum(int(i.file_size) for i in infos if not i.is_dir())
        compressed = sum(int(i.compress_size) for i in infos if not i.is_dir())
        ratio = (total / compressed) if compressed else (float("inf") if total else 1.0)
        return {"files": len(infos), "unpacked_bytes": total, "compressed_bytes": compressed, "compression_ratio": ratio, "path_traversal": False, "symlinks": False, "encrypted": False, "archive_bomb_guard": True}


def _validate_zip_infos(infos):
    seen = set(); total = 0; compressed_total = 0
    for info in infos:
        rel = safe_rel(info.filename)
        if len(Path(rel).parts) > MAX_PATH_DEPTH:
            raise ValueError(f"Слишком глубокая структура ZIP: {rel}")
        key = rel.casefold()
        if key in seen:
            raise ValueError(f"В архиве повторяется путь файла: {rel}")
        seen.add(key)
        if info.file_size > MAX_SINGLE_FILE_UNPACKED:
            raise ValueError(f"Файл внутри архива слишком большой: {rel}")
        total += int(info.file_size)
        compressed_total += int(info.compress_size)
        if total > MAX_UNPACKED:
            raise ValueError("Распакованный архив превышает безопасный лимит 4 ГБ.")
        mode = (info.external_attr >> 16) & 0xFFFF
        if stat.S_ISLNK(mode):
            raise ValueError(f"Архив содержит символическую ссылку: {rel}")
        if info.flag_bits & 0x1:
            raise ValueError(f"Зашифрованные ZIP-файлы не поддерживаются: {rel}")
    if compressed_total and total / compressed_total > MAX_ARCHIVE_RATIO:
        raise ValueError("Архив отклонён: подозрительно высокий коэффициент сжатия (archive bomb guard).")
    return len(seen), total


def compare_zip_paths(left: Path, right: Path) -> dict:
    def manifest(path):
        with ZipFile(path, "r") as zf:
            infos = zf.infolist(); _validate_zip_infos(infos)
            out = {}
            for info in infos:
                if info.is_dir():
                    continue
                rel = safe_rel(info.filename)
                h = hashlib.sha256()
                with zf.open(info, "r") as src:
                    while True:
                        chunk = src.read(1024 * 1024)
                        if not chunk: break
                        h.update(chunk)
                out[rel] = {"sha256": h.hexdigest(), "size": int(info.file_size)}
            return out
    a, b = manifest(left), manifest(right)
    added = sorted(set(b) - set(a)); removed = sorted(set(a) - set(b)); changed = sorted(k for k in set(a) & set(b) if a[k]["sha256"] != b[k]["sha256"])
    conflicts = [{"path": k, "left": a[k], "right": b[k]} for k in changed]
    return {"left_files": len(a), "right_files": len(b), "added": added, "removed": removed, "changed": changed, "conflicts": conflicts, "same": not (added or removed or changed)}


def mod_doctor(job: dict, text: str) -> dict:
    report = job.get("report") or {}
    issues = report.get("issues") or []
    q = (text or "").lower().strip()
    patterns = [
        (("не едет", "не движ", "не едет", "двигател"), ["Vehicle", "Syntax", "Configs"], "Проверить JBeam-структуру, связанные узлы, конфигурации и физические параметры."),
        (("стекл", "окн", "window", "windshield", "glass"), ["Materials", "Resources"], "Проверить material maps стекла и существование текстурных ссылок."),
        (("колес", "wheel", "шина"), ["Vehicle", "Resources"], "Проверить pressureWheels, node1/node2 и связанные JBeam-узлы."),
        (("текстур", "texture", "no texture"), ["Materials", "Resources"], "Проверить missing references и карты материала."),
        (("свет", "фонар", "glow", "light"), ["Materials", "Resources"], "Проверить glowmap/emissive references и доступность текстур."),
    ]
    selected = next((x for x in patterns if any(t in q for t in x[0])), None)
    cats = set(selected[1]) if selected else set(HEALTH_CATEGORIES)
    matched = [x for x in issues if x.get("category") in cats and x.get("status") != "fixed"]
    # Prefer concrete error evidence over generic OK lines.
    matched.sort(key=lambda x: (x.get("severity") not in {"CRITICAL", "ERROR"}, x.get("confidence") == "HEURISTIC"))
    likely = []
    for x in matched[:8]:
        likely.append({"title": x.get("title"), "severity": x.get("severity"), "confidence": x.get("confidence"), "category": x.get("category"), "evidence": x.get("details")})
    suggestions = []
    if selected:
        suggestions.append({"action": selected[2], "mode": "standard", "safe_first": True})
    if not suggestions:
        suggestions.append({"action": "Запустите полную проверку и откройте Resource Inspector; после появления конкретной ошибки выберите стандартный repair mode.", "mode": "standard", "safe_first": True})
    return {"query": text[:1200], "interpretation": selected[2] if selected else "Запрос не привязан к одному типу проблемы; используйте фактические результаты анализа.", "likely_causes": likely, "evidence_count": len(likely), "suggested_actions": suggestions, "limitations": ["Mod Doctor не запускает BeamNG.drive и не выдаёт игровой диагноз без фактических данных модификации."]}

def report_summary(issues: list[dict], files_checked: int, fixed: int) -> dict:
    normalized = normalize_issues(issues)
    warnings = sum(1 for i in normalized if i.get("status") == "unresolved" and i.get("severity") == "WARNING")
    errors = sum(1 for i in normalized if i.get("status") == "unresolved" and i.get("severity") == "ERROR")
    critical = sum(1 for i in normalized if i.get("status") == "unresolved" and i.get("severity") == "CRITICAL")
    oks = sum(1 for i in normalized if i.get("status") == "verified")
    fixed_total = sum(1 for i in normalized if i.get("status") == "fixed")
    return {"files_checked":files_checked,"fixed":max(fixed, fixed_total),"warnings":warnings,"errors":errors,"critical":critical,"ok_checks":oks,"ok":critical==0 and errors==0 and warnings==0}


def verify_output_file(path: Path) -> None:
    if not path.exists() or not path.is_file() or path.stat().st_size <= 0:
        raise FileNotFoundError("Итоговый файл отсутствует или пуст.")
    if path.suffix.lower() == ".zip":
        with ZipFile(path, "r") as zf:
            infos = zf.infolist()
            if not infos:
                raise ValueError("Итоговый ZIP пуст.")
            for info in infos:
                safe_rel(info.filename)


def rebuild_output(job_id: str) -> Path:
    job = jobs.get(job_id)
    if not job:
        raise FileNotFoundError("Задание не найдено.")
    root = Path(job["root"])
    payload = root / "payload"
    if not payload.exists():
        raise FileNotFoundError("Рабочие файлы задания больше недоступны.")
    source_kind = job.get("source_kind", "zip")
    output_type = job.get("output_type", "zip")
    source_name = job.get("source_name") or job.get("original_name") or "beamng_mod"
    suffix = job.get("output_suffix") or "FIXED"
    original_name = job.get("original_name") or source_name
    job["status"] = "rebuilding"
    job["stage_label"] = "Восстановление файла"
    job["stage_detail"] = "Готовый результат отсутствовал, ModForge заново собирает его из сохранённой рабочей копии."
    job["progress"] = 99
    job["eta_seconds"] = None
    persist_job(job_id)
    if source_kind == "single" and output_type == "same":
        candidates = [p for p in payload.iterdir() if p.is_file()]
        if len(candidates) != 1:
            raise ValueError("Невозможно однозначно восстановить отдельный файл.")
        out_name = output_name(source_name or original_name, suffix, False)
        out_path = root / out_name
        shutil.copy2(candidates[0], out_path)
    else:
        out_name = output_name(source_name or original_name, suffix, True)
        out_path = root / out_name
        package_zip(payload, out_path, job)
    verify_output_file(out_path)
    report_path = root / "report.json"
    job.update(output=str(out_path), report_path=str(report_path), fixed_archive_name=out_path.name,
               download_url=f"/api/jobs/{job_id}/download", report_url=f"/api/jobs/{job_id}/report",
               status="done", progress=100, stage_progress=100, eta_seconds=0, stage_label="Готово",
               stage_detail="Файл восстановлен и снова доступен для скачивания.")
    if job.get("report"):
        job["report"]["output_name"] = out_path.name
        job["report"]["download_url"] = f"/api/jobs/{job_id}/download"
        job["report"]["report_url"] = f"/api/jobs/{job_id}/report"
        report_path.write_text(json.dumps(job["report"], ensure_ascii=False, indent=2), "utf-8")
    persist_job(job_id)
    return out_path


def ensure_output(job_id: str) -> Path:
    job = jobs.get(job_id)
    if not job or job.get("status") not in {"done", "rebuilding"}:
        raise FileNotFoundError("Готовый файл ещё недоступен.")
    path = Path(job.get("output") or "")
    if path.exists() and path.is_file() and path.stat().st_size > 0:
        return path
    return rebuild_output(job_id)


NETWORK_PROFILES = {
    "standard": {"mbps": 2, "workers": 2, "poll_ms": 900},
    "balanced": {"mbps": 5, "workers": 4, "poll_ms": 550},
    "aggressive": {"mbps": 20, "workers": 8, "poll_ms": 320},
}

def network_settings(profile: str) -> dict:
    return NETWORK_PROFILES.get(profile, NETWORK_PROFILES["standard"])

def cached_files(root: Path, job: dict) -> list[Path]:
    cache = job.setdefault("_cache", {})
    cached_root = cache.get("root")
    if cached_root != str(root) or not isinstance(cache.get("files"), list):
        files = [p for p in root.rglob("*") if p.is_file()]
        cache["root"] = str(root)
        cache["files"] = files
        cache["file_set"] = {p.relative_to(root).as_posix() for p in files}
        cache["case_index"] = case_index(cache["file_set"])
    return cache["files"]

def cached_indexes(root: Path, job: dict) -> tuple[list[Path], set[str], dict[str, str]]:
    files = cached_files(root, job)
    cache = job["_cache"]
    return files, cache["file_set"], cache["case_index"]

async def job_timeout_watchdog(job_id: str, timeout_seconds: int) -> None:
    await asyncio.sleep(max(60, int(timeout_seconds)))
    job = jobs.get(job_id)
    if job and job.get("status") not in {"done", "error", "cancelled"}:
        job["_timeout_event"].set()
        job["_cancel_event"].set()
        job["stage_label"] = "Тайм-аут"
        job["stage_detail"] = f"Задача превысила лимит обработки {int(timeout_seconds)//60} мин."
        persist_job(job_id)


async def run_job(job_id: str, root: Path, original_name: str, source_kind: str, source_name: str, wishes: str, priority: list[str], uploaded_bytes: int, output_suffix: str, output_type: str, repair_mode: str="standard", task_mode: str="repair", modification_request: str="", network_profile: str="standard") -> None:
    job=jobs[job_id]
    if job.get("_run_started"):
        return
    job["_run_started"]=True
    job["repair_mode"]=repair_mode; job["task_mode"]=task_mode; job["modification_request"]=modification_request; job["network_profile"]=network_profile; ns=network_settings(network_profile); job["network_mbps"]=ns["mbps"]; job["scan_workers"]=ns["workers"]
    try:
        payload=root/"payload"; payload.mkdir(parents=True,exist_ok=True); source=root/"source"
        stage_start(job,0,"Приём","Проверяем формат, размер и безопасно готовим рабочую копию.")
        if source_kind=="zip": count,unpacked=await asyncio.to_thread(extract_zip,source/"upload.zip",payload)
        elif source_kind=="folder":
            await asyncio.to_thread(shutil.copytree,source,payload,dirs_exist_ok=True); count=sum(1 for p in payload.rglob("*") if p.is_file()); unpacked=sum(p.stat().st_size for p in payload.rglob("*") if p.is_file()); make_progress(job,0,1)
        else:
            src=next(payload.parent.joinpath("source").iterdir()); dst=payload/src.name; await asyncio.to_thread(shutil.copy2,src,dst); count=1; unpacked=dst.stat().st_size; make_progress(job,0,1)
        job.update(source_file_count=count,unpacked_bytes=unpacked,source_kind=source_kind,source_name=source_name,original_name=original_name,output_suffix=output_suffix,output_type=output_type); persist_job(job_id)
        if source_kind in {"zip","folder"} and not await asyncio.to_thread(likely_supported_folder,payload): raise ValueError("MF-422: содержимое не похоже на поддерживаемый BeamNG.drive мод или ресурсный набор.")
        issues=[]
        stage_start(job,1,"Ваш запрос","Разбираем выбранные приоритеты и текстовое пожелание пользователя."); issues.extend(await asyncio.to_thread(scan_request,payload,job,priority,wishes,task_mode)); make_progress(job,1,1)
        stage_start(job,2,"Прицельная проверка","Проверяем выбранные пользователем области до общего скана."); issues.extend(await asyncio.to_thread(scan_focused,payload,job,priority,wishes)); make_progress(job,2,1)
        stage_start(job,3,"Структура","Ищем дубли, странные пути и нарушения структуры."); issues.extend(await asyncio.to_thread(scan_structure,payload,job))
        stage_start(job,4,"Конфигурации","Проверяем JSON, PC, JBeam и текстовые конфигурации."); issues.extend(await asyncio.to_thread(scan_syntax,payload,job))
        stage_start(job,5,"Ресурсы","Сопоставляем внутренние ссылки с реально существующими файлами."); issues.extend(await asyncio.to_thread(scan_resources,payload,job))
        stage_start(job,6,"Материалы","Проверяем текстуры, стекло, NO TEXTURE и материалы света."); issues.extend(await asyncio.to_thread(scan_materials,payload,job)); issues.extend(await asyncio.to_thread(scan_lighting,payload,job))
        stage_start(job,7,"Автомобиль","Проверяем колёса, slotType, JBeam-связи и базовые физические аномалии."); issues.extend(await asyncio.to_thread(scan_vehicle_health,payload,job))
        stage_start(job,8,"Типовые проблемы","После прицельной проверки ищем распространённые ошибки сторонних модов."); issues.extend(await asyncio.to_thread(scan_common_issues,payload,job))
        stage_start(job,9,"Глубокая проверка","Проверяем связанные данные и подозрительные места."); issues.extend(await asyncio.to_thread(scan_deep,payload,job))
        stage_start(job,10,"Изменения","Показываем план ремонта, затем применяем правила по уровню безопасности.")
        preview = await asyncio.to_thread(build_repair_preview, payload, repair_mode, task_mode, modification_request)
        preview["unresolved_before_repair"] = sum(1 for x in issues if x.get("stage") == "resources" and x.get("level") == "warning") if task_mode != "modify" else 0
        job["repair_preview"] = preview
        preview_paths = await asyncio.to_thread(snapshot_for_preview, payload, preview)
        job["_repair_snapshot"] = preview_paths
        persist_job(job_id)
        if task_mode=="modify":
            try:
                save_history_snapshot(payload, root / "history", "repair", job)
            except Exception:
                pass
            repairs=await asyncio.to_thread(apply_modification_request,payload,modification_request,job)
        else: repairs=await asyncio.to_thread(repair_tree,payload,job)
        issues.extend(repairs); fixed=sum(1 for i in repairs if i.get("level")=="fixed")
        stage_start(job,11,"Проверка изменений","Проверяем изменённые файлы сразу после ремонта."); issues.extend(await asyncio.to_thread(verify_tree,payload,job,11))
        stage_start(job,12,"Повторная проверка","Запускаем полный контроль результата после изменений."); issues.extend(await asyncio.to_thread(verify_tree,payload,job,12))
        focus=detect_focus(priority,wishes)
        if is_vehicle_mod(payload):
            inject_modforge_status(payload,job)
            vehicle_status={}
            marker=payload/"modforge_applied.json"
            try: vehicle_status=json.loads(marker.read_text("utf-8")) if marker.exists() else {}
            except Exception: vehicle_status={}
        else: vehicle_status={}

        # Workbench diagnostics are data-only and run against the final working tree.
        inspector = await asyncio.to_thread(build_resource_inspector, payload)
        perf = await asyncio.to_thread(performance_scan, payload, inspector)
        issues.extend([{"level":"error","stage":"resources","category":"Resources","title":"Отсутствующая ссылка","details":f"{x['source']} → {x['reference']}"} for x in inspector.get("missing_references", [])[:1000]])
        issues.extend([{"level":"warning","stage":"structure","category":"Structure","title":"Дубликаты по SHA-256","details":", ".join(x[:8])} for x in inspector.get("duplicates", [])[:500]])
        issues.extend(perf.get("issues", []))
        issues = normalize_issues(issues)
        health = health_from_issues(issues, set(HEALTH_CATEGORIES))
        diffs = collect_diffs(payload, job.get("_repair_snapshot", {}), repairs)
        job["diffs"] = diffs
        job["health"] = health
        job["resource_inspector"] = inspector
        job["performance"] = perf

        # Preserve rollback points. The original source is never overwritten.
        history_root = root / "history"
        stage_name = "mod_lab" if task_mode == "modify" else "repair"
        try:
            save_history_snapshot(payload, history_root, stage_name, job)
        except Exception:
            pass
        stage_start(job,13,"Сборка","Создаём результат с сохранением структуры мода и ModForge-индикатором.")
        if source_kind=="single" and output_type=="same":
            original=next(p for p in payload.iterdir() if p.is_file()); out_name=output_name(source_name or original_name,output_suffix,False); out_path=root/out_name; shutil.copy2(original,out_path); make_progress(job,13,1)
        else:
            out_name=output_name(source_name or original_name,output_suffix,True); out_path=root/out_name; await asyncio.to_thread(package_zip,payload,out_path,job)
        stage_start(job,14,"Финал","Проверяем итоговый файл перед выдачей.")
        verify_output_file(out_path); make_progress(job,14,1)
        report_issues=normalize_issues(issues)
        report={"service":APP_NAME,"app_version":APP_VERSION,"release_id":RELEASE_ID,"beamng_version":BEAMNG_VERSION,"beamng_profile_note":BEAMNG_PROFILE_NOTE,"source_name":source_name or original_name,"source_kind":source_kind,"output_type":output_type,"output_name":out_name,"task_mode":task_mode,"repair_mode":repair_mode,"repair_mode_label":REPAIR_MODES[repair_mode]["label"],"uploaded_bytes":uploaded_bytes,"unpacked_bytes":job.get("unpacked_bytes",0),"artifact_size":out_path.stat().st_size if out_path.exists() else 0,"vehicle_status":vehicle_status,"wishes":wishes,"modification_request":modification_request,"priority":priority,"focus":focus,"site_version":SITE_VERSION,"network_profile":job.get("network_profile","standard"),"network_mbps":job.get("network_mbps",2),"scan_workers":job.get("scan_workers",2),"summary":report_summary(report_issues,count,fixed),"health":health,"repair_preview":preview,"diffs":diffs,"resource_inspector":inspector,"performance":perf,"history":history_listing(job),"security":{"path_traversal_guard":True,"symlink_guard":True,"archive_bomb_guard":True,"archive_data_only":True,"uploaded_code_execution":False,"max_files":MAX_FILES,"max_unpacked_bytes":MAX_UNPACKED,"max_single_file_bytes":MAX_SINGLE_FILE_UNPACKED,"max_path_depth":MAX_PATH_DEPTH,"max_archive_ratio":MAX_ARCHIVE_RATIO,"max_active_jobs_per_client":MAX_ACTIVE_JOBS_PER_CLIENT,"max_active_jobs_global":MAX_ACTIVE_JOBS_GLOBAL,"job_timeout_seconds":JOB_TIMEOUT_SECONDS},"changed_files":[x.get("file") for x in diffs if x.get("status") != "unchanged"],"issues":report_issues,"limitations":["ModForge не запускает BeamNG.drive для живого 3D-рендера.","Физические и визуальные изменения требуют проверки в игре.","ModForge не скачивает и не копирует закрытые игровые ассеты BeamNG."],"download_url":f"/api/jobs/{job_id}/download","report_url":f"/api/jobs/{job_id}/report"}
        report_path=root/"report.json"; report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2),"utf-8")
        job.update(report=report,output=str(out_path),report_path=str(report_path),fixed_archive_name=out_name,download_url=f"/api/jobs/{job_id}/download",report_url=f"/api/jobs/{job_id}/report",status="done",stage_progress=100,progress=100,eta_seconds=0,stage_label="Готово",stage_detail="Финальная проверка завершена. Файл готов к скачиванию.",stage_index=len(STAGES),artifact_size=out_path.stat().st_size,artifact_mtime=out_path.stat().st_mtime); persist_job(job_id)
    except RuntimeError as exc:
        if str(exc)=="__TIMEOUT__": job.update(status="error",stage_label="Тайм-аут",stage_detail=f"Превышен лимит обработки {JOB_TIMEOUT_SECONDS//60} мин.",error="MF-TIMEOUT: превышен лимит обработки.",progress=0,eta_seconds=None)
        elif str(exc)=="__CANCELLED__": job.update(status="cancelled",stage_label="Остановлено",stage_detail="Обработка остановлена пользователем.",progress=0,eta_seconds=None)
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
    return {"ok":True,"service":APP_NAME,"app_version":APP_VERSION,"site_version":SITE_VERSION,"release_id":RELEASE_ID,"beamng_version":BEAMNG_VERSION,"max_upload_bytes":MAX_UPLOAD,"supported_single":sorted(SUPPORTED_SINGLE),"config":{**CONFIG,"email_notifications":bool(SMTP_HOST and SMTP_USER and SMTP_PASSWORD)},"email":{"configured":bool(SMTP_HOST and SMTP_USER and SMTP_PASSWORD),"last_ok":email_state.get("last_ok"),"last_error":email_state.get("last_error")},"stages":[{"key":k,"label":l,"description":d,"weight":w} for k,l,d,w in STAGES]}

@app.post("/api/analyze")
async def analyze(request: Request, source_kind: str=Form("zip"), source_name: str=Form(""), wishes: str=Form(""), priority_json: str=Form("[]"), files: list[UploadFile]=File(...), manifest_json: str=Form("[]"), output_suffix: str=Form("FIXED"), output_type: str=Form("zip"), repair_mode: str=Form("standard"), task_mode: str=Form("repair"), modification_request: str=Form(""), network_profile: str=Form("standard")):
    if source_kind not in {"zip","folder","single"}: raise service_error("MF-415","Поддерживаемые входы: ZIP, папка и отдельные BeamNG-ресурсы.",400)
    if output_type not in {"zip","same"}: raise service_error("MF-415","Для этого режима выбран неподдерживаемый формат выдачи.",400)
    if repair_mode not in REPAIR_MODES: repair_mode="standard"
    if task_mode not in {"repair","modify"}: task_mode="repair"
    if network_profile not in {"standard","balanced","aggressive"}: network_profile="standard"
    cid=request_client_id(request)
    active_global = sum(1 for j in jobs.values() if j.get("status") in {"queued","running","processing","paused","rebuilding","cancelling"})
    active_client = sum(1 for j in jobs.values() if j.get("_client_id") == cid and j.get("status") in {"queued","running","processing","paused","rebuilding","cancelling"})
    if active_global >= MAX_ACTIVE_JOBS_GLOBAL:
        raise service_error("MF-429", "Очередь ModForge заполнена. Повторите запрос позже.", 429)
    if active_client >= MAX_ACTIVE_JOBS_PER_CLIENT:
        raise service_error("MF-429", f"Для одного клиента одновременно разрешено не более {MAX_ACTIVE_JOBS_PER_CLIENT} задач.", 429)
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
        jobs[job_id]={"status":"queued","stage":"queued","stage_index":0,"stage_label":"Файл принят","stage_detail":"Проверяем доступность рабочей задачи…","stage_progress":0,"progress":0,"eta_seconds":None,"created_at":time.time(),"started_at":time.time(),"report":None,"error":None,"fixed_archive_name":None,"download_url":None,"report_url":None,"root":str(root),"output":None,"report_path":None,"source_kind":source_kind,"source_name":final_source_name,"original_name":original_name,"wishes":wishes[:5000],"priority":priority,"uploaded_bytes":total,"output_suffix":output_suffix,"output_type":output_type,"repair_mode":repair_mode,"task_mode":task_mode,"modification_request":modification_request[:5000],"network_profile":network_profile,"network_mbps":network_settings(network_profile)["mbps"],"scan_workers":network_settings(network_profile)["workers"],"_cancel_event":threading.Event(),"_pause_event":threading.Event(),"_timeout_event":threading.Event(),"_client_id":cid,"job_id":job_id}
        persist_job(job_id)
        asyncio.create_task(job_timeout_watchdog(job_id, JOB_TIMEOUT_SECONDS))
        asyncio.create_task(run_job(job_id,root,original_name,source_kind,final_source_name,wishes[:5000],priority,total,output_suffix,output_type,repair_mode,task_mode,modification_request[:5000],network_profile))
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
    persist_job(job_id)
    return {"ok":True,"paused":job["_pause_event"].is_set()}

@app.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id:str):
    job=jobs.get(job_id)
    if not job or job.get("status") in {"done","error","cancelled"}: raise service_error("MF-404","Задание уже завершено.",404)
    job["_cancel_event"].set(); job["_pause_event"].clear(); job["status"]="cancelling"; persist_job(job_id); return {"ok":True}

@app.post("/api/jobs/{job_id}/restart")
async def restart_job(job_id: str):
    old = jobs.get(job_id)
    if not old:
        raise service_error("MF-404", "Сохранённое задание больше не найдено.", 404)
    old_root = Path(old.get("root") or "")
    old_source = old_root / "source"
    if not old_source.exists():
        raise service_error("MF-404", "Исходные данные задания больше недоступны для перезапуска.", 404)
    source_kind = old.get("source_kind", "zip")
    source_name = old.get("source_name") or old.get("original_name") or "beamng_mod"
    original_name = old.get("original_name") or source_name
    wishes = str(old.get("wishes") or "")[:5000]
    priority = old.get("priority") if isinstance(old.get("priority"), list) else []
    output_suffix = str(old.get("output_suffix") or "FIXED")
    output_type = str(old.get("output_type") or "zip")
    repair_mode = str(old.get("repair_mode") or "standard")
    if repair_mode not in REPAIR_MODES: repair_mode="standard"
    task_mode = str(old.get("task_mode") or "repair")
    if task_mode not in {"repair","modify"}: task_mode="repair"
    modification_request = str(old.get("modification_request") or "")
    new_id = uuid.uuid4().hex
    root = WORK_ROOT / new_id
    source = root / "source"
    root.mkdir(parents=True, exist_ok=True)
    try:
        await asyncio.to_thread(shutil.copytree, old_source, source, dirs_exist_ok=True)
        uploaded_bytes = int(old.get("uploaded_bytes") or 0)
        jobs[new_id] = {
            "status":"queued", "stage":"queued", "stage_index":0, "stage_label":"Перезапуск принят",
            "stage_detail":"Используем сохранённую копию исходных данных — повторная загрузка из браузера не нужна.",
            "stage_progress":0, "progress":0, "eta_seconds":None, "created_at":time.time(), "started_at":time.time(),
            "report":None, "error":None, "fixed_archive_name":None, "download_url":None, "report_url":None,
            "root":str(root), "output":None, "report_path":None, "source_kind":source_kind, "source_name":source_name,
            "original_name":original_name, "wishes":wishes, "priority":priority, "uploaded_bytes":uploaded_bytes,
            "output_suffix":output_suffix, "output_type":output_type, "repair_mode":repair_mode, "restarted_from":job_id,
            "_cancel_event":threading.Event(), "_pause_event":threading.Event(), "_timeout_event":threading.Event(), "_client_id":old.get("_client_id"), "job_id":new_id, "task_mode":str(old.get("task_mode") or "repair"), "modification_request":modification_request, "network_profile":str(old.get("network_profile") or "standard"), "network_mbps":{"standard":2,"balanced":5,"aggressive":20}.get(str(old.get("network_profile") or "standard"),2)
        }
        persist_job(new_id)
        asyncio.create_task(job_timeout_watchdog(new_id, JOB_TIMEOUT_SECONDS))
        asyncio.create_task(run_job(new_id, root, original_name, source_kind, source_name, wishes, priority, uploaded_bytes, output_suffix, output_type, repair_mode, task_mode, modification_request, str(old.get("network_profile") or "standard")))
        return {"ok":True, "job_id":new_id, "status":"queued", "restarted_from":job_id}
    except Exception as exc:
        shutil.rmtree(root, ignore_errors=True)
        raise service_error("MF-503", f"Не удалось перезапустить сохранённую задачу: {exc}", 503)

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
    if not job or job.get("status") not in {"done", "rebuilding"}:
        raise service_error("MF-404", "Готовый файл ещё недоступен.", 404)
    try:
        path = await asyncio.to_thread(ensure_output, job_id)
        verify_output_file(path)
    except FileNotFoundError as exc:
        raise service_error("MF-404", str(exc), 404)
    except Exception as exc:
        raise service_error("MF-503", f"Не удалось восстановить готовый файл: {exc}", 503)
    return JSONResponse(status_code=200, content={}, headers={"X-ModForge-Artifact": path.name, "X-ModForge-Artifact-Size": str(path.stat().st_size), "Cache-Control": "no-store"})

@app.get("/api/jobs/{job_id}/download")
async def download(job_id:str):
    job=jobs.get(job_id)
    if not job or job.get("status") not in {"done", "rebuilding"}: raise service_error("MF-404","Готовый файл ещё недоступен.",404)
    try:
        path = await asyncio.to_thread(ensure_output, job_id)
        verify_output_file(path)
    except FileNotFoundError as exc:
        raise service_error("MF-404", str(exc), 404)
    except Exception as exc:
        raise service_error("MF-503", f"Не удалось подготовить файл к выдаче: {exc}", 503)
    filename=path.name; media="application/zip" if path.suffix.lower()==".zip" else "application/octet-stream"
    safe_filename=filename.replace('"','_')
    return FileResponse(path,media_type=media,headers={"Content-Disposition":f"attachment; filename=\"{safe_filename}\"; filename*=UTF-8''{quote(filename)}", "Cache-Control":"no-store"})

@app.get("/api/jobs/{job_id}/report")
async def report_download(job_id:str):
    job=jobs.get(job_id)
    if not job or job.get("status")!="done": raise service_error("MF-404","Отчёт ещё недоступен.",404)
    path=Path(job["report_path"]); filename=f"{Path(job['fixed_archive_name']).stem}_report.json"
    return FileResponse(path,media_type="application/json",headers={"Content-Disposition":f"attachment; filename=\"{filename}\"; filename*=UTF-8''{quote(filename)}"})


@app.get("/api/repair-rules")
async def repair_rules():
    return {"ok": True, "version": RELEASE_ID, "rules": REPAIR_RULES}


@app.get("/api/jobs/{job_id}/health")
async def job_health(job_id: str):
    job = jobs.get(job_id)
    if not job: raise service_error("MF-404", "Задание не найдено.", 404)
    report = job.get("report") or {}
    return {"ok": True, "health": report.get("health") or job.get("health") or {}}


@app.get("/api/jobs/{job_id}/repair-preview")
async def job_repair_preview(job_id: str):
    job = jobs.get(job_id)
    if not job: raise service_error("MF-404", "Задание не найдено.", 404)
    preview = job.get("repair_preview") or (job.get("report") or {}).get("repair_preview")
    if not preview: raise service_error("MF-409", "План ремонта ещё не сформирован.", 409)
    return {"ok": True, "preview": preview}


@app.get("/api/jobs/{job_id}/diff")
async def job_diff(job_id: str):
    job = jobs.get(job_id)
    if not job: raise service_error("MF-404", "Задание не найдено.", 404)
    return {"ok": True, "diffs": (job.get("report") or {}).get("diffs") or job.get("diffs") or []}


@app.get("/api/jobs/{job_id}/inspector")
async def job_inspector(job_id: str):
    job = jobs.get(job_id)
    if not job: raise service_error("MF-404", "Задание не найдено.", 404)
    report = job.get("report") or {}
    inspector = report.get("resource_inspector") or job.get("resource_inspector")
    if inspector is None: raise service_error("MF-409", "Resource Inspector ещё не сформирован.", 409)
    return {"ok": True, "inspector": inspector}


@app.post("/api/jobs/{job_id}/doctor")
async def job_doctor(job_id: str, request: Request):
    job = jobs.get(job_id)
    if not job: raise service_error("MF-404", "Задание не найдено.", 404)
    try: data = await request.json()
    except Exception: data = {}
    query = str(data.get("query") or "").strip()[:1200]
    if len(query) < 2: raise service_error("MF-422", "Опишите проблему хотя бы несколькими словами.", 400)
    return {"ok": True, "doctor": mod_doctor(job, query)}


@app.get("/api/jobs/{job_id}/history")
async def job_history(job_id: str):
    job = jobs.get(job_id)
    if not job: raise service_error("MF-404", "Задание не найдено.", 404)
    return {"ok": True, "history": history_listing(job)}


@app.post("/api/jobs/{job_id}/prepare-release")
async def prepare_release(job_id: str):
    job = jobs.get(job_id)
    if not job: raise service_error("MF-404", "Задание не найдено.", 404)
    if job.get("status") != "done": raise service_error("MF-409", "PREPARE FOR RELEASE доступен после завершения основной проверки.", 409)
    root = Path(job["root"]); payload = root / "payload"
    if not payload.exists(): raise service_error("MF-404", "Рабочая копия мода больше недоступна.", 404)
    job["status"] = "processing"; job["stage_label"] = "PREPARE FOR RELEASE"; job["stage_detail"] = "Сохраняем repair snapshot, удаляем только безопасный мусор и повторно проверяем мод."; persist_job(job_id)
    try:
        history_root = root / "history"
        if not (history_root / "repair.zip").exists():
            await asyncio.to_thread(save_history_snapshot, payload, history_root, "repair", job)
        removed = await asyncio.to_thread(clean_tree_safe, payload)
        job["release_removed_files"] = removed
        release_issues = []
        release_issues.extend(await asyncio.to_thread(scan_structure, payload, job))
        release_issues.extend(await asyncio.to_thread(scan_syntax, payload, job))
        release_issues.extend(await asyncio.to_thread(scan_resources, payload, job))
        inspector = await asyncio.to_thread(build_resource_inspector, payload)
        release_issues.extend([{"level":"error","stage":"resources","category":"Resources","title":"Отсутствующая ссылка после очистки","details":f"{x['source']} → {x['reference']}"} for x in inspector.get("missing_references", [])[:1000]])
        perf = await asyncio.to_thread(performance_scan, payload, inspector)
        release_issues.extend(perf.get("issues", []))
        normalized = normalize_issues(release_issues)
        health = health_from_issues(normalized, {"Structure","Syntax","Resources","Materials","Vehicle","Configs","Performance"})
        await asyncio.to_thread(save_history_snapshot, payload, history_root, "optimized", job)
        release_name = output_name(job.get("source_name") or job.get("original_name") or "beamng_mod", "RELEASE", True)
        release_path = root / release_name
        await asyncio.to_thread(package_zip, payload, release_path, job)
        verify_output_file(release_path)
        report = dict(job.get("report") or {})
        report.update({"release_check": {"removed_safe_files": removed, "rechecked": True, "health": health}, "health": health, "issues": normalize_issues((report.get("issues") or []) + normalized), "output_name": release_name, "artifact_size": release_path.stat().st_size, "history": history_listing(job)})
        report["summary"] = report_summary(report["issues"], int(job.get("source_file_count") or 0), int(report.get("summary", {}).get("fixed") or 0))
        report["download_url"] = f"/api/jobs/{job_id}/download"; report["report_url"] = f"/api/jobs/{job_id}/report"
        job.update(report=report, health=health, output=str(release_path), fixed_archive_name=release_name, artifact_size=release_path.stat().st_size, status="done", stage_label="Release готов", stage_detail="Очистка и повторная проверка завершены. Готов Release ZIP.", progress=100, stage_progress=100, eta_seconds=0)
        (root / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
        persist_job(job_id)
        return {"ok": True, "release": {"name": release_name, "size": release_path.stat().st_size, "removed": removed, "health": health}}
    except Exception as exc:
        job.update(status="done", stage_label="PREPARE FOR RELEASE остановлен", stage_detail=str(exc))
        persist_job(job_id)
        raise service_error("MF-503", f"Не удалось подготовить Release: {exc}", 503)


@app.post("/api/jobs/{job_id}/rollback/{stage}")
async def job_rollback(job_id: str, stage: str):
    job = jobs.get(job_id)
    if not job: raise service_error("MF-404", "Задание не найдено.", 404)
    if job.get("status") != "done": raise service_error("MF-409", "Rollback доступен после завершения задачи.", 409)
    if stage not in {"original", "repair", "optimized", "mod_lab"}: raise service_error("MF-422", "Неизвестная точка истории.", 400)
    root = Path(job["root"]); payload = root / "payload"
    try:
        shutil.rmtree(payload, ignore_errors=True); payload.mkdir(parents=True, exist_ok=True)
        if stage == "original":
            source = root / "source"
            if job.get("source_kind") == "zip":
                await asyncio.to_thread(extract_zip, source / "upload.zip", payload)
            elif job.get("source_kind") == "folder":
                await asyncio.to_thread(shutil.copytree, source, payload, dirs_exist_ok=True)
            else:
                items = [p for p in source.iterdir() if p.is_file()]
                if len(items) != 1: raise ValueError("Исходный отдельный файл не удалось восстановить однозначно.")
                shutil.copy2(items[0], payload / items[0].name)
        else:
            snap = root / "history" / f"{stage}.zip"
            if not snap.exists(): raise FileNotFoundError(f"Снапшот {stage} отсутствует.")
            await asyncio.to_thread(extract_zip, snap, payload)
        job["status"] = "processing"; job["stage_label"] = f"Rollback → {stage}"; persist_job(job_id)
        inspector = await asyncio.to_thread(build_resource_inspector, payload)
        issues = await asyncio.to_thread(scan_syntax, payload, job) + await asyncio.to_thread(scan_resources, payload, job)
        issues = normalize_issues(issues)
        health = health_from_issues(issues, set(HEALTH_CATEGORIES))
        report = dict(job.get("report") or {})
        report.update({"rollback": {"stage": stage, "restored_at": int(time.time() * 1000)}, "health": health, "issues": issues, "resource_inspector": inspector, "output_name": output_name(job.get("source_name") or job.get("original_name") or "beamng_mod", f"ROLLBACK_{stage.upper()}", True)})
        out_path = root / report["output_name"]
        await asyncio.to_thread(package_zip, payload, out_path, job, stage != "original"); verify_output_file(out_path)
        report["artifact_size"] = out_path.stat().st_size; report["download_url"] = f"/api/jobs/{job_id}/download"; report["report_url"] = f"/api/jobs/{job_id}/report"; report["summary"] = report_summary(issues, int(job.get("source_file_count") or 0), 0)
        job.update(report=report, health=health, output=str(out_path), fixed_archive_name=out_path.name, artifact_size=out_path.stat().st_size, status="done", stage_label="Готово", stage_detail=f"Rollback → {stage} завершён.", progress=100, stage_progress=100, eta_seconds=0)
        (root / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8"); persist_job(job_id)
        return {"ok": True, "stage": stage, "name": out_path.name, "health": health}
    except Exception as exc:
        job.update(status="done", stage_label="Rollback остановлен", stage_detail=str(exc)); persist_job(job_id)
        raise service_error("MF-503", f"Rollback не выполнен: {exc}", 503)


@app.post("/api/compare")
async def compare_mods(files: list[UploadFile] = File(...)):
    if len(files) != 2: raise service_error("MF-415", "Для сравнения нужны ровно два ZIP-файла.", 400)
    tmp = WORK_ROOT / f"compare_{uuid.uuid4().hex}"; tmp.mkdir(parents=True, exist_ok=True)
    try:
        paths=[]
        for idx, upload in enumerate(files):
            name=Path(upload.filename or f"mod_{idx}.zip").name
            if Path(name).suffix.lower() != ".zip": raise service_error("MF-415", "Оба входа должны быть ZIP.", 400)
            path=tmp/f"{idx}.zip"; total=0
            with path.open("wb") as fh:
                while True:
                    chunk=await upload.read(8*1024*1024)
                    if not chunk: break
                    total += len(chunk)
                    if total > MAX_COMPARE_UPLOAD: raise service_error("MF-413", "ZIP для сравнения превышает лимит 1 ГБ на архив.", 413)
                    fh.write(chunk)
            await upload.close(); paths.append(path)
        result = await asyncio.to_thread(compare_zip_paths, paths[0], paths[1])
        return {"ok": True, "compare": result}
    except HTTPException: raise
    except (BadZipFile, ValueError) as exc: raise service_error("MF-422", str(exc), 400)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@app.get("/api/feedback")
async def feedback_list():
    with feedback_lock:
        items = load_feedback()
        public = []
        for item in reversed(items):
            cleaned = clean_feedback_item(item)
            cleaned["reports"] = min(int(cleaned.get("reports") or 0), 99)
            public.append(cleaned)
        return {"items": public[:200], "email_notifications": bool(SMTP_HOST and SMTP_USER and SMTP_PASSWORD), "admin_configured": bool(ADMIN_KEY)}

@app.post("/api/feedback")
async def feedback_create(request: Request):
    try: data = await request.json()
    except Exception: data = {}
    name = str(data.get("name") or "Гость").strip()[:40] or "Гость"
    message = str(data.get("message") or "").strip()[:1200]
    email = str(data.get("email") or "").strip()[:160]
    if len(message) < 2: raise service_error("MF-422", "Сообщение слишком короткое.", 400)
    if email and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise service_error("MF-422", "Проверьте email.", 400)
    item = {"id": uuid.uuid4().hex[:12], "name": name, "email": email, "message": message, "created_at": int(time.time()*1000), "status": "открыто", "replies": [], "reports": 0}
    with feedback_lock:
        items = load_feedback(); items.append(item); save_feedback(items)
    schedule_email(send_owner_email, f"ModForge · новая обратная связь #{item['id']}",
                   f"Новое сообщение в ModForge.\n\nID: {item['id']}\nИмя: {name}\nEmail: {email or 'не указан'}\n\n{message}\n\nОтветить на это письмо можно обычной кнопкой Reply: если email указан, он стоит в поле Reply-To.", email)
    return {"ok": True, "item": clean_feedback_item(item)}

@app.post("/api/feedback/{feedback_id}/reply")
async def feedback_reply(feedback_id: str, request: Request):
    try: data = await request.json()
    except Exception: data = {}
    name = str(data.get("name") or ("ModForge" if is_admin(request) else "Гость")).strip()[:40] or "Гость"
    message = str(data.get("message") or "").strip()[:1200]
    author = is_admin(request)
    if len(message) < 2: raise service_error("MF-422", "Ответ слишком короткий.", 400)
    with feedback_lock:
        items = load_feedback(); item = next((x for x in items if x.get("id") == feedback_id), None)
        if not item: raise service_error("MF-404", "Сообщение не найдено.", 404)
        reply = {"id": uuid.uuid4().hex[:12], "name": name, "message": message, "created_at": int(time.time()*1000), "author": author}
        item.setdefault("replies", []).append(reply)
        item["replies"] = item["replies"][-40:]
        if author:
            item["status"] = "ответ дан"
        save_feedback(items)
        clean = clean_feedback_item(item)
    if author and item.get("email"):
        schedule_email(send_user_email, item["email"], f"ModForge · ответ на сообщение #{feedback_id}",
                       f"На ваше сообщение в ModForge ответил автор.\n\nВаше сообщение:\n{item.get('message','')}\n\nОтвет:\n{message}\n")
    if author:
        schedule_email(send_owner_email, f"ModForge · опубликован ответ #{feedback_id}",
                       f"Ответ опубликован.\n\nID: {feedback_id}\nАвтор: {name}\n\n{message}\n")
    return {"ok": True, "item": clean}

@app.post("/api/feedback/{feedback_id}/report")
async def feedback_report(feedback_id: str, request: Request):
    try: data = await request.json()
    except Exception: data = {}
    reason = str(data.get("reason") or "Пользователь пожаловался на сообщение").strip()[:400]
    with feedback_lock:
        items = load_feedback(); item = next((x for x in items if x.get("id") == feedback_id), None)
        if not item: raise service_error("MF-404", "Сообщение не найдено.", 404)
        item["reports"] = int(item.get("reports") or 0) + 1
        item.setdefault("report_log", []).append({"id": uuid.uuid4().hex[:12], "reason": reason, "created_at": int(time.time()*1000)})
        item["report_log"] = item["report_log"][-50:]
        save_feedback(items)
        reports_count = item["reports"]
    schedule_email(send_owner_email, f"ModForge · жалоба #{feedback_id}",
                   f"Поступила жалоба на сообщение ModForge.\n\nID сообщения: {feedback_id}\nКоличество жалоб: {reports_count}\nПричина: {reason}\n\nСообщение:\n{item.get('message','')}\nАвтор: {item.get('name','Гость')}\n")
    return {"ok": True, "reports": reports_count}

@app.get("/api/feedback/admin/email-status")
async def feedback_admin_email_status(request: Request):
    if not is_admin(request):
        raise service_error("MF-403", "Требуется режим автора.", 403)
    return {
        "ok": True,
        "configured": bool(SMTP_HOST and SMTP_USER and SMTP_PASSWORD),
        "host": SMTP_HOST or None,
        "port": SMTP_PORT,
        "tls": SMTP_TLS,
        "ssl": SMTP_SSL,
        "from": SMTP_FROM or OWNER_EMAIL,
        "owner": OWNER_EMAIL,
        "last_ok": email_state.get("last_ok"),
        "last_error": email_state.get("last_error"),
        "last_sent_at": email_state.get("last_sent_at"),
    }


@app.post("/api/feedback/admin/test-email")
async def feedback_admin_test_email(request: Request):
    if not is_admin(request):
        raise service_error("MF-403", "Требуется режим автора.", 403)
    if not (SMTP_HOST and SMTP_USER and SMTP_PASSWORD):
        raise service_error("MF-503", "SMTP не настроен. Задайте переменные окружения MODFORGE_SMTP_HOST, MODFORGE_SMTP_USER и MODFORGE_SMTP_PASSWORD.", 503)
    schedule_email(send_owner_email, "ModForge · тест почты", "Это тестовое письмо ModForge. Если оно пришло, уведомления обратной связи настроены корректно.")
    return {"ok": True, "message": "Тестовая отправка запущена."}


@app.post("/api/feedback/admin/login")
async def feedback_admin_login(request: Request):
    if not ADMIN_KEY:
        raise service_error("MF-503", "Режим автора не настроен: задайте MODFORGE_ADMIN_KEY.", 503)
    if not is_admin(request):
        raise service_error("MF-403", "Неверный ключ автора.", 403)
    return {"ok": True, "role": "author"}

@app.get("/robots.txt")
async def robots(): return PlainTextResponse("User-agent: *\nAllow: /\n",media_type="text/plain")

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    detail=exc.detail
    if isinstance(detail,dict) and "code" in detail: return JSONResponse(status_code=exc.status_code,content={"ok":False,"code":detail["code"],"message":detail.get("message","")})
    return JSONResponse(status_code=exc.status_code,content={"ok":False,"code":f"MF-{exc.status_code}","message":str(detail)})
