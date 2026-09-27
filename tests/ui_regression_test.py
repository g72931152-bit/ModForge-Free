from __future__ import annotations

import asyncio
import json
from pathlib import Path

import main

ROOT = Path(__file__).resolve().parents[1]


def test_health_exposes_only_public_bootstrap_state() -> None:
    data = asyncio.run(main.health())
    assert data["state_epoch"] == main.STATE_EPOCH
    assert "config" in data
    encoded = json.dumps(data, ensure_ascii=False)
    assert "SMTP_PASSWORD" not in encoded
    assert "ADMIN_KEY" not in encoded
    assert "owner_email" not in encoded


def test_bootstrap_has_reset_detection_contract() -> None:
    data = asyncio.run(main.bootstrap())
    assert data["ok"] is True
    assert data["state_epoch"] == main.STATE_EPOCH
    assert set(data) == {"ok", "service", "release_id", "site_version", "state_epoch"}


def test_frontend_has_session_history_and_error_catalog() -> None:
    html = (ROOT / "index.html").read_text("utf-8")
    js = (ROOT / "assets" / "app.js").read_text("utf-8")
    css = (ROOT / "assets" / "styles.css").read_text("utf-8")
    assert 'id="historyTop"' in html
    assert 'id="historyDrawer"' in html
    assert 'mf_session_history' in js
    for code in ("MF-528", "MF-503", "MF-TIMEOUT", "MF-409", "MF-413", "MF-429", "MF-CANCELLED"):
        assert code in js
    assert "critical-error-active" in js
    assert ".diagnostic-error.critical" in css
    assert ".history-card" in css


def test_offline_fallback_and_critical_logo_are_shipped() -> None:
    offline = ROOT / "offline.html"
    cracked = ROOT / "assets" / "logo-critical.svg"
    sw = ROOT / "sw.js"
    manifest = ROOT / "manifest.json"
    assert offline.exists() and cracked.exists() and sw.exists() and manifest.exists()
    assert "/sw.js" in (ROOT / "index.html").read_text("utf-8")
    assert "MF-503" in offline.read_text("utf-8")
    assert "logo-critical.svg" in sw.read_text("utf-8")
    assert json.loads(manifest.read_text("utf-8"))["short_name"] == "ModForge"


def test_frontend_uses_distinct_error_visuals_and_safe_retry_text() -> None:
    js = (ROOT / "assets" / "app.js").read_text("utf-8")
    assert "Восстановление данных" in js
    assert "Сайт не отвечает" in js
    assert "Данные и прошлые сессии были сброшены" in js
    assert "Не отправляйте один и тот же запрос многократно" in js
    assert "Локальные сессии останутся на месте" in js


def test_browser_navigation_errors_get_diagnostic_html() -> None:
    class Url:
        path = "/missing-page"
    class Req:
        url = Url()
        method = "GET"
    from fastapi import HTTPException
    response = asyncio.run(main.http_exception_handler(Req(), HTTPException(404, detail={"code": "MF-404", "message": "Страница не найдена."})))
    assert response.status_code == 404
    assert "MF-404" in response.body.decode("utf-8")
    assert "Страница не найдена." in response.body.decode("utf-8")
    starlette_response = asyncio.run(main.starlette_http_exception_handler(Req(), main.StarletteHTTPException(404, detail="Not Found")))
    assert starlette_response.status_code == 404
    assert "MF-404" in starlette_response.body.decode("utf-8")


def test_offline_service_worker_and_manifest_routes_are_served() -> None:
    assert "MF-503" in asyncio.run(main.offline_page()).body.decode("utf-8")
    assert "serviceWorker" in asyncio.run(main.service_worker()).body.decode("utf-8") or "self.addEventListener" in asyncio.run(main.service_worker()).body.decode("utf-8")
    assert json.loads(asyncio.run(main.manifest()).body.decode("utf-8"))["name"] == "ModForge"
