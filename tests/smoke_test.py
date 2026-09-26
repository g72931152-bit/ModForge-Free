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


if __name__ == "__main__":
    test_vehicle_branding()
    print("ModForge smoke test: OK")
