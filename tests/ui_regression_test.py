from __future__ import annotations

import asyncio
import json
import tempfile
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
    assert data["config"]["large_file_budget_share"] == 0.5
    assert data["config"]["repair_modes"]["aggressive"]["check_blocks"] == 15
    assert data["config"]["processing_speed_profiles"]["aggressive"]["large_file_workers"] == 2


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


def test_v095_processing_speed_is_not_a_network_mb_budget() -> None:
    assert main.SITE_VERSION == "0.57-A"
    assert main.processing_speed_settings("standard")["total_workers"] == 2
    assert main.processing_speed_settings("balanced")["total_workers"] == 4
    assert main.processing_speed_settings("aggressive")["total_workers"] == 4
    assert all(main.processing_speed_settings(x)["large_file_workers"] * 2 == main.processing_speed_settings(x)["total_workers"] for x in ("standard","balanced","aggressive"))
    assert all(main.processing_speed_settings(x)["network_intensity"] in {"низкая","контролируемая","обычная","повышенная","высокая"} for x in ("standard","balanced","aggressive"))
    assert "network_profiles" not in main.DEFAULT_CONFIG
    assert "processing_speed_profiles" in main.DEFAULT_CONFIG


def test_v063_repair_modes_expose_7_11_15_logical_blocks() -> None:
    assert main.REPAIR_MODE_BLOCKS["standard"]["count"] == 7
    assert main.REPAIR_MODE_BLOCKS["medium"]["count"] == 11
    assert main.REPAIR_MODE_BLOCKS["aggressive"]["count"] == 15
    js=(ROOT/"assets"/"app.js").read_text("utf-8")
    assert "REPAIR_BLOCK_RANGES" in js
    assert "standard: [[1],[2],[3,4]" in js


def test_v063_large_files_get_sequential_blocks_from_16() -> None:
    root=Path(tempfile.mkdtemp(prefix="modforge-large-blocks-"))
    try:
        for i in range(3): (root/f"big{i}.bin").write_bytes(b"x")
        job={"job_id":"blocks","processing_workers":4,"large_file_workers":2,"_cancel_event":__import__('threading').Event(),"_pause_event":__import__('threading').Event(),"_timeout_event":__import__('threading').Event(),"status":"running"}
        main.jobs["blocks"]=job
        original=main.review_large_file
        main.review_large_file=lambda path,j:{"sha256":"x","bytes_read":1,"signals":[]}
        items=[{"file":f"big{i}.bin","size":1,"status":"queued"} for i in range(3)]
        asyncio.run(main.run_large_file_task("blocks",root,items))
        assert [x["block_no"] for x in items] == [16,17,18]
        assert job["large_file_budget_share"] == 0.5
    finally:
        main.review_large_file=original
        main.jobs.pop("blocks",None)
        import shutil; shutil.rmtree(root,ignore_errors=True)


def test_v063_analyze_accepts_processing_speed_as_canonical_setting() -> None:
    from fastapi.testclient import TestClient
    async def noop(*_args, **_kwargs): return None
    old_run, old_watch = main.run_job, main.job_timeout_watchdog
    main.run_job, main.job_timeout_watchdog = noop, noop
    client=TestClient(main.app)
    old_jobs=dict(main.jobs); old_global=main.job_reservations_global; old_client=dict(main.job_reservations_client)
    try:
        main.jobs.clear(); main.job_reservations_global=0; main.job_reservations_client.clear()
        r=client.post('/api/analyze', data={'source_kind':'single','source_name':'x.jbeam','output_type':'same','repair_mode':'aggressive','task_mode':'repair','processing_speed':'aggressive','manifest_json':'[]','priority_json':'[]','problem_hints_json':'[]','wishes':'','modification_request':'','output_suffix':'FIXED','asset_type':''}, files={'files':('x.jbeam', b'{"spring": 1}', 'application/octet-stream')})
        assert r.status_code==200, r.text
        jid=r.json()['job_id']
        job=main.public_job(main.jobs[jid])
        assert job['processing_speed']=='aggressive'
        assert job['processing_workers']==4
        assert job['large_file_budget_share']==0.5
        assert job['check_blocks']['count']==15
    finally:
        for jid,job in list(main.jobs.items()):
            if jid not in old_jobs and job.get('root'):
                import shutil; shutil.rmtree(job['root'],ignore_errors=True)
        main.jobs.clear(); main.jobs.update(old_jobs); main.job_reservations_global=old_global; main.job_reservations_client.clear(); main.job_reservations_client.update(old_client)
        main.run_job, main.job_timeout_watchdog = old_run, old_watch


