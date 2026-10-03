from __future__ import annotations

import asyncio
import json
import tempfile
import sys
import threading
import time
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image
from fastapi import HTTPException

import main


def test_vehicle_branding() -> None:
    root = Path(tempfile.mkdtemp(prefix="modforge-smoke-"))
    vehicle = root / "vehicles" / "cadillac"
    vehicle.mkdir(parents=True)
    (vehicle / "info.json").write_text(json.dumps({"Brand": "Cadillac", "Name": "CTS"}), "utf-8")
    (vehicle / "cts.jbeam").write_text('{"cts":{"information":{"name":"CTS"}}}', "utf-8")
    Image.new("RGB", (640, 360), "white").save(vehicle / "thumbnail.jpg")

    main.inject_modforge_status(root, {"repair_mode": "standard"})
    info = json.loads((vehicle / "info.json").read_text("utf-8"))
    assert info["Brand"] == "Cadillac ModMendryx"
    marker = json.loads((root / "modforge_applied.json").read_text("utf-8"))
    assert marker["status"] == "repaired-artifact"
    assert marker["branding"]["thumbnail_watermark"] is True

    before = (vehicle / "thumbnail.jpg").read_bytes()
    main.inject_modforge_status(root, {"repair_mode": "standard"})
    assert before == (vehicle / "thumbnail.jpg").read_bytes()


def test_missing_glass_texture_is_repaired() -> None:
    root = Path(tempfile.mkdtemp(prefix="modforge-glass-") )
    vehicle = root / "vehicles" / "broken_car"
    vehicle.mkdir(parents=True)
    materials = {
        "broken_glass": {
            "name": "broken_glass",
            "mapTo": "broken_glass",
            "class": "Material",
            "Stages": [{
                "baseColorMap": ["/vehicles/broken_car/missing_glass_b.color.png"],
                "opacityMap": ["/vehicles/broken_car/missing_glass_o.data.png"],
                "normalMap": ["/vehicles/broken_car/missing_glass_n.normal.png"]
            }, {}, {}, {}],
            "materialTag1": "vehicle"
        }
    }
    path = vehicle / "main.materials.json"
    path.write_text(json.dumps(materials), "utf-8")
    changes = main.repair_glass(path, root=root)
    assert changes and "missing_glass_texture" in changes[0]["updates"]
    fixed = json.loads(path.read_text("utf-8"))["broken_glass"]
    stage = fixed["Stages"][0]
    assert "baseColorMap" not in stage and "opacityMap" not in stage and "normalMap" not in stage
    assert stage["baseColorFactor"] == [1.0, 1.0, 1.0, 1.0]
    assert fixed["translucent"] is True
    assert fixed["translucentBlendOp"] == "PreMulAlpha"





def _write_zip(path: Path, entries: dict[str, bytes], compress=True, external_attrs=None) -> None:
    import zipfile
    mode = zipfile.ZIP_DEFLATED if compress else zipfile.ZIP_STORED
    with zipfile.ZipFile(path, "w", mode) as zf:
        for name, data in entries.items():
            info = zipfile.ZipInfo(name)
            info.compress_type = mode
            if external_attrs and name in external_attrs:
                info.external_attr = external_attrs[name]
            zf.writestr(info, data)


def test_security_path_traversal_and_limits() -> None:
    import zipfile
    root = Path(tempfile.mkdtemp(prefix="modforge-security-"))
    bad = root / "bad.zip"
    _write_zip(bad, {"../escape.txt": b"x"})
    try:
        main.extract_zip(bad, root / "out")
        raise AssertionError("path traversal was not rejected")
    except ValueError:
        pass

    oversized = root / "oversized.zip"
    _write_zip(oversized, {"huge.txt": b"0123456789ABCDEFGHIJ"}, compress=False)
    old = main.MAX_UNPACKED
    main.MAX_UNPACKED = 10
    try:
        try:
            main.extract_zip(oversized, root / "out2")
            raise AssertionError("oversized archive was not rejected")
        except ValueError:
            pass
    finally:
        main.MAX_UNPACKED = old

    bomb = root / "bomb.zip"
    _write_zip(bomb, {"zeros.txt": b"0" * 200_000}, compress=True)
    symlink_zip = root / "symlink.zip"
    import stat
    link_info = {"link.txt": ((stat.S_IFLNK | 0o777) << 16)}
    _write_zip(symlink_zip, {"link.txt": b"x"}, compress=False, external_attrs=link_info)
    try:
        main.extract_zip(symlink_zip, root / "out_symlink")
        raise AssertionError("symlink entry was not rejected")
    except ValueError:
        pass

    try:
        main.extract_zip(bomb, root / "out3")
        # Extremely compressed data must hit the archive-bomb guard.
        raise AssertionError("archive bomb guard was not triggered")
    except ValueError as exc:
        assert "сжат" in str(exc).lower() or "bomb" in str(exc).lower()


