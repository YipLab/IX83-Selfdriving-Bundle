"""Isolated imports for the un-packaged bundle-local prototype tools."""
from __future__ import annotations

import sys
from pathlib import Path


def enable_source_tree(*, include_processing_source: bool = False,
                       include_test_support: bool = False) -> Path:
    """Expose current source trees to local tools until package metadata exists."""
    bundle_root = Path(__file__).resolve().parents[2]
    source_paths = [
        bundle_root / "03_external/sample_search",
        bundle_root / "04_code/sample_search",
        bundle_root / "04_code/ix83_acquisition/src",
    ]
    if include_processing_source:
        processing_source = bundle_root / "03_external/Realtime-Anisotropy-SPT-Analysis/src"
        if processing_source.is_dir():
            source_paths.append(processing_source)
    if include_test_support:
        source_paths.append(bundle_root / "04_code/sample_search/tests")

    normalized = {str(path.resolve()).casefold() for path in source_paths}
    sys.path[:] = [path for path in sys.path if str(Path(path or ".").resolve()).casefold() not in normalized]
    sys.path[:0] = [str(path) for path in source_paths]
    return bundle_root