def test_v095_single_release_marker_and_no_footer_duplicate_version() -> None:
    html = (ROOT / "index.html").read_text("utf-8")
    assert "ModForge · V1 (0.57-A) Global Update" in html
    assert 'id="versionBadge">V1 · 0.57-A · GLOBAL UPDATE</span>' in html
    footer = html.split('<footer class="footer">', 1)[1].split('</footer>', 1)[0]
    assert "0.52" not in footer
    assert "0.43" not in html


def test_v095_theme_favicon_and_issue_catalog_contract() -> None:
    js = (ROOT / "assets" / "app.js").read_text("utf-8")
    css = (ROOT / "assets" / "styles.css").read_text("utf-8")
    html = (ROOT / "index.html").read_text("utf-8")
    assert "setThemeFavicon" in js
    assert "function setPickerVisual" in js
    assert "problemOther" in js
    assert js.count("lighting_direction") >= 1
    assert "data-theme-favicon" not in js
    assert "modforge-shell-v057a" in (ROOT / "sw.js").read_text("utf-8")
    assert '/assets/styles.css?v=057a' in html
    assert '/assets/app.js?v=057a' in html
    assert 'var(--accent)' in css
    assert 'backdrop-filter: none !important' in css


def test_v095_polling_has_no_frontend_hard_timeout_and_deduplicates_polls() -> None:
    js = (ROOT / "assets" / "app.js").read_text("utf-8")
    assert "__timeoutMs: null" in js
    assert "pollInFlight" in js
    assert "if (state.pollInFlight) return;" in js
    assert "state.pollInFlight = false" in js
    assert "stage-connection-note" in js
    assert "Связь с backend нестабильна" in js


def test_v063_files_button_uses_current_status_snapshot() -> None:
    js = (ROOT / "assets" / "app.js").read_text("utf-8")
    assert "state.lastStatusJob.current_files" in js
    assert "Что сейчас проверяется" in js
    assert "Список файлов скопирован." in js
    assert "filesRefresh" in js


def test_v063_stage_status_icons_and_pointer_aura_are_present() -> None:
    js = (ROOT / "assets" / "app.js").read_text("utf-8")
    css = (ROOT / "assets" / "styles.css").read_text("utf-8")
    assert "stage-state-icon" in js
    assert ".stage-state-icon.checking" in css
    assert ".stage-state-icon.done" in css
    assert "@keyframes stageSpin" in css
    assert "initPointerAura" in js
    assert "--pointer-x" in css and "--pointer-y" in css


def test_v063_error_avatars_exist_and_are_used() -> None:
    js = (ROOT / "assets" / "app.js").read_text("utf-8")
    assert (ROOT / "assets" / "error-avatar.png").exists()
    assert (ROOT / "assets" / "error-avatar-critical.png").exists()
    assert "error-avatar.png" in js
    assert "error-avatar-critical.png" in js
    assert "background:transparent" in (ROOT / "assets" / "styles.css").read_text("utf-8")


def test_v063_files_endpoint_exposes_current_stage_not_full_working_copy(tmp_path: Path) -> None:
    job_id = "ui-current-files"
    main.jobs[job_id] = {
        "job_id": job_id,
        "status": "running",
        "stage_label": "Приём",
        "current_files": ["vehicles/test/a.jbeam", "common/a.png"],
        "current_files_truncated": False,
        "payload_files": ["vehicles/test/a.jbeam", "common/a.png", "extra/readme.txt"],
    }
    try:
        d = asyncio.run(main.job_files(job_id))
        assert d["scope"] == "current_stage"
        assert d["stage"] == "Приём"
        assert d["files"] == ["vehicles/test/a.jbeam", "common/a.png"]
        assert "extra/readme.txt" not in d["files"]
    finally:
        main.jobs.pop(job_id, None)


def test_v063_large_file_block_sequence_remains_16_17_18() -> None:
    root = Path(tempfile.mkdtemp(prefix="modforge-large-blocks-044-"))
    try:
        for i in range(3):
            (root / f"big{i}.bin").write_bytes(b"x")
        import threading
        job = {
            "job_id": "blocks-044",
            "processing_workers": 4,
            "large_file_workers": 2,
            "_cancel_event": threading.Event(),
            "_pause_event": threading.Event(),
            "_timeout_event": threading.Event(),
            "status": "running",
        }
        main.jobs["blocks-044"] = job
        original = main.review_large_file
        main.review_large_file = lambda path, j: {"sha256": "x", "bytes_read": 1, "signals": []}
        items = [{"file": f"big{i}.bin", "size": 1, "status": "queued"} for i in range(3)]
        asyncio.run(main.run_large_file_task("blocks-044", root, items))
        assert [x["block_no"] for x in items] == [16, 17, 18]
    finally:
        main.review_large_file = original
        main.jobs.pop("blocks-044", None)
        import shutil
        shutil.rmtree(root, ignore_errors=True)


