import sys
from pathlib import Path

bundle_root = Path(__file__).resolve().parents[4]
for source in (
    bundle_root / "04_code/ix83_acquisition/src",
    bundle_root / "04_code/ix83_acquisition/scripts/scan_workflow",
):
    sys.path.insert(0, str(source))
sys.path.insert(
    0,
    str(bundle_root / "04_code/ix83_acquisition/scripts/scan_workflow"),
)