def test_repair_preview_health_diff_and_verification() -> None:
    root = Path(tempfile.mkdtemp(prefix="modforge-regression-"))
    (root / "vehicles" / "testcar").mkdir(parents=True)
    (root / "vehicles" / "testcar" / "wanted.png").write_bytes(b"png")
    (root / "vehicles" / "testcar" / "duplicate.png").write_bytes(b"png")
    (root / "vehicles" / "testcar" / "broken.jbeam").write_text('{"broken":{"information":{"name":"x"}', "utf-8")
    (root / "vehicles" / "testcar" / "broken.json").write_text('{"a": 1,}', "utf-8")
    (root / "vehicles" / "testcar" / "bad.materials.json").write_text(json.dumps({
        "glass": {"class": "Material", "name": "glass", "Stages": [{"baseColorMap": ["/vehicles/testcar/missing.png"]}]}
    }), "utf-8")
    (root / "vehicles" / "testcar" / "refs.json").write_text(json.dumps({"tex":"/vehicles/testcar/missing.png"}), "utf-8")

    job = {"repair_mode":"medium", "_cancel_event":__import__('threading').Event(), "_pause_event":__import__('threading').Event(), "_timeout_event":__import__('threading').Event(), "_stage_index":0, "job_id":"test", "scan_workers":1}
    preview = main.build_repair_preview(root, "medium")
    assert preview["files_to_change"] >= 1
    assert any(x["rule_id"] == "JSON-TRAILING-COMMA" for x in preview["plans"])

    before = main.snapshot_for_preview(root, preview)
    syntax_issues = main.scan_syntax(root, job)
    assert any("JBeam" in x.get("title", "") for x in syntax_issues)
    repairs = main.repair_tree(root, job)
    verification = main.verify_tree(root, job, 11)
    assert not any("JSON всё ещё некорректен" in x.get("title", "") for x in verification)
    diffs = main.collect_diffs(root, before, repairs)
    assert diffs

    normalized = main.normalize_issues(repairs + verification)
    health = main.health_from_issues(normalized)
    assert set(health["categories"]) == set(main.HEALTH_CATEGORIES)

    inspector = main.build_resource_inspector(root)
    assert not inspector["missing_references"]
    assert inspector["duplicates"] or any("DUPLICATE" == row.get("status") for row in inspector["files"])
    assert any(row.get("status") == "DUPLICATE" for row in inspector["files"])

    cleaner_root = root / "cleaner"; cleaner_root.mkdir()
    (cleaner_root / "Thumbs.db").write_bytes(b"x")
    (cleaner_root / "keep.txt").write_bytes(b"keep")
    (cleaner_root / "car.bak").write_bytes(b"x")
    removed = main.clean_tree_safe(cleaner_root)
    assert "Thumbs.db" in removed and "car.bak" in removed
    assert (cleaner_root / "keep.txt").exists()


def test_mod_compare_and_doctor() -> None:
    root = Path(tempfile.mkdtemp(prefix="modforge-compare-"))
    a = root / "a.zip"; b = root / "b.zip"
    _write_zip(a, {"vehicles/a/a.jbeam": b"A", "common/shared.png": b"S"})
    _write_zip(b, {"vehicles/a/a.jbeam": b"B", "common/shared.png": b"S", "new/file.png": b"N"})
    result = main.compare_zip_paths(a, b)
    assert result["added"] == ["new/file.png"]
    assert result["changed"] == ["vehicles/a/a.jbeam"]
    assert result["conflicts"]

    job={"report":{"issues":[{"title":"У автомобиля не найден ресурс","severity":"ERROR","confidence":"PROBABLE","category":"Resources","status":"unresolved","details":"vehicles/a/a.jbeam → missing.png"}]}}
    doctor=main.mod_doctor(job, "пропало колесо")
    assert doctor["likely_causes"] or doctor["suggested_actions"]