def test_v063_pause_button_preserves_paused_state_after_request() -> None:
    js = (ROOT / "assets" / "app.js").read_text("utf-8")
    assert "state.paused = !!d.paused" in js
    assert "state.paused ? 'Продолжить' : 'Пауза'" in js


def test_v063_connection_warning_is_visible_only_inside_open_stage_detail() -> None:
    css = (ROOT / "assets" / "styles.css").read_text("utf-8")
    assert ".stage:not(.open) .stage-connection-note" in css
    assert ".stage.open .stage-connection-note:not([hidden])" in css


def test_v063_http_error_page_uses_uploaded_avatar_by_severity() -> None:
    from fastapi import HTTPException
    class Url:
        path = "/missing-page"
    class Req:
        url = Url()
        method = "GET"
    normal = asyncio.run(main.http_exception_handler(Req(), HTTPException(404, detail={"code": "MF-404", "message": "Страница не найдена."})))
    critical = asyncio.run(main.http_exception_handler(Req(), HTTPException(500, detail={"code": "MF-500", "message": "Ошибка."})))
    nbody = normal.body.decode("utf-8")
    cbody = critical.body.decode("utf-8")
    assert "/assets/error-avatar.png" in nbody
    assert "/assets/error-avatar-critical.png" not in nbody
    assert "/assets/error-avatar-critical.png" in cbody
    assert 'class="critical"' in cbody


def test_v063_service_worker_cache_uses_current_assets_and_error_avatars() -> None:
    sw = (ROOT / "sw.js").read_text("utf-8")
    assert 'modforge-shell-v057a' in sw
    assert '/assets/styles.css?v=057a' in sw
    assert '/assets/app.js?v=057a' in sw
    assert '/assets/error-avatar.png' in sw
    assert '/assets/error-avatar-critical.png' in sw


def test_v063_recheck_stage_is_backend_stage_13() -> None:
    assert main.STAGES[12][0] == "recheck"
    assert main.STAGES[12][1] == "Повторная проверка"
    import threading
    job = {"job_id":"stage13-contract", "_cancel_event":threading.Event(), "_pause_event":threading.Event(), "_timeout_event":threading.Event()}
    main.stage_start(job, 12)
    assert job["stage_index"] == 13
    assert job["stage_label"] == "Повторная проверка"


def test_v063_pause_endpoint_toggles_real_server_state() -> None:
    import threading
    job_id = "pause-contract-044"
    main.jobs[job_id] = {"job_id": job_id, "status": "running", "_pause_event": threading.Event()}
    try:
        first = asyncio.run(main.pause_job(job_id))
        assert first["paused"] is True
        assert main.jobs[job_id]["status"] == "paused"
        second = asyncio.run(main.pause_job(job_id))
        assert second["paused"] is False
        assert main.jobs[job_id]["status"] == "running"
    finally:
        main.jobs.pop(job_id, None)


def test_v063_light_color_uses_linear_rgb(tmp_path: Path) -> None:
    root = tmp_path / "light_color"
    root.mkdir()
    p = root / "lights.json"
    p.write_text('{"light":{"class":"SpotLight","brightness":1,"color":[255,128,0,255]}}', "utf-8")
    import threading
    job = {"_cancel_event": threading.Event(), "_pause_event": threading.Event()}
    changes = main.repair_lighting_file(p, job)
    data = json.loads(p.read_text("utf-8"))
    assert changes
    assert data["light"]["color"][0] == 1.0
    assert 0.2 < data["light"]["color"][1] < 0.22
    assert data["light"]["color"][2] == 0.0


def test_v063_jbeam_light_nested_angle_repair_preserves_transform(tmp_path: Path) -> None:
    import threading
    root = tmp_path / "nested_light"
    root.mkdir()
    p = root / "car.jbeam"
    original = '{\n"lights":[["id","type"],["lamp","SPOTLIGHT",{"lightBrightness":0.5,"lightInnerAngle":120,"lightOuterAngle":60,"baseRotationGlobal":{"x":1,"y":2,"z":3}}]]\n}'
    p.write_text(original, "utf-8")
    job = {"_cancel_event": threading.Event(), "_pause_event": threading.Event()}
    changes = main.repair_jbeam_light_props(p)
    text = p.read_text("utf-8")
    assert changes
    assert '"lightIntensityCd":2500.0' in text
    assert '"lightInnerAngle":60' in text
    assert '"lightOuterAngle":120' in text
    assert '"baseRotationGlobal":{"x":1,"y":2,"z":3}' in text


