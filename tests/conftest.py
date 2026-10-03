from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
for p in (APP, ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
