"""Temporary local import setup while redsun-planner is in the bundle checkout."""

from __future__ import annotations

import sys
from pathlib import Path


def enable_source_tree(
    *,
    include_planner_source: bool = False,
    include_processing_source: bool = False,
    include_test_support: bool = False,
) -> Path:
    """Expose acquisition sources; opt into planner source only for local development."""
    bundle_root = Path(__file__).resolve().parents[4]
    source_paths = [
        bundle_root / "04_code/ix83_acquisition/src",
    ]
    if include_planner_source:
        source_paths.append(bundle_root / "03_external/sample_search/src")
    if include_processing_source:
        processing_source = bundle_root / "03_external/Realtime-Anisotropy-SPT-Analysis/src"
        if processing_source.is_dir():
            source_paths.append(processing_source)
    if include_test_support:
        source_paths.append(bundle_root / "04_code/ix83_acquisition/tests/scan_host")

    normalized = {str(path.resolve()).casefold() for path in source_paths}
    sys.path[:] = [
        path for path in sys.path if str(Path(path or ".").resolve()).casefold() not in normalized
    ]
    sys.path[:0] = [str(path) for path in source_paths]
    return bundle_root
