import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for path in [ROOT / "ml_workspace", ROOT / "ml_workspace/scripts", ROOT / "ml_workspace/experiments", ROOT / "ml_workspace/recommendation"]:
    sys.path.insert(0, str(path))