if __name__ == "__main__":
    test_vehicle_branding()
    test_missing_glass_texture_is_repaired()
    test_security_path_traversal_and_limits()
    test_repair_preview_health_diff_and_verification()
    test_mod_compare_and_doctor()
    print("ModMendryx V1 (0.63-A) regression smoke tests: OK")


def test_large_file_is_deferred_not_rejected() -> None:
    import zipfile
    root = Path(tempfile.mkdtemp(prefix="modforge-large-"))
    archive = root / "large.zip"
    _write_zip(archive, {"vehicles/test/big.jbeam": b"0123456789ABCDEFGHIJ", "vehicles/test/small.jbeam": b'{}'}, compress=False)
    old_threshold = main.LARGE_FILE_THRESHOLD
    main.LARGE_FILE_THRESHOLD = 10
    try:
        out = root / "out"
        count, total, large = main.extract_zip(archive, out)
        assert count == 2 and total == 22
        assert large and large[0]["file"] == "vehicles/test/big.jbeam"
        assert (out / "vehicles/test/big.jbeam").stat().st_size == 20
        job = {"_cancel_event": __import__('threading').Event(), "_pause_event": __import__('threading').Event(), "_timeout_event": __import__('threading').Event()}
        assert main.is_large_scan_file(out / "vehicles/test/big.jbeam", job)
        assert not main.is_large_scan_file(out / "vehicles/test/small.jbeam", job)
    finally:
        main.LARGE_FILE_THRESHOLD = old_threshold


def test_public_job_is_small_even_with_huge_report() -> None:
    report = {
        "summary": {"files": 12000, "fixed": 37, "warnings": 91},
        "artifact_size": 123456,
        "resource_inspector": {"files": [{"path": f"x/{i}.jbeam"} for i in range(20000)]},
        "issues": [{"details": "x" * 400} for _ in range(20000)],
    }
    job = {
        "job_id": "test", "status": "done", "progress": 100, "stage_index": 15,
        "stage_label": "Готово", "stage_detail": "ok", "report": report,
        "output": "/secret/out.zip", "root": "/secret/root", "report_path": "/secret/report.json",
    }
    public = main.public_job(job)
    assert public["report_available"] is True
    assert public["report_summary"] == report["summary"]
    assert "resource_inspector" not in public
    assert "issues" not in public
    assert "report" not in public


def _job_events() -> dict:
    return {
        "_cancel_event": threading.Event(),
        "_pause_event": threading.Event(),
        "_timeout_event": threading.Event(),
        "_stage_index": 0,
        "job_id": "test",
        "scan_workers": 1,
    }


def test_mod_lab_ru_forms_and_requested_percentages() -> None:
    cases = {
        "сделать подвеску мягче на 15%": ("soft", 15.0),
        "сделать подвеску жёстче на 15%": ("hard", 15.0),
        "сделать подвеску жестче на 15%": ("hard", 15.0),
        "смягчить подвеску на 7%": ("soft", 7.0),
    }
    for text, expected in cases.items():
        req = main.parse_modification_request(text)
        assert (req["suspension"], req["suspension_percent"]) == expected

    req = main.parse_modification_request("двигатель +12%, RPM +25%")
    assert req["engine_percent"] == 12.0
    assert req["engine_rpm_percent"] == 25.0

    root = Path(tempfile.mkdtemp(prefix="modforge-modlab-percent-"))
    jbeam = root / "car.jbeam"
    jbeam.write_text(json.dumps({"spring": 100, "damp": 50, "torque": 200, "maxRPM": 4000, "idleRPM": 1000}), "utf-8")
    job = _job_events()
    request = "сделать подвеску мягче на 15%, двигатель +25%, RPM +25%"
    preview = main.build_repair_preview(root, "standard", "modify", request, job)
    assert {p["rule_id"] for p in preview["plans"]} == {"MOD-SUSPENSION", "MOD-ENGINE", "MOD-RPM"}
    repairs = main.apply_modification_request(root, request, job)
    data = json.loads(jbeam.read_text("utf-8"))
    assert data["spring"] == 85.0
    assert data["damp"] == 42.5
    assert data["torque"] == 250.0
    assert data["maxRPM"] == 5000.0
    assert data["idleRPM"] == 1250.0
    assert len(repairs) == 3
    assert all("ровно 15%" in x["details"] or "25%" in x["title"] or "25%" in x["details"] for x in repairs)


