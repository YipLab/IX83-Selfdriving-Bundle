"""Seam discontinuity analysis with a checked geometry precondition (Q06).

Q06 asks for seam analysis over recorded mosaics alongside the registration
figures. A seam metric is only meaningful if the pixel geometry is known: which
canvas position each tile's edge falls on. A saved mosaic does not always carry
that directly — a declared source shape and downsample can disagree with the
canvas when the builder also crops — so this module derives the tile size from
the record's own coverage array instead of trusting a declared scale, and refuses
to measure seams when no tile geometry reproduces the coverage.

The measurement is comparative, not absolute. For each tile edge it reports the
mean absolute intensity step across the edge and a control step from inside the
same tile, so a seam can be described relative to that tile's own within-tile
variation. A mosaic that blends overlapping tiles already averages the boundary,
so the step is a residual mismatch after averaging; it is not the raw tile
disagreement, and it is not an image-quality verdict.

The module reads arrays only; it does not stitch, re-register or read Zarr.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import numpy as np

#: A geometry that reproduces at most this fraction of pixels wrongly is accepted.
DEFAULT_MAX_MISMATCH = 0.01


@dataclass(frozen=True)
class GeometryFit:
    """Best tile geometry found for a coverage array, and whether it is usable."""

    tile_px: int
    rounding: str
    mismatch_fraction: float
    accepted: bool
    max_mismatch: float


def predict_coverage(
    origins: Sequence[tuple[float, float]],
    shape: tuple[int, int],
    tile_px: int,
    *,
    rounding: str = "round",
) -> np.ndarray:
    """Return the per-pixel tile count implied by origins and a tile size."""
    if tile_px < 1:
        raise ValueError("tile_px must be positive")
    if rounding not in ("round", "floor"):
        raise ValueError("rounding must be 'round' or 'floor'")
    height, width = shape
    predicted = np.zeros((height, width), dtype=np.int64)
    for x, y in origins:
        x0 = int(round(x)) if rounding == "round" else int(np.floor(x))
        y0 = int(round(y)) if rounding == "round" else int(np.floor(y))
        x1 = min(x0 + tile_px, width)
        y1 = min(y0 + tile_px, height)
        x0c, y0c = max(x0, 0), max(y0, 0)
        if x1 > x0c and y1 > y0c:
            predicted[y0c:y1, x0c:x1] += 1
    return predicted


def fit_tile_geometry(
    origins: Sequence[tuple[float, float]],
    coverage: np.ndarray,
    *,
    minimum_tile_px: int = 8,
    maximum_tile_px: int | None = None,
    max_mismatch: float = DEFAULT_MAX_MISMATCH,
) -> GeometryFit:
    """Find the tile size whose predicted coverage best matches the record.

    The search is over integer tile sizes and the two plausible origin roundings.
    It reports the best fraction of pixels that disagree, so a caller can see how
    far the record is from any equal-tile model rather than being told only that
    it failed.
    """
    if coverage.ndim != 2 or coverage.size == 0:
        raise ValueError("coverage must be a nonempty 2D array")
    if not origins:
        raise ValueError("at least one tile origin is required")
    height, width = coverage.shape
    maximum = maximum_tile_px if maximum_tile_px is not None else max(height, width)
    if maximum < minimum_tile_px:
        raise ValueError("maximum_tile_px must not be below minimum_tile_px")
    actual = np.asarray(coverage, dtype=np.int64)
    best: GeometryFit | None = None
    for tile in range(minimum_tile_px, maximum + 1):
        for rounding in ("round", "floor"):
            predicted = predict_coverage(origins, (height, width), tile, rounding=rounding)
            mismatch = float(np.count_nonzero(predicted != actual)) / actual.size
            if best is None or mismatch < best.mismatch_fraction:
                best = GeometryFit(
                    tile_px=tile,
                    rounding=rounding,
                    mismatch_fraction=mismatch,
                    accepted=mismatch <= max_mismatch,
                    max_mismatch=max_mismatch,
                )
    assert best is not None
    return best


@dataclass(frozen=True)
class SeamMeasurement:
    """One tile edge's measured step and its within-tile control."""

    axis: str
    position_px: int
    rows: int
    step: float
    control: float

    def to_document(self) -> dict[str, Any]:
        """Return the JSON-safe measurement."""
        return {
            "axis": self.axis,
            "position_px": self.position_px,
            "rows": self.rows,
            "step": self.step,
            "control": self.control,
        }


@dataclass(frozen=True)
class SeamReport:
    """Measured seam steps for one mosaic and the geometry that justified them."""

    fit: GeometryFit
    measurements: tuple[SeamMeasurement, ...]
    refused_reason: str | None = None

    def to_document(self) -> dict[str, Any]:
        """Return the JSON-safe report."""
        steps = [item.step for item in self.measurements]
        controls = [item.control for item in self.measurements]
        return {
            "schema": "ix71.mosaic-seams.v1",
            "accepted": self.refused_reason is None,
            "refused_reason": self.refused_reason,
            "geometry": {
                "tile_px": self.fit.tile_px,
                "rounding": self.fit.rounding,
                "mismatch_fraction": self.fit.mismatch_fraction,
                "max_mismatch": self.fit.max_mismatch,
                "accepted": self.fit.accepted,
            },
            "seams_measured": len(self.measurements),
            "step_median": float(np.median(steps)) if steps else None,
            "step_p95": float(np.percentile(steps, 95)) if steps else None,
            "control_median": float(np.median(controls)) if controls else None,
            "control_p95": float(np.percentile(controls, 95)) if controls else None,
            "measurements": [item.to_document() for item in self.measurements],
        }


