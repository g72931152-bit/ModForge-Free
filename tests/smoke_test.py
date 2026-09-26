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


if __name__ == "__main__":
    test_vehicle_branding()
    test_missing_glass_texture_is_repaired()
    print("ModForge smoke test: OK")
