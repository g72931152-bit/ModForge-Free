from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import stat
import tempfile
import threading
import zipfile
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main


def events() -> dict:
    return {
        "_cancel_event": threading.Event(),
        "_pause_event": threading.Event(),
        "_timeout_event": threading.Event(),
        "_stage_index": 0,
        "job_id": "stress-v062a",
        "scan_workers": 1,
    }


def test_scope_controls_and_aliases() -> None:
    actions, exclusions, paths = main.normalize_repair_settings(None, None, None)
    assert "vehicle" in actions and "glass" in actions
    assert actions == main.DEFAULT_REPAIR_ACTIONS

    actions, exclusions, paths = main.normalize_repair_settings([], ["physics"], ["vehicles/car/*.jbeam"])
    assert actions == []
    job = events() | {"repair_actions": ["vehicle"], "repair_exclusions": [], "excluded_files": []}
    root = Path(tempfile.mkdtemp(prefix="mf095-scope-"))
    p = root / "vehicles" / "car.jbeam"
    p.parent.mkdir(parents=True)
    p.write_text("{}", "utf-8")
    try:
        assert not main.file_repair_excluded(job, root, p, "physics")
        job["repair_exclusions"] = ["physics"]
        assert main.file_repair_excluded(job, root, p, "physics")
        job["repair_exclusions"] = []
        job["excluded_files"] = ["vehicles/*.jbeam"]
        assert main.file_repair_excluded(job, root, p, None)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_glass_damage_material_wiring_is_deterministic() -> None:
    root = Path(tempfile.mkdtemp(prefix="mf095-glass-"))
    path = root / "vehicles" / "car.materials.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({
        "glass": {"class": "Material", "name": "glass", "Stages": [{"baseColorFactor": [0.3, 0.3, 0.3, 0.4]}]},
        "glass_dmg": {"class": "Material", "name": "glass_dmg", "Stages": [{"baseColorFactor": [0.1, 0.1, 0.1, 0.7]}]},
    }), "utf-8")
    job = events() | {"repair_actions": ["glass"], "repair_exclusions": [], "excluded_files": []}
    try:
        repairs = main.repair_glass_damage_materials(path, root, job)
        data = json.loads(path.read_text("utf-8"))
        assert repairs and data["glass"]["deformMaterialBase"] == "glass"
        assert data["glass"]["deformMaterialDamaged"] == "glass_dmg"

        # A second run must not churn the file.
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        assert main.repair_glass_damage_materials(path, root, job) == []
        assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_glass_mirror_and_compatibility_scans() -> None:
    root = Path(tempfile.mkdtemp(prefix="mf095-scans-"))
    try:
        (root / "vehicles" / "car").mkdir(parents=True)
        (root / "vehicles" / "car" / "car.jbeam").write_text(
            '{"flexbodies":[{"deformGroup":"glass_front","deformMaterialBase":"glass"}],"mirrors":[["mirrorMesh","refNode","idLeft","idRight"]]}',
            "utf-8",
        )
        (root / "vehicles" / "car" / "glass.materials.json").write_text(
            json.dumps({"glass":{"class":"Material","name":"glass","Stages":[]},"glass_dmg":{"class":"Material","name":"glass_dmg","Stages":[]},"old":{"class":"Material","name":"old","persistentId":"legacy","version":1}}),
            "utf-8",
        )
        job = events()
        glass_issues = main.scan_glass_damage_wiring(root, job)
        mirror_issues = main.scan_mirrors(root, job)
        compat_issues = main.scan_compatibility_039(root, job)
        assert any(x.get("rule_id") == "GLASS-DEFORM-WIRING" for x in glass_issues)
        assert any(x.get("rule_id") == "MIRROR-SECTION" for x in mirror_issues)
        assert any(x.get("rule_id") == "COMPAT-039-MATERIAL" for x in compat_issues)

        # Migration is deterministic and only uses an existing PNG replacement.
        mat = root / "vehicles" / "car" / "old.materials.json"
        mat.write_text(json.dumps({"old":{"class":"Material","Stages":[{"baseColorMap":"old.dds"}],"persistentId":"x","version":1}}), "utf-8")
        (root / "vehicles" / "car" / "old.png").write_bytes(b"png")
        idx = {p.relative_to(root).as_posix().casefold() for p in root.rglob("*") if p.is_file()}
        repairs = main.migrate_materials_039(mat, root, idx, job)
        migrated = json.loads(mat.read_text("utf-8"))["old"]
        assert repairs and "persistentId" not in migrated and migrated["version"] == 1.5
        assert migrated["Stages"][0]["baseColorMap"] == "old.png"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_excluded_file_remains_byte_identical() -> None:
    root = Path(tempfile.mkdtemp(prefix="mf095-excluded-"))
    try:
        (root / "vehicles").mkdir(parents=True)
        target = root / "vehicles" / "untouch.json"
        target.write_text('{"broken":1,}', "utf-8")
        before = target.read_bytes()
        job = events() | {"repair_mode": "medium", "repair_actions": ["syntax"], "repair_exclusions": [], "excluded_files": ["vehicles/untouch.json"]}
        repairs = main.repair_tree(root, job)
        assert target.read_bytes() == before
        assert not repairs
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_api_contract_exposes_global_update_settings() -> None:
    import inspect
    params = inspect.signature(main.analyze).parameters
    required = {
        "asset_subtype", "repair_actions_json", "repair_exclusions_json", "excluded_files_json",
    }
    assert required.issubset(params)
    assert params["repair_actions_json"].default.default == ""
    assert params["repair_exclusions_json"].default.default == ""
    assert params["excluded_files_json"].default.default == ""
    cfg = asyncio.run(main.health())["config"]
    assert set(("asset_types", "asset_subtypes", "repair_actions", "repair_exclusions")).issubset(cfg)
    assert main.RELEASE_ID == "v1 (0.62-A)"
    assert main.BEAMNG_VERSION == "0.39"


