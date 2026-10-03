import json, threading
from pathlib import Path

import main


def _job(mode="standard"):
    return {"job_id":"core-test","repair_mode":mode,"_cancel_event":threading.Event(),"_pause_event":threading.Event(),"_timeout_event":threading.Event(),"_stage_index":0,"scan_workers":1,"repair_actions":list(main.DEFAULT_REPAIR_ACTIONS),"repair_exclusions":[],"excluded_files":[]}


def test_standard_recovers_missing_vehicle_texture_with_generated_fallback(tmp_path):
    root = tmp_path / "mod"
    vehicle = root / "vehicles" / "car"
    vehicle.mkdir(parents=True)
    mat = vehicle / "car.materials.json"
    mat.write_text(json.dumps({"paint":{"class":"Material","name":"paint","Stages":[{"baseColorMap":"/vehicles/car/paint_missing.dds","normalMap":"/vehicles/car/normal_missing.png"}]}}), encoding="utf-8")
    jbeam = vehicle / "car.jbeam"
    jbeam.write_text('{"car":{"information":{"name":"car"},"paint":"vehicles/car/paint_missing.dds"}}', encoding="utf-8")

    repairs = main.repair_tree(root, _job("standard"))
    rules = {x.get("rule_id") for x in repairs}
    assert "RES-FALLBACK" in rules
    assert (vehicle / "paint_missing.png").exists()
    assert (vehicle / "normal_missing.png").exists()
    material = json.loads(mat.read_text("utf-8"))["paint"]
    assert material["Stages"][0]["baseColorMap"].endswith("paint_missing.png")
    assert material["Stages"][0]["normalMap"].endswith("normal_missing.png")

    second = main.repair_tree(root, _job("standard"))
    assert second == [] or not any(x.get("rule_id") == "RES-FALLBACK" for x in second)


def test_unique_extension_recovery(tmp_path):
    root = tmp_path / "mod"
    vehicle = root / "vehicles" / "car"
    vehicle.mkdir(parents=True)
    (vehicle / "body.png").write_bytes(b"png")
    cfg = vehicle / "body.materials.json"
    cfg.write_text('{"body":{"class":"Material","Stages":[{"baseColorMap":"vehicles/car/body.dds"}]}}', encoding="utf-8")
    repairs = main.repair_tree(root, _job("standard"))
    assert any(x.get("rule_id") == "RES-EXTENSION" for x in repairs)
    assert "body.png" in cfg.read_text("utf-8")


def test_unrecoverable_resource_is_not_faked_as_success(tmp_path):
    root = tmp_path / "mod"
    vehicle = root / "vehicles" / "car"
    vehicle.mkdir(parents=True)
    jbeam = vehicle / "car.jbeam"
    jbeam.write_text('{"car":{"mesh":"vehicles/car/body_missing.dae"}}', encoding="utf-8")
    repairs = main.repair_tree(root, _job("standard"))
    assert not any(x.get("rule_id") == "RES-FALLBACK" for x in repairs)
    assert "body_missing.dae" in jbeam.read_text("utf-8")


def test_referenced_corrupt_texture_is_rebuilt(tmp_path):
    root = tmp_path / "mod"
    vehicle = root / "vehicles" / "car"
    vehicle.mkdir(parents=True)
    broken = vehicle / "body.png"
    broken.write_bytes(b"this-is-not-a-real-png")
    mat = vehicle / "body.materials.json"
    mat.write_text('{"body":{"class":"Material","Stages":[{"baseColorMap":"vehicles/car/body.png"}]}}', encoding="utf-8")
    repairs = main.repair_tree(root, _job("standard"))
    assert any(x.get("rule_id") == "RES-CORRUPT" for x in repairs)
    from PIL import Image
    with Image.open(broken) as image:
        assert image.width == 64 and image.height == 64


def test_ve1_paint_can_create_missing_color_factor(tmp_path):
    root = tmp_path / "mod"
    vehicle = root / "vehicles" / "car"
    vehicle.mkdir(parents=True)
    path = vehicle / "body.materials.json"
    path.write_text('{"body":{"class":"Material","Stages":[{}]}}', encoding='utf-8')
    job = _job("standard") | {"engine_id": main.VE1_ID, "selected_variant": {"vehicle_path":"vehicles/car"}, "job_id":"ve"}
    changes = main.apply_lab_paint(root, job, ["vehicles/car/body.materials.json::body"], "#336699")
    assert changes
    data = json.loads(path.read_text("utf-8"))
    assert data["body"]["Stages"][0]["baseColorFactor"][:3] == [51/255,102/255,153/255]


def test_relative_missing_resource_is_generated_next_to_owner_file(tmp_path):
    root = tmp_path / "mod"
    vehicle = root / "vehicles" / "localcar"
    vehicle.mkdir(parents=True)
    mat = vehicle / "local.materials.json"
    mat.write_text(json.dumps({"glass":{"class":"Material","name":"glass","Stages":[{"baseColorMap":"missing.png"}]}}), encoding="utf-8")
    repairs = main.repair_tree(root, _job("standard"))
    assert any(x.get("rule_id") == "RES-FALLBACK" for x in repairs)
    generated = vehicle / "missing.png"
    assert generated.exists()
    assert json.loads(mat.read_text("utf-8"))["glass"]["Stages"][0]["baseColorMap"] == "missing.png"
    assert main._resource_exists(root, "missing.png", {p.relative_to(root).as_posix().casefold() for p in root.rglob("*") if p.is_file()}, source_path=mat)


def test_corrupt_unique_candidate_is_rebuilt_before_reference_is_fixed(tmp_path):
    root = tmp_path / "mod"
    vehicle = root / "vehicles" / "candidatecar"
    vehicle.mkdir(parents=True)
    broken = vehicle / "body.png"
    broken.write_bytes(b"broken-png")
    mat = vehicle / "body.materials.json"
    mat.write_text('{"body":{"class":"Material","Stages":[{"baseColorMap":"body.dds"}]}}', encoding="utf-8")
    repairs = main.repair_tree(root, _job("standard"))
    assert any(x.get("rule_id") in {"RES-UNIQUE", "RES-EXTENSION"} for x in repairs)
    assert json.loads(mat.read_text("utf-8"))["body"]["Stages"][0]["baseColorMap"] == "body.png"
    from PIL import Image
    with Image.open(broken) as image:
        assert image.size == (64, 64)
