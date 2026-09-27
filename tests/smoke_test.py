from __future__ import annotations

import json
import tempfile
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image

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
    assert info["Brand"] == "Cadillac ModForge"
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
    assert stage["baseColorFactor"] == [0.2, 0.28, 0.34, 1.0]
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
    assert inspector["missing_references"]
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
    print("ModForge V1 (0.42) regression smoke tests: OK")


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
