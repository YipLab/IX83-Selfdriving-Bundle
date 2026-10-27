"""Build a figure-input table and its SVG from a saved registration record (Q12).

Q12 asks for CSV/SVG/PNG figure outputs linked to their sources, analysis and
exclusions. This module is the first half of a real figure: it turns a saved
pairwise registration record into

* a measured per-pair CSV of placement residuals (the figure's input table),
* a provenance sidecar naming the registration identity, the calibration, the
  source digest and the row count, and
* a deterministic SVG histogram of the residual magnitudes.

It does not register, re-stitch, re-fit or choose a manuscript slot. The slot
assignment and any claim about image quality stay with the author; the numbers
here are exactly the recorded pairs' reported residuals.

The SVG is written directly rather than through a plotting library so a headless
session can rebuild the figure with the standard library alone and the output is
byte-stable for a given input.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Iterable, Sequence

TABLE_SCHEMA = "ix71.figure-input.residuals.v1"
SIDECAR_SCHEMA = "ix71.figure-input.provenance.v1"

TABLE_COLUMNS = (
    "pair_index",
    "frame_a",
    "frame_b",
    "residual_x_px",
    "residual_y_px",
    "magnitude_px",
)


def _sha256(path: Path) -> str:
    """Return the file digest."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _finite_pair(value: Any, name: str) -> tuple[float, float]:
    """Return one finite residual pair."""
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"{name} must be a two-value pair")
    x_px, y_px = value
    for part in (x_px, y_px):
        if isinstance(part, bool) or not isinstance(part, (int, float)):
            raise ValueError(f"{name} must contain numbers")
        if not math.isfinite(part):
            raise ValueError(f"{name} must be finite")
    return float(x_px), float(y_px)


def read_pairs(record: Any) -> list[dict[str, Any]]:
    """Return the passing pairs' residuals from a saved registration record.

    Only pairs whose `fit_status` is `passed` contribute, because a failed pair
    has no placement to plot. A record without a `pairs` list is refused rather
    than treated as empty.
    """
    if not isinstance(record, dict):
        raise ValueError("a registration record must be a JSON object")
    pairs = record.get("pairs")
    if not isinstance(pairs, list):
        raise ValueError("the registration record has no pairs list")
    rows: list[dict[str, Any]] = []
    for index, pair in enumerate(pairs):
        if not isinstance(pair, dict):
            raise ValueError(f"pairs[{index}] must be an object")
        if pair.get("fit_status") != "passed":
            continue
        residual_x_px, residual_y_px = _finite_pair(
            pair.get("placement_graph_residual_xy_px"),
            f"pairs[{index}].placement_graph_residual_xy_px",
        )
        rows.append(
            {
                "pair_index": index,
                "frame_a": pair.get(
                    "reference_frame_index", pair.get("frame_a", pair.get("first_frame"))
                ),
                "frame_b": pair.get(
                    "moving_frame_index", pair.get("frame_b", pair.get("second_frame"))
                ),
                "residual_x_px": residual_x_px,
                "residual_y_px": residual_y_px,
                "magnitude_px": math.hypot(residual_x_px, residual_y_px),
            }
        )
    if not rows:
        raise ValueError("the registration record has no passing pairs")
    return rows