def test_json_repair_never_touches_string_content() -> None:
    root = Path(tempfile.mkdtemp(prefix="modforge-json-string-safe-"))
    path = root / "config.json"
    source = '{"literal": "keep comma,}", "literal2": "[,}]", "items": [1,],}'
    path.write_text(source, "utf-8")
    changed, _ = main.repair_json_syntax(path)
    assert changed is True
    repaired = path.read_text("utf-8")
    assert '"keep comma,}"' in repaired
    assert '"[,}]"' in repaired
    assert json.loads(repaired)["items"] == [1]
    second, _ = main.repair_json_syntax(path)
    assert second is False
    assert path.read_text("utf-8") == repaired


def test_glass_repair_is_stage_local_and_idempotent() -> None:
    root = Path(tempfile.mkdtemp(prefix="modforge-glass-stage-"))
    (root / "valid.png").write_bytes(b"png")
    path = root / "glass.materials.json"
    path.write_text(json.dumps({
        "glass": {
            "class": "Material", "name": "glass",
            "Stages": [
                {"baseColorMap": ["missing.png"], "opacityMap": ["valid.png"]},
                {"baseColorMap": ["valid.png"], "normalMap": ["valid.png"]},
            ],
        }
    }), "utf-8")
    resource_index = main.casefold_resource_index(root, main.path_set(root))
    first = main.repair_glass(path, root=root, resource_index=resource_index)
    fixed = json.loads(path.read_text("utf-8"))["glass"]
    assert first
    assert "baseColorMap" not in fixed["Stages"][0]
    assert fixed["Stages"][0]["opacityMap"] == ["valid.png"]
    assert fixed["Stages"][1]["baseColorMap"] == ["valid.png"]
    assert fixed["Stages"][1]["normalMap"] == ["valid.png"]
    before = path.read_bytes()
    second = main.repair_glass(path, root=root, resource_index=resource_index)
    assert second == []
    assert path.read_bytes() == before


def test_job_admission_limits_and_restart_dedup_are_atomic() -> None:
    old_jobs = dict(main.jobs)
    old_global = main.job_reservations_global
    old_client = dict(main.job_reservations_client)
    old_children = dict(main.restart_children)
    old_restart_res = set(main.restart_reservations)
    main.jobs.clear(); main.job_reservations_global = 0; main.job_reservations_client.clear(); main.restart_children.clear(); main.restart_reservations.clear()
    try:
        successes = []
        for i in range(main.MAX_ACTIVE_JOBS_GLOBAL + 5):
            cid = f"client-{i}"
            try:
                main.reserve_job_slot(cid)
                successes.append(cid)
            except HTTPException:
                pass
        assert len(successes) == main.MAX_ACTIVE_JOBS_GLOBAL
        for cid in successes:
            main.release_job_slot(cid)

        cid = "one-client"
        for _ in range(main.MAX_ACTIVE_JOBS_PER_CLIENT):
            main.reserve_job_slot(cid)
        try:
            main.reserve_job_slot(cid)
            raise AssertionError("client limit was bypassed")
        except HTTPException as exc:
            assert exc.detail["code"] == "MF-429"
        for _ in range(main.MAX_ACTIVE_JOBS_PER_CLIENT):
            main.release_job_slot(cid)

        restart_source = Path(tempfile.mkdtemp(prefix="modforge-restart-source-"))
        old_id = "old-job"
        (restart_source / "source").mkdir()
        main.jobs[old_id] = {"status": "done", "root": str(restart_source), "_client_id": "restart-client"}
        main.reserve_job_slot("restart-client", restart_from=old_id)
        try:
            main.reserve_job_slot("restart-client", restart_from=old_id)
            raise AssertionError("parallel restart was admitted")
        except HTTPException as exc:
            assert exc.detail["code"] == "MF-409"
        main.release_job_slot("restart-client", restart_from=old_id)
    finally:
        main.jobs.clear(); main.jobs.update(old_jobs)
        main.job_reservations_global = old_global; main.job_reservations_client.clear(); main.job_reservations_client.update(old_client)
        main.restart_children.clear(); main.restart_children.update(old_children)
        main.restart_reservations.clear(); main.restart_reservations.update(old_restart_res)