def measure_seams(
    mosaic: np.ndarray,
    coverage: np.ndarray,
    origins: Sequence[tuple[float, float]],
    fit: GeometryFit,
    *,
    axes: Sequence[str] = ("x",),
    minimum_span_px: int = 8,
) -> SeamReport:
    """Measure tile-edge steps and within-tile controls for each axis.

    Only edges with at least ``minimum_span_px`` covered pixels on both sides are
    measured. A control is the mean absolute step over three interior columns (or
    rows) of the same tile, so it carries that tile's own noise and texture.
    """
    if not fit.accepted:
        return SeamReport(fit=fit, measurements=(), refused_reason="geometry_unverified")
    image = np.asarray(mosaic, dtype=float)
    counts = np.asarray(coverage)
    if image.shape != counts.shape:
        raise ValueError("mosaic and coverage must share a shape")
    if image.ndim != 2:
        raise ValueError("mosaic must be a 2D array")
    height, width = image.shape
    tile = fit.tile_px
    measurements: list[SeamMeasurement] = []
    for axis in axes:
        if axis not in ("x", "y"):
            raise ValueError("axis must be 'x' or 'y'")
        for origin_x, origin_y in origins:
            x0 = int(round(origin_x)) if fit.rounding == "round" else int(np.floor(origin_x))
            y0 = int(round(origin_y)) if fit.rounding == "round" else int(np.floor(origin_y))
            if axis == "x":
                position = x0
                if not 0 < position < width:
                    continue
                rows = slice(max(y0, 0), min(y0 + tile, height))
                left = image[rows, position - 1]
                right = image[rows, position]
                mask = (counts[rows, position - 1] > 0) & (counts[rows, position] > 0)
                if int(mask.sum()) < minimum_span_px:
                    continue
                step = float(np.mean(np.abs(right - left)[mask]))
                controls = []
                for offset in (tile // 4, tile // 2, (3 * tile) // 4):
                    interior = position + offset
                    if interior <= 0 or interior >= width:
                        continue
                    a = image[rows, interior - 1]
                    b = image[rows, interior]
                    interior_mask = (counts[rows, interior - 1] > 0) & (
                        counts[rows, interior] > 0
                    )
                    if int(interior_mask.sum()) >= minimum_span_px:
                        controls.append(float(np.mean(np.abs(b - a)[interior_mask])))
                if not controls:
                    continue
                measurements.append(
                    SeamMeasurement(
                        axis="x",
                        position_px=position,
                        rows=int(mask.sum()),
                        step=step,
                        control=float(np.mean(controls)),
                    )
                )
            else:
                position = y0
                if not 0 < position < height:
                    continue
                columns = slice(max(x0, 0), min(x0 + tile, width))
                top = image[position - 1, columns]
                bottom = image[position, columns]
                mask = (counts[position - 1, columns] > 0) & (
                    counts[position, columns] > 0
                )
                if int(mask.sum()) < minimum_span_px:
                    continue
                step = float(np.mean(np.abs(bottom - top)[mask]))
                controls = []
                for offset in (tile // 4, tile // 2, (3 * tile) // 4):
                    interior = position + offset
                    if interior <= 0 or interior >= height:
                        continue
                    a = image[interior - 1, columns]
                    b = image[interior, columns]
                    interior_mask = (counts[interior - 1, columns] > 0) & (
                        counts[interior, columns] > 0
                    )
                    if int(interior_mask.sum()) >= minimum_span_px:
                        controls.append(float(np.mean(np.abs(b - a)[interior_mask])))
                if not controls:
                    continue
                measurements.append(
                    SeamMeasurement(
                        axis="y",
                        position_px=position,
                        rows=int(mask.sum()),
                        step=step,
                        control=float(np.mean(controls)),
                    )
                )
    reason = None if measurements else "no_measurable_seams"
    return SeamReport(fit=fit, measurements=tuple(measurements), refused_reason=reason)


def main(argv: list[str] | None = None) -> int:
    """Measure seams on a recorded mosaic and print or write the report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mosaic", type=Path)
    parser.add_argument("coverage", type=Path)
    parser.add_argument("placements", type=Path, help="CSV with registration_origin_x_px/y_px")
    parser.add_argument("--output", type=Path, default=None)
    arguments = parser.parse_args(argv)
    import csv

    import tifffile

    mosaic = tifffile.imread(arguments.mosaic)
    coverage = tifffile.imread(arguments.coverage)
    with arguments.placements.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    origins = [
        (
            float(row["registration_origin_x_px"]),
            float(row["registration_origin_y_px"]),
        )
        for row in rows
    ]
    fit = fit_tile_geometry(origins, np.asarray(coverage))
    report = measure_seams(mosaic, coverage, origins, fit, axes=("x", "y"))
    text = json.dumps(report.to_document(), indent=2) + "\n"
    if arguments.output is None:
        sys.stdout.write(text)
    else:
        arguments.output.write_text(text, encoding="utf-8")
    return 0 if report.refused_reason is None else 1


__all__ = [
    "DEFAULT_MAX_MISMATCH",
    "GeometryFit",
    "SeamMeasurement",
    "SeamReport",
    "fit_tile_geometry",
    "measure_seams",
    "predict_coverage",
]


if __name__ == "__main__":
    raise SystemExit(main())
