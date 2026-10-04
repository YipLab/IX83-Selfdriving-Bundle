"""Summarize detector behavior on read-only AutoScanJ TIFF test data.

Run from the bundle root with the IX83 integration venv Python:
  python scripts/validate_autoscan_data.py <directory-or-tiff> [more inputs]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import tifffile
from samplescout.detection import DetectionConfig, detect_bright_objects
from scipy import ndimage


def summarize(path: Path, config: DetectionConfig) -> dict[str, object]:
    image = tifffile.imread(path)
    image_array = np.asarray(image)
    detections = detect_bright_objects(image_array, config)
    plane = image_array[..., config.channel] if image_array.ndim == 3 else image_array
    threshold = config.threshold if config.threshold is not None else _otsu_reference_threshold(plane)
    labels, _ = ndimage.label(plane > threshold, structure=np.ones((3, 3), dtype=np.uint8))
    label_sizes = np.bincount(labels.ravel())[1:]
    selected = np.flatnonzero(
        (label_sizes >= config.min_area_px)
        & (True if config.max_area_px is None else label_sizes <= config.max_area_px)
    )
    reference_count = int(selected.size)
    reference_labels = (selected + 1).tolist()
    reference_centers_yx = ndimage.center_of_mass(
        np.maximum(plane.astype(np.float64) - threshold, 0),
        labels,
        reference_labels,
    ) if reference_labels else []
    center_errors = [
        max(abs(item.x_pixel - center[1]), abs(item.y_pixel - center[0]))
        for item, center in zip(detections, reference_centers_yx, strict=True)
    ] if len(detections) == reference_count else []
    return {
        "path": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "shape": list(image_array.shape),
        "dtype": str(image_array.dtype),
        "min": float(image_array.min()),
        "max": float(image_array.max()),
        "threshold": config.threshold if config.threshold is not None else "otsu",
        "component_count": len(detections),
        "scipy_reference_component_count": reference_count,
        "component_counts_match": len(detections) == reference_count,
        "scipy_max_centroid_error_px": max(center_errors, default=None),
        "area_px_min": min((item.area_px for item in detections), default=None),
        "area_px_max": max((item.area_px for item in detections), default=None),
        "edge_touch_count": sum(item.touches_edge for item in detections),
    }


def _otsu_reference_threshold(image: np.ndarray) -> float:
    """Independent Otsu implementation for SciPy label-count cross-check."""
    low, high = float(image.min()), float(image.max())
    if low == high:
        return low
    hist, edges = np.histogram(image, bins=min(4096, max(256, int(np.sqrt(image.size)))), range=(low, high))
    prob = hist.astype(np.float64) / hist.sum()
    centers = (edges[:-1] + edges[1:]) * 0.5
    weight, mean = np.cumsum(prob), np.cumsum(prob * centers)
    denom = weight * (1.0 - weight)
    score = np.zeros_like(denom)
    valid = denom > 0
    score[valid] = (mean[-1] * weight[valid] - mean[valid]) ** 2 / denom[valid]
    return float(centers[int(np.argmax(score))])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path, help="TIFF files or directories to scan")
    parser.add_argument("--limit", type=int, default=0, help="maximum images per input (0 means all)")
    parser.add_argument("--threshold", type=float, help="fixed bright-pixel threshold (default: Otsu)")
    parser.add_argument("--min-area", type=int, default=1)
    parser.add_argument("--max-area", type=int)
    parser.add_argument("--output", type=Path, help="write JSON report here; stdout is always printed")
    args = parser.parse_args(argv)
    if args.limit < 0:
        parser.error("--limit must be non-negative")
    config = DetectionConfig(threshold=args.threshold, min_area_px=args.min_area, max_area_px=args.max_area)
    paths: list[Path] = []
    for raw_input in args.inputs:
        if raw_input.is_dir():
            paths.extend(sorted(p for p in raw_input.rglob("*") if p.is_file() and p.suffix.lower() in {".tif", ".tiff"}))
        elif raw_input.is_file() and raw_input.suffix.lower() in {".tif", ".tiff"}:
            paths.append(raw_input)
        else:
            parser.error(f"input is not a TIFF file or directory: {raw_input}")
    paths = sorted(set(paths))
    if not paths:
        parser.error("no TIFF images found")
    if args.limit:
        paths = paths[: args.limit]
    report = {
        "method": "global Otsu threshold plus 8-connected components",
        "input_count": len(paths),
        "config": {"threshold": config.threshold, "min_area_px": config.min_area_px, "max_area_px": config.max_area_px},
        "images": [summarize(path, config) for path in paths],
    }
    encoded = json.dumps(report, indent=2)
    print(encoded)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