def test_upload_paths_are_canonical_case_insensitive_and_cleanup_on_error() -> None:
    class FakeUpload:
        def __init__(self, filename, chunks):
            self.filename = filename
            self._chunks = iter(chunks)
            self.closed = False
        async def read(self, _n):
            try: return next(self._chunks)
            except StopIteration: return b""
        async def close(self): self.closed = True

    root = Path(tempfile.mkdtemp(prefix="modforge-upload-collision-"))
    dest = root / "dest"; dest.mkdir()
    f1 = FakeUpload("A.txt", [b"a"]); f2 = FakeUpload("a.TXT", [b"b"])
    try:
        asyncio.run(main.save_folder_uploads([f1, f2], ["Mod/A.txt", "Mod/a.TXT"], dest))
        raise AssertionError("case-insensitive duplicate path was accepted")
    except ValueError as exc:
        assert "Повторяется путь файла" in str(exc)
    assert f1.closed and f2.closed
    assert not list(dest.rglob("*"))

    class FailingUpload(FakeUpload):
        async def read(self, _n):
            try:
                chunk = next(self._chunks)
            except StopIteration:
                return b""
            if chunk is None:
                raise IOError("simulated upload failure")
            return chunk
    dest2 = root / "dest2"; dest2.mkdir()
    good = FailingUpload("one.txt", [b"one"])
    bad = FailingUpload("two.txt", [None])
    try:
        asyncio.run(main.save_folder_uploads([good, bad], ["Mod/one.txt", "Mod/two.txt"], dest2))
        raise AssertionError("upload failure was not propagated")
    except IOError:
        pass
    assert not [p for p in dest2.rglob("*") if p.is_file()]
    assert not [p for p in dest2.iterdir() if p.name.startswith(".upload-staging-")]


def test_health_does_not_mark_unscanned_as_pass() -> None:
    health = main.health_from_issues([], set())
    assert health["overall"] == "NOT_SCANNED"
    assert all(v["status"] == "NOT_SCANNED" for v in health["categories"].values())
    partial = main.health_from_issues([], {"Syntax"})
    assert partial["categories"]["Syntax"]["status"] == "PASS"
    assert partial["categories"]["Resources"]["status"] == "NOT_SCANNED"
    assert partial["overall"] == "NOT_SCANNED"


def test_prepare_and_rollback_errors_are_terminal_error_not_done() -> None:
    async def run_prepare():
        root = Path(tempfile.mkdtemp(prefix="modforge-prepare-state-")); (root / "payload").mkdir()
        jid = "prepare-fail"
        main.jobs[jid] = {"status":"done","root":str(root),"report":{},"job_id":jid}
        original = main.clean_tree_safe
        main.clean_tree_safe = lambda _root: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            await main.prepare_release(jid)
        except HTTPException as exc:
            assert exc.detail["code"] == "MF-503"
        finally:
            main.clean_tree_safe = original
        assert main.jobs[jid]["status"] == "error"
        main.jobs.pop(jid, None)

    async def run_rollback():
        root = Path(tempfile.mkdtemp(prefix="modforge-rollback-state-")); (root / "source").mkdir(); (root / "source" / "upload.zip").write_bytes(b"not-a-zip")
        jid = "rollback-fail"
        main.jobs[jid] = {"status":"done","root":str(root),"report":{},"job_id":jid,"source_kind":"zip"}
        try:
            await main.job_rollback(jid, "original")
        except HTTPException as exc:
            assert exc.detail["code"] == "MF-503"
        assert main.jobs[jid]["status"] == "error"
        main.jobs.pop(jid, None)

    asyncio.run(run_prepare())
    asyncio.run(run_rollback())