def test_v063_light_repair_never_changes_orientation(tmp_path: Path) -> None:
    root = tmp_path / "light_orientation"
    root.mkdir()
    p = root / "lights.json"
    original = {"light":{"class":"SpotLight","brightness":1,"rotationMatrix":[1,2,3,4,5,6,7,8,9],"position":[10,20,30]}}
    p.write_text(json.dumps(original), "utf-8")
    import threading
    job = {"_cancel_event": threading.Event(), "_pause_event": threading.Event()}
    main.repair_lighting_file(p, job)
    data = json.loads(p.read_text("utf-8"))
    assert data["light"]["rotationMatrix"] == original["light"]["rotationMatrix"]
    assert data["light"]["position"] == original["light"]["position"]


def test_v063_lighting_scan_flags_legacy_pbl_fields(tmp_path: Path) -> None:
    import threading
    root = tmp_path / "mod"
    (root / "vehicles" / "demo").mkdir(parents=True)
    (root / "vehicles" / "demo" / "lights.json").write_text('{"light":{"brightness":2,"linearAttenuation":1}}', "utf-8")
    job = {"_cancel_event": threading.Event(), "_pause_event": threading.Event(), "_timeout_event": threading.Event(), "status": "running"}
    issues = main.scan_lighting(root, job)
    titles = [x["title"] for x in issues]
    assert any("legacy-параметр brightness" in x for x in titles)
    assert any("legacy-расчёт затухания" in x for x in titles)


def test_v063_problem_hint_catalog_is_not_truncated_at_twenty() -> None:
    assert len(__import__('builtins').getattr(__import__('main'), 'PROBLEM_HINT_LABELS', {})) >= 29


def test_v063_recheck_scopes_changed_files_only(tmp_path: Path) -> None:
    import threading
    root = tmp_path / "mod"; root.mkdir()
    (root / "changed.json").write_text('{"ok": 1}', "utf-8")
    (root / "untouched.json").write_text('{"ok": 2,}', "utf-8")
    job = {"job_id":"scope-test","_cancel_event":threading.Event(),"_pause_event":threading.Event(),"_timeout_event":threading.Event(),"_stage_index":12}
    issues = main.verify_tree(root, job, 12, {"changed.json"})
    assert not any("untouched.json" in str(x.get("details")) for x in issues)
    assert job["stage_progress"] == 100


def test_v063_package_stores_precompressed_assets_without_deflate(tmp_path: Path) -> None:
    import threading, zipfile
    root = tmp_path / "mod"; root.mkdir()
    (root / "tex.dds").write_bytes(b"DDS " + b"x" * 2048)
    (root / "config.json").write_text('{"ok": true}', "utf-8")
    out = tmp_path / "out.zip"
    job = {"job_id":"zip-test","_cancel_event":threading.Event(),"_pause_event":threading.Event(),"_timeout_event":threading.Event(),"_stage_index":13,"repair_mode":"standard"}
    main.package_zip(root, out, job, with_branding=False)
    with zipfile.ZipFile(out) as zf:
        assert zf.getinfo("tex.dds").compress_type == zipfile.ZIP_STORED
        assert zf.getinfo("config.json").compress_type == zipfile.ZIP_DEFLATED


def test_v095_usual_settings_memory_contract() -> None:
    js = (ROOT / "assets" / "app.js").read_text("utf-8")
    html = (ROOT / "index.html").read_text("utf-8")
    assert "USUAL_PREFERENCES" in js
    assert "recordUsualSettings" in js
    assert "loadUsualSettings" in js
    assert "applyUsualSettings" in js
    assert "usualSettingsPrompt" in js
    assert 'id="versionBadge">V1 · 0.57-A · GLOBAL UPDATE</span>' in html


def test_v095_one_time_local_reset_is_scoped_to_modforge_keys() -> None:
    js = (ROOT / "assets" / "app.js").read_text("utf-8")
    assert "LOCAL_DATA_RESET_RELEASE = '0.57-A'" in js
    assert "key.startsWith('mf_')" in js
    assert "Server-side jobs are untouched" in js
