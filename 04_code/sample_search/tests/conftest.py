from pathlib import Path
from runpy import run_path

bootstrap_path = Path(__file__).resolve().parents[1] / "source_bootstrap.py"
bootstrap = run_path(str(bootstrap_path))
bootstrap["enable_source_tree"]()