def test_feedback_and_admin_rate_limits_block_spam() -> None:
    class FakeClient:
        host = "198.51.100.77"
    class FakeHeaders:
        def get(self, _key, _default=""):
            return ""
    class FakeRequest:
        client = FakeClient()
        headers = FakeHeaders()

    request = FakeRequest()
    main.rate_limit_buckets.clear()
    for _ in range(main.RATE_LIMITS["feedback_create"][0]):
        main.enforce_rate_limit(request, "feedback_create")
    try:
        main.enforce_rate_limit(request, "feedback_create")
        raise AssertionError("feedback spam was not blocked")
    except HTTPException as exc:
        assert exc.detail["code"] == "MF-429"

    main.rate_limit_buckets.clear()
    for _ in range(main.RATE_LIMITS["admin_login"][0]):
        main.enforce_rate_limit(request, "admin_login")
    try:
        main.enforce_rate_limit(request, "admin_login")
        raise AssertionError("admin bruteforce was not blocked")
    except HTTPException as exc:
        assert exc.detail["code"] == "MF-429"

def test_health_endpoint_exposes_only_public_config() -> None:
    data = asyncio.run(main.health())
    allowed={"brand_name","tagline","support_url","support_label","ad_enabled","ad_html","default_suffix","repair_modes","processing_speed_profiles","large_file_budget_share","asset_types","asset_subtypes","repair_actions","repair_exclusions","engines","load_guard"}
    assert set(data["config"]).issubset(allowed)
    assert data["config"]["large_file_budget_share"] == 0.5
    assert data["config"]["repair_modes"]["standard"]["check_blocks"] == 7
    assert "email" not in data
    assert "owner_email" not in data["config"]
    assert "SMTP_HOST" not in json.dumps(data)
    old_enabled, old_html = main.CONFIG.get("ad_enabled"), main.CONFIG.get("ad_html")
    try:
        main.CONFIG["ad_enabled"] = True; main.CONFIG["ad_html"] = "<b>public ad</b>"
        public = asyncio.run(main.health())
        assert public["config"]["ad_html"] == "<b>public ad</b>"
        assert "owner_email" not in json.dumps(public)
    finally:
        main.CONFIG["ad_enabled"] = old_enabled; main.CONFIG["ad_html"] = old_html


def test_repair_preview_matches_actual_changed_files_and_repair_is_idempotent() -> None:
    root = Path(tempfile.mkdtemp(prefix="modforge-preview-parity-"))
    (root / "vehicles" / "car").mkdir(parents=True)
    (root / "vehicles" / "car" / "Tex.PNG").write_bytes(b"png")
    jbeam = root / "vehicles" / "car" / "car.jbeam"
    jbeam.write_text('{"information":{"name":"x"},"tex":"vehicles/car/tex.png",}', "utf-8")
    glass = root / "vehicles" / "car" / "glass.materials.json"
    glass.write_text(json.dumps({"glass":{"class":"Material","name":"glass","Stages":[{"baseColorMap":["missing.png"]},{"baseColorMap":["vehicles/car/Tex.PNG"]}]}}), "utf-8")
    job = _job_events() | {"repair_mode":"medium"}
    preview = main.build_repair_preview(root, "medium", "repair", "", job)
    before = main.snapshot_for_preview(root, preview)
    repairs = main.repair_tree(root, job)
    changed = main.collect_diffs(root, before, repairs)
    changed_files = {x["file"] for x in changed if x.get("status") != "unchanged"}
    preview_files = {x["file"] for x in preview["plans"]}
    assert changed_files.issubset(preview_files)
    after = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    second = main.repair_tree(root, job)
    after2 = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert second == []
    assert after2 == after


