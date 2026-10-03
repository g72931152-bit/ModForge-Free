from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import main


def _job(job_id="arch-test"):
    return {
        "job_id": job_id, "status": "running", "root": str(Path(main.WORK_ROOT) / job_id),
        "_cancel_event": threading.Event(), "_pause_event": threading.Event(), "_timeout_event": threading.Event(),
        "load_guard": {"state": "idle"},
    }


def test_engine_contracts_are_explicit_and_independent():
    assert main.VA2_RELEASE == "0IN-1.0"
    assert main.VE1_RELEASE == "M0-D-l00"
    assert main.ENGINE_INFO[main.VA2_ID]["mode"] == "repair"
    assert main.ENGINE_INFO[main.VE1_ID]["mode"] == "lab"
    assert main.ENGINE_INFO[main.VE1_ID]["architecture"]["va2_dependency"] is False
    assert main.engine_for_task("repair") == main.VA2_ID
    assert main.engine_for_task("modify") == main.VE1_ID


def test_public_health_exposes_engine_and_load_guard_contract():
    data = asyncio.run(main.health())
    assert data["site_version"] == "0.61-A"
    assert {x["id"] for x in data["engines"]} == {"VA2", "VE1"}
    assert data["capabilities"]["async_load_cooldown"] is True
    assert data["config"]["load_guard"]["cooldown_seconds"] >= 1.0


def test_va2_dispatch_never_carries_modification_request():
    job = _job("va2-dispatch")
    main.jobs[job["job_id"]] = job
    old = main.run_va2_engine
    captured = {}

    async def fake(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs

    try:
        main.run_va2_engine = fake
        asyncio.run(main.run_job(job["job_id"], Path(job["root"]), "x.zip", "zip", "x.zip", "", [], 0, "FIXED", "zip", "standard", "repair", "не запускать VE", "standard"))
        assert captured["args"][-2] == ""
        assert captured["args"][-3] == "repair"
    finally:
        main.run_va2_engine = old
        main.jobs.pop(job["job_id"], None)


def test_load_guard_sync_pause_clears_cooldown_state(monkeypatch, tmp_path):
    job = _job("cooldown-pause")
    Path(job["root"]).mkdir(parents=True, exist_ok=True)
    snapshots = iter([
        {"load1": 10.0, "cpu": 4, "ratio": 2.5, "free_disk": 10**12, "disk_pressure": False},
        {"load1": 10.0, "cpu": 4, "ratio": 2.5, "free_disk": 10**12, "disk_pressure": False},
    ])
    monkeypatch.setattr(main, "host_pressure_snapshot", lambda: next(snapshots))
    monkeypatch.setattr(main, "LOAD_GUARD_COOLDOWN_SECONDS", 0.001)
    job["_pause_event"].set()
    main.apply_load_cooldown(job)
    assert job["_load_cooldown"] is False
    assert job["status"] == "paused"
    assert job["load_guard"]["state"] == "paused"
    import shutil; shutil.rmtree(job["root"], ignore_errors=True)


def test_load_guard_async_does_not_block_pause_or_leave_flag(monkeypatch):
    job = _job("cooldown-async")
    phase = {"high": True}
    def snapshot():
        return {"load1": 10.0 if phase["high"] else 0.0, "cpu": 4, "ratio": 2.5 if phase["high"] else 0.0, "free_disk": 10**12, "disk_pressure": False}
    monkeypatch.setattr(main, "host_pressure_snapshot", snapshot)
    monkeypatch.setattr(main, "LOAD_GUARD_COOLDOWN_SECONDS", 0.01)

    async def scenario():
        task = asyncio.create_task(main.load_cooldown_async(job))
        await asyncio.sleep(0.004)
        job["_pause_event"].set()
        await asyncio.sleep(0.006)
        assert not task.done()
        phase["high"] = False
        job["_pause_event"].clear()
        await task
    asyncio.run(scenario())
    assert job["_load_cooldown"] is False
    assert job["load_guard"]["state"] == "resumed"


def test_ve1_edit_endpoints_reject_va2_job():
    job = _job("va2-endpoints")
    job.update(engine_id=main.VA2_ID, status="running")
    main.jobs[job["job_id"]] = job
    client = TestClient(main.app)
    try:
        r = client.get(f"/api/jobs/{job['job_id']}/lab/materials")
        assert r.status_code == 409
        assert r.json()["code"] == "MF-409"
    finally:
        main.jobs.pop(job["job_id"], None)


def test_info_center_contract_is_present():
    html = (Path(main.BASE_DIR) / "index.html").read_text("utf-8")
    js = (Path(main.BASE_DIR) / "assets" / "app.js").read_text("utf-8")
    assert 'id="interfaceInfoTop"' in html
    assert 'id="interfaceInfoNav"' in html
    assert 'id="interfaceInfoContent"' in html
    assert "const INTERFACE_INFO" in js
    for key in ("overview", "topbar", "engines", "input", "focus", "request", "modes", "output", "speed", "processing", "lab", "resultPanel", "recovery", "history", "shortcuts", "limits"):
        assert f"{key}:" in js
    assert "Ctrl/Cmd + Shift + U" in js and "Ctrl/Cmd + Shift + R" in js


def test_manifest_keeps_stable_app_name():
    data = json.loads((Path(main.BASE_DIR) / "manifest.json").read_text("utf-8"))
    assert data["name"] == "ModForge"
    assert data["short_name"] == "ModForge"


def test_ve1_modification_ignores_va2_repair_action_toggles(tmp_path):
    root = tmp_path / "payload"; vehicle = root / "vehicles" / "a"; vehicle.mkdir(parents=True)
    jbeam = vehicle / "a.jbeam"
    jbeam.write_text('{"spring":1000,"beamSpring":2000,"damp":300}', "utf-8")
    job = {"engine_id": main.VE1_ID, "selected_variant": {"id":"vehicles/a","vehicle_path":"vehicles/a"},
           "repair_actions": [], "repair_exclusions": [], "excluded_files": [], "_cancel_event": threading.Event(), "_pause_event": threading.Event()}
    out = main.apply_modification_request(root, "сделать подвеску мягче на 15%", job)
    assert any(x.get("level") == "fixed" for x in out)
    data = json.loads(jbeam.read_text("utf-8"))
    assert data["spring"] == 850.0
