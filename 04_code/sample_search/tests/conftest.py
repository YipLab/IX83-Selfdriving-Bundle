import sys
from pathlib import Path

BUNDLE = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(BUNDLE / "03_external/sample_search"),
                str(BUNDLE / "04_code/sample_search"),
                str(BUNDLE / "04_code/ix83_acquisition/src")]