def write_table(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    """Write the measured per-pair residual table."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(TABLE_COLUMNS))
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in TABLE_COLUMNS})


def histogram_bins(values: Sequence[float], *, bins: int) -> list[tuple[float, float, int]]:
    """Return (low, high, count) bins over the values."""
    if bins < 1:
        raise ValueError("bins must be positive")
    low, high = min(values), max(values)
    if high <= low:
        high = low + 1e-12
    width = (high - low) / bins
    counts = [0] * bins
    for value in values:
        index = min(int((value - low) / width), bins - 1)
        counts[index] += 1
    return [
        (low + index * width, low + (index + 1) * width, counts[index])
        for index in range(bins)
    ]


def render_histogram_svg(
    values: Sequence[float],
    *,
    title: str,
    x_label: str,
    width: int = 640,
    height: int = 400,
    bins: int = 24,
) -> str:
    """Render a deterministic SVG histogram of the values."""
    if not values:
        raise ValueError("values must not be empty")
    if width < 200 or height < 200:
        raise ValueError("width and height must be at least 200 px")
    margin_left, margin_right = 70, 30
    margin_top, margin_bottom = 50, 60
    plot_width = width - margin_left - margin_right
    plot_height = height - margin_top - margin_bottom
    bins_doc = histogram_bins(values, bins=bins)
    maximum = max(count for _low, _high, count in bins_doc) or 1
    bar_width = plot_width / len(bins_doc)
    bars: list[str] = []
    for index, (low, high, count) in enumerate(bins_doc):
        bar_height = plot_height * (count / maximum)
        x = margin_left + index * bar_width
        y = margin_top + (plot_height - bar_height)
        bars.append(
            f'<rect x="{x:.2f}" y="{y:.2f}" width="{max(bar_width - 1, 0.5):.2f}" '
            f'height="{bar_height:.2f}" fill="#3d6fb6">'
            f"<title>{low:.4g}..{high:.4g} px: {count}</title></rect>"
        )
    ticks: list[str] = []
    for fraction in (0.0, 0.25, 0.5, 0.75, 1.0):
        value = bins_doc[0][0] + fraction * (bins_doc[-1][1] - bins_doc[0][0])
        x = margin_left + fraction * plot_width
        ticks.append(
            f'<line x1="{x:.2f}" y1="{margin_top + plot_height}" '
            f'x2="{x:.2f}" y2="{margin_top + plot_height + 6}" stroke="#444"/>'
        )
        ticks.append(
            f'<text x="{x:.2f}" y="{margin_top + plot_height + 22}" '
            f'font-family="sans-serif" font-size="12" text-anchor="middle">'
            f"{value:.3g}</text>"
        )
    value_ticks: list[str] = []
    for step in range(5):
        count = maximum * step / 4
        y = margin_top + plot_height * (1 - step / 4)
        value_ticks.append(
            f'<line x1="{margin_left - 6}" y1="{y:.2f}" x2="{margin_left}" '
            f'y2="{y:.2f}" stroke="#444"/>'
        )
        value_ticks.append(
            f'<text x="{margin_left - 10}" y="{y + 4:.2f}" font-family="sans-serif" '
            f'font-size="12" text-anchor="end">{count:.0f}</text>'
        )
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
        f'<text x="{margin_left}" y="28" font-family="sans-serif" font-size="16">'
        f"{title}</text>",
        f'<text x="{margin_left + plot_width / 2:.2f}" y="{height - 14}" '
        f'font-family="sans-serif" font-size="12" text-anchor="middle">{x_label}</text>',
        f'<g stroke="#bbbbbb" stroke-width="1">'
        f'<line x1="{margin_left}" y1="{margin_top + plot_height}" '
        f'x2="{margin_left + plot_width}" y2="{margin_top + plot_height}"/></g>',
        *ticks,
        *value_ticks,
        *bars,
        f'<text x="{margin_left}" y="{height - 28}" font-family="sans-serif" '
        f'font-size="11" fill="#555">n = {len(values)}</text>',
        "</svg>",
    ]
    return "\n".join(parts) + "\n"


def build(
    record_path: Path,
    *,
    table_path: Path,
    svg_path: Path,
    sidecar_path: Path,
    title: str,
    bins: int = 24,
) -> dict[str, Any]:
    """Build the table, the SVG and its provenance sidecar."""
    record = json.loads(record_path.read_text(encoding="utf-8"))
    rows = read_pairs(record)
    write_table(table_path, rows)
    magnitudes = [row["magnitude_px"] for row in rows]
    svg = render_histogram_svg(
        magnitudes,
        title=title,
        x_label="placement residual magnitude (px)",
        bins=bins,
    )
    svg_path.parent.mkdir(parents=True, exist_ok=True)
    svg_path.write_text(svg, encoding="utf-8")
    sidecar = {
        "schema": SIDECAR_SCHEMA,
        "table_schema": TABLE_SCHEMA,
        "record": {
            "path": str(record_path),
            "sha256": _sha256(record_path),
        },
        "registration_id": record.get("registration_id"),
        "calibration_id": record.get("calibration_id"),
        "pairs_total": len(record.get("pairs") or ()),
        "pairs_plotted": len(rows),
        "magnitude_px": {
            "median": sorted(magnitudes)[len(magnitudes) // 2],
            "max": max(magnitudes),
        },
        "table": {"path": str(table_path), "sha256": _sha256(table_path)},
        "svg": {"path": str(svg_path), "sha256": _sha256(svg_path)},
        "bins": bins,
        "slot": None,
        "slot_assignment": "pending author assignment",
    }
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    sidecar_path.write_text(json.dumps(sidecar, indent=2) + "\n", encoding="utf-8")
    return sidecar


def main(argv: list[str] | None = None) -> int:
    """Build a figure table, SVG and sidecar from a registration record."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("record", type=Path)
    parser.add_argument("--table", type=Path, required=True)
    parser.add_argument("--svg", type=Path, required=True)
    parser.add_argument("--sidecar", type=Path, required=True)
    parser.add_argument("--title", default="Registration placement residuals")
    parser.add_argument("--bins", type=int, default=24)
    arguments = parser.parse_args(argv)
    sidecar = build(
        arguments.record,
        table_path=arguments.table,
        svg_path=arguments.svg,
        sidecar_path=arguments.sidecar,
        title=arguments.title,
        bins=arguments.bins,
    )
    sys.stdout.write(json.dumps(sidecar, indent=2) + "\n")
    return 0


__all__ = [
    "SIDECAR_SCHEMA",
    "TABLE_COLUMNS",
    "TABLE_SCHEMA",
    "build",
    "histogram_bins",
    "main",
    "read_pairs",
    "render_histogram_svg",
    "write_table",
]


if __name__ == "__main__":
    raise SystemExit(main())

