from pathlib import Path
import json
import tempfile
import asyncio
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main


def _job(tmp, selected=None):
    root = Path(tmp)
    return {"root": str(root), "asset_type": "vehicle", "asset_subtype": "microbus", "selected_variant": selected, "repair_actions": ["vehicle","glass","pbr"], "repair_exclusions": [], "excluded_files": [], "repair_mode": "standard", "status":"waiting_selection", "job_id":"test-058a"}


def test_release_and_palette_contract():
    assert main.RELEASE_ID == "v1 (0.58-A)"
    js=(Path(__file__).resolve().parents[1]/"assets/app.js").read_text("utf-8")
    html=(Path(__file__).resolve().parents[1]/"index.html").read_text("utf-8")
    assert "customAccentColorInput" in js
    assert 'data-accent-option="lime"' in js
    assert "halloween.js?v=058a" in html
    assert '<button class="brand brand-button"' in html
    assert "V1 · 0.58-A" in html
    assert "MODFORGE_OWNER_EMAIL" in (Path(__file__).resolve().parents[1]/"main.py").read_text("utf-8")


def test_catalog_vehicle_with_generated_preview_and_configs():
    tmp=tempfile.mkdtemp(prefix="mf058a-cat-")
    root=Path(tmp)
    vehicle=root/"vehicles"/"stress"
    vehicle.mkdir(parents=True)
    (vehicle/"stress.jbeam").write_text('{"information":{"name":"Stress Microbus"}}',"utf-8")
    (vehicle/"info.json").write_text(json.dumps({"name":"Stress Microbus"}),"utf-8")
    (vehicle/"rescue.pc").write_text('{"config":"Rescue"}',"utf-8")
    job=_job(root)
    catalog=main.build_asset_catalog(root, job)
    assert catalog["count"] == 1
    item=catalog["items"][0]
    assert item["name"] == "Stress Microbus"
    assert item["has_real_preview"] is False
    assert item["preview"].startswith("__catalog__/")
    assert item["configs"][0]["name"] == "Rescue"


def test_selected_vehicle_limits_repairs_but_not_shared_files():
    tmp=tempfile.mkdtemp(prefix="mf058a-scope-")
    root=Path(tmp)
    a=root/"vehicles"/"a"; b=root/"vehicles"/"b"; shared=root/"common"
    for d in (a,b,shared): d.mkdir(parents=True)
    selected={"id":"vehicles/a","vehicle_path":"vehicles/a"}
    job=_job(root,selected)
    assert main.file_repair_excluded(job,root,a/"a.jbeam","vehicle") is False
    assert main.file_repair_excluded(job,root,b/"b.jbeam","vehicle") is True
    assert main.file_repair_excluded(job,root,shared/"body.materials.json","pbr") is False


def test_launch_parser_and_safe_heuristic():
    req=main.parse_modification_request("сделать старт плавнее на 40%")
    assert req["launch_percent"] == 40
    factors=main.modification_factors(req)
    assert factors["engine"] == 1.0


def test_lab_paint_skips_glass_materials():
    tmp=tempfile.mkdtemp(prefix="mf058a-paint-")
    root=Path(tmp)
    vehicle=root/"vehicles"/"a"; vehicle.mkdir(parents=True)
    mats={
        "body": {"class":"Material","Stages":[{"baseColorFactor":[1,1,1,1]}]},
        "windshieldGlass": {"class":"Material","Stages":[{"baseColorFactor":[.1,.1,.1,1]}]},
    }
    mp=vehicle/"a.materials.json"; mp.write_text(json.dumps(mats),"utf-8")
    job=_job(root,{"id":"vehicles/a","vehicle_path":"vehicles/a"})
    entries=main.build_lab_material_catalog(root,job)
    assert any(x["label"]=="body" for x in entries)
    assert all("glass" not in x["label"].lower() and "windshield" not in x["label"].lower() for x in entries)
    changes=main.apply_lab_paint(root,job,[entries[0]["id"]],"#123456")
    data=json.loads(mp.read_text("utf-8"))
    assert changes
    assert data["body"]["Stages"][0]["baseColorFactor"][:3] == [0.070588,0.203922,0.337255]
    assert data["windshieldGlass"]["Stages"][0]["baseColorFactor"][:3] == [.1,.1,.1]