def test_end_to_end_zip_pipeline() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="mf095-e2e-"))
    try:
        root = tmp / "job"
        source = root / "source"
        source.mkdir(parents=True)
        archive = source / "upload.zip"
        files = {
            "vehicles/stress/stress.jbeam": b'{"information":{"name":"StressCar"},}',
            "vehicles/stress/stress.materials.json": json.dumps({
                "glass": {"class":"Material","name":"glass","Stages":[]},
                "glass_dmg": {"class":"Material","name":"glass_dmg","Stages":[]},
            }).encode(),
            "vehicles/stress/old.materials.json": json.dumps({"body":{"class":"Material","name":"body","persistentId":"x","version":1,"Stages":[{"baseColorMap":"body.dds"}]} }).encode(),
            "vehicles/stress/body.png": b"png",
        }
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, data in files.items():
                zf.writestr(name, data)
        job = events() | {
            "root": str(root),
            "asset_type": "vehicle",
            "asset_subtype": "microbus",
            "problem_hints": ["glass_transparency", "mirror_reflection"],
            "repair_actions": ["syntax", "glass", "compat_039", "lighting", "resources"],
            "repair_exclusions": ["mirrors"],
            "excluded_files": [],
            "status": "queued",
            "processing_speed": "standard",
            "selected_variant": {"id":"vehicles/stress","vehicle_path":"vehicles/stress"},
        }
        main.jobs[job["job_id"]] = job
        asyncio.run(main.run_job(job["job_id"], root, "stress.zip", "zip", "stress.zip", "", [], archive.stat().st_size, "FIXED", "zip", "medium", "repair", "", "standard"))
        final = main.jobs[job["job_id"]]
        assert final["status"] == "done", final.get("error")
        out = Path(final["output"])
        assert out.exists() and out.suffix == ".zip" and out.stat().st_size > 0
        with zipfile.ZipFile(out) as zf:
            bad = zf.testzip()
            assert bad is None
            names = set(zf.namelist())
            assert "vehicles/stress/stress.jbeam" in names
            material = json.loads(zf.read("vehicles/stress/stress.materials.json").decode("utf-8"))
            assert material["glass"].get("deformMaterialDamaged") == "glass_dmg"
        report = final["report"]
        assert report["site_version"] == "0.62-A"
        assert report["asset_subtype"] == "microbus"
        assert "repair_actions" in report and "repair_exclusions" in report
    finally:
        main.jobs.pop("stress-v062a", None)
        shutil.rmtree(tmp, ignore_errors=True)


def test_zip_special_file_guard() -> None:
    root = Path(tempfile.mkdtemp(prefix="mf095-zipguard-"))
    archive = root / "special.zip"
    try:
        info = zipfile.ZipInfo("special.bin")
        info.external_attr = (stat.S_IFIFO | 0o600) << 16
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr(info, b"x")
        try:
            main.extract_zip(archive, root / "out")
        except ValueError as exc:
            assert "специальный файл" in str(exc)
        else:
            raise AssertionError("special file was accepted")
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
