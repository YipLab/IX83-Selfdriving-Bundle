"""Adapter from a recorded track export to the declared track table (Q08).

The [track coverage export](README.md) consumes a declared
``ix71.track-table.v1`` document. A tracking host writes its own table, so this
adapter is the seam: it reads a delimited track export, checks and normalizes the
columns it actually uses, and produces the declared document with the window and
identity the caller supplies.

What it checks is deliberately narrow, because a wrong guess about a foreign
export is worse than a refusal: a missing required column, a blank field, a
non-numeric coordinate, a duplicate ``(track, frame)`` pair, a negative frame and
an empty header are refused with the row number so the source can be fixed. It
does not rename or reorder columns silently, and it does not infer the frame
period, window, ROI or identity from the file.

The caller must state provenance it knows: the source path's digest is recorded
so a downstream figure can point at the exact input.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from tracks import SCHEMA

#: Columns the adapter reads. A source with different names must be renamed
#: first, so nothing here guesses a mapping.
COLUMNS = ("track_id", "frame", "x_px", "y_px")


def _sha256(path: Path) -> str:
    """Return the file digest the declared table records."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_rows(path: Path) -> list[dict[str, Any]]:
    """Read a delimited track export into declared point rows.

    Raises
    ------
    ValueError
        If the header is missing a required column, or a row is blank,
        non-numeric, negative or duplicated for its track.
    """
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        header = reader.fieldnames
        if not header:
            raise ValueError(f"{path} has no header row")
        missing = [name for name in COLUMNS if name not in header]
        if missing:
            raise ValueError(f"{path} is missing column(s): {', '.join(missing)}")
        rows: list[dict[str, Any]] = []
        seen: set[tuple[str, int]] = set()
        for line_number, row in enumerate(reader, start=2):
            track_id = (row.get("track_id") or "").strip()
            frame_text = (row.get("frame") or "").strip()
            x_text = (row.get("x_px") or "").strip()
            y_text = (row.get("y_px") or "").strip()
            if not track_id:
                raise ValueError(f"{path}:{line_number}: blank track_id")
            try:
                frame = int(frame_text)
            except ValueError as error:
                raise ValueError(
                    f"{path}:{line_number}: frame must be an integer"
                ) from error
            if frame < 0:
                raise ValueError(f"{path}:{line_number}: frame must be nonnegative")
            try:
                x_px = float(x_text)
                y_px = float(y_text)
            except ValueError as error:
                raise ValueError(
                    f"{path}:{line_number}: x_px and y_px must be numeric"
                ) from error
            key = (track_id, frame)
            if key in seen:
                raise ValueError(
                    f"{path}:{line_number}: duplicate point for {track_id!r} "
                    f"at frame {frame}"
                )
            seen.add(key)
            rows.append(
                {
                    "track_id": track_id,
                    "frame": frame,
                    "x_px": x_px,
                    "y_px": y_px,
                }
            )
    return rows


def build_table(
    rows: list[dict[str, Any]],
    *,
    specimen_id: str,
    field_id: str,
    frame_period_s: float,
    start_s: float,
    end_s: float,
    roi_x_px: tuple[float, float],
    roi_y_px: tuple[float, float],
    edge_margin_px: float = 2.0,
    source: Path | None = None,
) -> dict[str, Any]:
    """Assemble the declared track table document from declared rows."""
    for name, value in (
        ("specimen_id", specimen_id),
        ("field_id", field_id),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a nonempty string")
    tracks: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        tracks.setdefault(str(row["track_id"]), []).append(
            {"frame": int(row["frame"]), "x_px": float(row["x_px"]), "y_px": float(row["y_px"])}
        )
    track_documents = [
        {
            "track_id": track_id,
            "points": sorted(points, key=lambda point: point["frame"]),
        }
        for track_id, points in sorted(tracks.items())
    ]
    document: dict[str, Any] = {
        "schema": SCHEMA,
        "specimen_id": specimen_id,
        "field_id": field_id,
        "frame_period_s": float(frame_period_s),
        "window": {
            "start_s": float(start_s),
            "end_s": float(end_s),
            "roi_px": {"x": list(roi_x_px), "y": list(roi_y_px)},
            "edge_margin_px": float(edge_margin_px),
        },
        "tracks": track_documents,
    }
    if source is not None:
        document["source"] = {
            "path": str(source),
            "sha256": _sha256(source),
            "columns": list(COLUMNS),
        }
    return document


def main(argv: list[str] | None = None) -> int:
    """Convert one delimited track export into the declared table."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export", type=Path)
    parser.add_argument("--specimen", required=True)
    parser.add_argument("--field", required=True)
    parser.add_argument("--frame-period", type=float, required=True)
    parser.add_argument("--window", type=float, nargs=2, required=True)
    parser.add_argument("--roi-x", type=float, nargs=2, required=True)
    parser.add_argument("--roi-y", type=float, nargs=2, required=True)
    parser.add_argument("--edge-margin", type=float, default=2.0)
    parser.add_argument("--output", type=Path, default=None)
    arguments = parser.parse_args(argv)
    rows = read_rows(arguments.export)
    document = build_table(
        rows,
        specimen_id=arguments.specimen,
        field_id=arguments.field,
        frame_period_s=arguments.frame_period,
        start_s=arguments.window[0],
        end_s=arguments.window[1],
        roi_x_px=(arguments.roi_x[0], arguments.roi_x[1]),
        roi_y_px=(arguments.roi_y[0], arguments.roi_y[1]),
        edge_margin_px=arguments.edge_margin,
        source=arguments.export,
    )
    text = json.dumps(document, indent=2) + "\n"
    if arguments.output is None:
        sys.stdout.write(text)
    else:
        arguments.output.write_text(text, encoding="utf-8")
    return 0


__all__ = ["COLUMNS", "build_table", "main", "read_rows"]


if __name__ == "__main__":
    raise SystemExit(main())