def test_large_file_task_stops_with_cancel_and_does_not_finish_after_error() -> None:
    async def run():
        root = Path(tempfile.mkdtemp(prefix="modforge-large-lifecycle-"))
        (root / "big.bin").write_bytes(b"x")
        jid = "large-lifecycle"
        job = {"job_id":jid,"root":str(root),"_cancel_event":threading.Event(),"_pause_event":threading.Event(),"_timeout_event":threading.Event()}
        main.jobs[jid]=job
        original = main.review_large_file
        def slow_review(path, j):
            for _ in range(100):
                main.check_cancel_pause(j)
                time.sleep(0.002)
            return {"sha256":"x","bytes_read":1,"signals":[]}
        main.review_large_file = slow_review
        try:
            task = asyncio.create_task(main.run_large_file_task(jid, root, [{"file":"big.bin","size":1}]))
            await asyncio.sleep(0.01)
            job["status"]="error"; job["_cancel_event"].set()
            try:
                await task
                raise AssertionError("large task ignored cancellation")
            except RuntimeError as exc:
                assert str(exc) == "__CANCELLED__"
            assert job["large_task_status"] == "cancelled"
        finally:
            main.review_large_file = original
            main.jobs.pop(jid, None)
    asyncio.run(run())



def test_frontend_backend_upload_report_download_and_mf_contract() -> None:
    from fastapi.testclient import TestClient
    import zipfile

    async def noop(*_args, **_kwargs):
        return None
    old_run_job = main.run_job; old_watchdog = main.job_timeout_watchdog
    main.run_job = noop; main.job_timeout_watchdog = noop
    client = TestClient(main.app)
    old_jobs = dict(main.jobs); old_global = main.job_reservations_global; old_client = dict(main.job_reservations_client)
    try:
        main.jobs.clear(); main.job_reservations_global = 0; main.job_reservations_client.clear()
        response = client.post('/api/analyze', data={
            'source_kind':'single','source_name':'car.jbeam','output_type':'same','repair_mode':'standard','task_mode':'repair',
            'manifest_json':'[]','priority_json':'[]','problem_hints_json':'[]','wishes':'','modification_request':'','network_profile':'standard','output_suffix':'FIXED','asset_type':''
        }, files={'files':('car.jbeam', b'{"spring":100}', 'application/octet-stream')})
        assert response.status_code == 200, response.text
        jid = response.json()['job_id']
        assert client.get(f'/api/jobs/{jid}').status_code == 200

        root = Path(tempfile.mkdtemp(prefix='modforge-api-artifact-'))
        artifact = root / 'fixed.zip'
        with zipfile.ZipFile(artifact, 'w') as zf:
            zf.writestr('car.jbeam', '{"spring":100}')
        report_path = root / 'report.json'; report_path.write_text(json.dumps({'summary':{'fixed':1}}), 'utf-8')
        report_job = {'job_id':'artifact-contract','status':'done','root':str(root),'report_path':str(report_path),'fixed_archive_name':artifact.name,'output':str(artifact),'report':{}}
        main.jobs[report_job['job_id']] = report_job
        assert client.get('/api/health').status_code == 200
        assert client.head('/api/jobs/artifact-contract/download').status_code == 200
        assert client.get('/api/jobs/artifact-contract/download').status_code == 200
        assert client.get('/api/jobs/artifact-contract/report').status_code == 200
        main.jobs.clear(); main.jobs.update(old_jobs)
        shutil.rmtree(root, ignore_errors=True)
    finally:
        main.run_job = old_run_job; main.job_timeout_watchdog = old_watchdog
        # Clean any temporary analyze job roots created by this test.
        for jid, job in list(main.jobs.items()):
            if jid not in old_jobs and job.get('root'):
                shutil.rmtree(Path(job['root']), ignore_errors=True)
        main.jobs.clear(); main.jobs.update(old_jobs)
        main.job_reservations_global = old_global; main.job_reservations_client.clear(); main.job_reservations_client.update(old_client)

def test_frontend_backend_contract_mentions_modlab_forms_and_mf_error_handling() -> None:
    app_js = (Path(__file__).resolve().parents[1] / "site" / "assets" / "app.js").read_text("utf-8")
    html = (Path(__file__).resolve().parents[1] / "site" / "index.html").read_text("utf-8")
    assert 'data-mod-template="Сделать подвеску мягче на 15%."' in html
    assert 'data-mod-template="Сделать подвеску жёстче на 15%."' in html
    for endpoint in ("/api/health", "/api/analyze", "/restart", "/repair-preview", "/report", "/download"):
        assert endpoint in app_js or endpoint in html
    assert "d.code || `MF-${r.status}`" in app_js
