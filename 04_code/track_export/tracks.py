"""Per-track duration, censoring, lag-pair and support export (Q08).

Q08 asks for calibrated track/window/control exports built on RTASPT's existing
analysis, with duration/censoring and lag-pair counts retained, support masks
kept, and edge exits classified separately from particle disappearance. RTASPT
owns tracking, fitting, diffusion and localization precision; this module owns
none of that. It consumes a declared track table and reports what a downstream
figure needs to know about *coverage*: how long each track was observed, whether
it was censored by the acquisition window, how many frame pairs exist at each
lag, which frame runs support it, and whether its first or last detection sits at
the ROI edge.

Two deliberate limits:

* Nothing here is a diffusion estimate. A lag-pair count says how many pairs a
  fit *could* use; it does not say the displacement is diffusive.
* Edge proximity is not a disappearance mechanism. An edge flag records that the
  track's end sits within the declared margin of the ROI boundary, so a reader
  can exclude it; absence without edge contact is a different event and is not
  classified here.

The module imports only the standard library, so it can run beside any RTASPT
environment without importing it.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import Any, Literal

SCHEMA = "ix71.track-table.v1"
EXPORT_SCHEMA = "ix71.track-export.v1"

Severity = Literal["blocking", "warning", "info"]
BLOCKING = "blocking"
WARNING = "warning"
INFO = "info"

Censoring = Literal["none", "start", "end", "both"]


@dataclass(frozen=True)
class Issue:
    """One typed finding about a track table or its export."""

    code: str
    severity: Severity
    detail: str
    track_id: str | None = None

    def to_document(self) -> dict[str, Any]:
        """Return the JSON-safe issue."""
        return {
            "code": self.code,
            "severity": self.severity,
            "detail": self.detail,
            "track_id": self.track_id,
        }


@dataclass(frozen=True)
class TrackWindow:
    """Acquisition window and ROI a track table is measured inside."""

    start_s: float
    end_s: float
    roi_x_px: tuple[float, float]
    roi_y_px: tuple[float, float]
    edge_margin_px: float = 2.0

    def __post_init__(self) -> None:
        """Check the window is ordered and the ROI is nonempty."""
        if not isfinite(self.start_s) or not isfinite(self.end_s):
            raise ValueError("window bounds must be finite")
        if self.end_s <= self.start_s:
            raise ValueError("window end must be after its start")
        for name, bounds in (("roi_x_px", self.roi_x_px), ("roi_y_px", self.roi_y_px)):
            if len(bounds) != 2 or any(
                isinstance(value, bool) or not isinstance(value, (int, float))
                for value in bounds
            ):
                raise ValueError(f"{name} must be a numeric pair")
            low, high = float(bounds[0]), float(bounds[1])
            if not isfinite(low) or not isfinite(high) or high <= low:
                raise ValueError(f"{name} must be an ordered finite pair")
        if not isfinite(self.edge_margin_px) or self.edge_margin_px < 0:
            raise ValueError("edge_margin_px must be finite and nonnegative")

    @property
    def duration_s(self) -> float:
        """Return the observed window length."""
        return self.end_s - self.start_s


def _number(value: Any, name: str) -> float:
    """Return a finite float, refusing bools and non-finite values."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a real number")
    number = float(value)
    if not isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _frame(value: Any, name: str) -> int:
    """Return a nonnegative integer frame index."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer")
    return value


def _at_edge(
    x_px: float, y_px: float, window: TrackWindow
) -> bool:
    """Return whether a position sits within the margin of the ROI boundary."""
    margin = window.edge_margin_px
    return (
        x_px <= window.roi_x_px[0] + margin
        or x_px >= window.roi_x_px[1] - margin
        or y_px <= window.roi_y_px[0] + margin
        or y_px >= window.roi_y_px[1] - margin
    )


@dataclass(frozen=True)
class TrackExport:
    """One track's coverage summary, without any motion model."""

    track_id: str
    frames: tuple[int, ...]
    duration_s: float
    gaps: int
    censoring: Censoring
    lag_pairs: dict[int, int]
    support_runs: tuple[tuple[int, int], ...]
    edge_at_start: bool
    edge_at_end: bool


def export_track(
    track_id: str,
    points: list[dict[str, Any]],
    *,
    window: TrackWindow,
    frame_period_s: float,
    maximum_lag_frames: int = 3,
) -> tuple[TrackExport, list[Issue]]:
    """Summarize one track's observation coverage and lag support."""
    issues: list[Issue] = []
    if not isinstance(track_id, str) or not track_id.strip():
        raise ValueError("track_id must be a nonempty string")
    if (
        isinstance(maximum_lag_frames, bool)
        or not isinstance(maximum_lag_frames, int)
        or maximum_lag_frames < 1
    ):
        raise ValueError("maximum_lag_frames must be a positive integer")
    period = _number(frame_period_s, "frame_period_s")
    if period <= 0:
        raise ValueError("frame_period_s must be positive")
    if not points:
        issues.append(
            Issue("track_without_points", BLOCKING, "track has no points", track_id)
        )
        return (
            TrackExport(
                track_id=track_id,
                frames=(),
                duration_s=0.0,
                gaps=0,
                censoring="none",
                lag_pairs={},
                support_runs=(),
                edge_at_start=False,
                edge_at_end=False,
            ),
            issues,
        )

    frames: list[int] = []
    positions: list[tuple[float, float]] = []
    for index, point in enumerate(points):
        if not isinstance(point, dict):
            raise TypeError("each track point must be an object")
        frame = _frame(point.get("frame"), f"points[{index}].frame")
        x_px = _number(point.get("x_px"), f"points[{index}].x_px")
        y_px = _number(point.get("y_px"), f"points[{index}].y_px")
        frames.append(frame)
        positions.append((x_px, y_px))

    if any(right <= left for left, right in zip(frames, frames[1:])):
        issues.append(
            Issue(
                "frames_not_increasing",
                BLOCKING,
                "points must arrive in strictly increasing frame order",
                track_id,
            )
        )
        return (
            TrackExport(
                track_id=track_id,
                frames=tuple(frames),
                duration_s=0.0,
                gaps=0,
                censoring="none",
                lag_pairs={},
                support_runs=(),
                edge_at_start=False,
                edge_at_end=False,
            ),
            issues,
        )

    gaps = sum(
        1 for left, right in zip(frames, frames[1:]) if right - left > 1
    )
    if gaps:
        issues.append(
            Issue(
                "track_frames_missing",
                INFO,
                f"{gaps} frame gap(s); lag pairs count only observed frames",
                track_id,
            )
        )
    duration_s = (frames[-1] - frames[0]) * period
    if duration_s > window.duration_s + 1e-9:
        issues.append(
            Issue(
                "track_exceeds_window",
                WARNING,
                f"track spans {duration_s:.3f} s against a "
                f"{window.duration_s:.3f} s window",
                track_id,
            )
        )

    censored_start = (frames[0] * period) <= window.start_s + 1e-9
    censored_end = (frames[-1] * period) >= window.end_s - 1e-9
    censoring: Censoring = (
        "both"
        if censored_start and censored_end
        else "start"
        if censored_start
        else "end"
        if censored_end
        else "none"
    )

    lag_pairs: dict[int, int] = {}
    present = set(frames)
    for lag in range(1, maximum_lag_frames + 1):
        lag_pairs[lag] = sum(1 for frame in frames if frame + lag in present)

    runs: list[tuple[int, int]] = []
    run_start = frames[0]
    previous = frames[0]
    for frame in frames[1:]:
        if frame - previous > 1:
            runs.append((run_start, previous))
            run_start = frame
        previous = frame
    runs.append((run_start, previous))

    return (
        TrackExport(
            track_id=track_id,
            frames=tuple(frames),
            duration_s=duration_s,
            gaps=gaps,
            censoring=censoring,
            lag_pairs=lag_pairs,
            support_runs=tuple(runs),
            edge_at_start=_at_edge(*positions[0], window),
            edge_at_end=_at_edge(*positions[-1], window),
        ),
        issues,
    )


def export_document(document: Any) -> dict[str, Any]:
    """Check a declared track table and return its coverage export."""
    if not isinstance(document, dict):
        raise ValueError("a track table must be a JSON object")
    issues: list[Issue] = []
    if document.get("schema") != SCHEMA:
        issues.append(
            Issue(
                "schema_missing",
                BLOCKING,
                f"expected schema {SCHEMA!r}, found {document.get('schema')!r}",
            )
        )
    period = document.get("frame_period_s")
    try:
        frame_period_s = _number(period, "frame_period_s")
        if frame_period_s <= 0:
            raise ValueError("frame_period_s must be positive")
    except (TypeError, ValueError) as error:
        issues.append(Issue("frame_period_invalid", BLOCKING, str(error)))
        frame_period_s = 1.0

    window_doc = document.get("window")
    window: TrackWindow | None = None
    if not isinstance(window_doc, dict):
        issues.append(Issue("window_missing", BLOCKING, "window is required"))
    else:
        try:
            roi = window_doc.get("roi_px")
            if not isinstance(roi, dict):
                raise ValueError("window.roi_px must be an object")
            window = TrackWindow(
                start_s=_number(window_doc.get("start_s"), "window.start_s"),
                end_s=_number(window_doc.get("end_s"), "window.end_s"),
                roi_x_px=tuple(roi.get("x")) if isinstance(roi.get("x"), list) else (),
                roi_y_px=tuple(roi.get("y")) if isinstance(roi.get("y"), list) else (),
                edge_margin_px=_number(
                    window_doc.get("edge_margin_px", 2.0), "window.edge_margin_px"
                ),
            )
        except (TypeError, ValueError) as error:
            issues.append(Issue("window_invalid", BLOCKING, str(error)))
            window = None

    tracks_doc = document.get("tracks")
    track_documents = tracks_doc if isinstance(tracks_doc, list) else []
    if not isinstance(tracks_doc, list):
        issues.append(Issue("tracks_missing", BLOCKING, "tracks must be a list"))

    exports: list[TrackExport] = []
    if window is not None:
        seen: set[str] = set()
        for track in track_documents:
            if not isinstance(track, dict):
                issues.append(
                    Issue("track_invalid", BLOCKING, "each track must be an object")
                )
                continue
            track_id = track.get("track_id")
            if not isinstance(track_id, str) or not track_id.strip():
                issues.append(
                    Issue("track_id_missing", BLOCKING, "track_id is required")
                )
                continue
            if track_id in seen:
                issues.append(
                    Issue("track_id_duplicate", BLOCKING, f"repeated {track_id!r}")
                )
                continue
            seen.add(track_id)
            points = track.get("points")
            if not isinstance(points, list):
                issues.append(
                    Issue(
                        "track_points_missing",
                        BLOCKING,
                        "points must be a list",
                        track_id,
                    )
                )
                continue
            export, track_issues = export_track(
                track_id,
                points,
                window=window,
                frame_period_s=frame_period_s,
            )
            exports.append(export)
            issues.extend(track_issues)

    total_pairs = sum(export.lag_pairs.get(1, 0) for export in exports)
    censored = sum(1 for export in exports if export.censoring != "none")
    edge_ends = sum(1 for export in exports if export.edge_at_end)
    gaps = sum(export.gaps for export in exports)
    return {
        "schema": EXPORT_SCHEMA,
        "source_schema": document.get("schema"),
        "specimen_id": document.get("specimen_id"),
        "field_id": document.get("field_id"),
        "window": (
            None
            if window is None
            else {
                "start_s": window.start_s,
                "end_s": window.end_s,
                "duration_s": window.duration_s,
                "roi_x_px": list(window.roi_x_px),
                "roi_y_px": list(window.roi_y_px),
                "edge_margin_px": window.edge_margin_px,
            }
        ),
        "frame_period_s": frame_period_s,
        "tracks": [
            {
                "track_id": export.track_id,
                "frames": list(export.frames),
                "duration_s": export.duration_s,
                "gaps": export.gaps,
                "censoring": export.censoring,
                "lag_pairs": {str(lag): count for lag, count in export.lag_pairs.items()},
                "support_runs": [list(run) for run in export.support_runs],
                "edge_at_start": export.edge_at_start,
                "edge_at_end": export.edge_at_end,
            }
            for export in exports
        ],
        "summary": {
            "tracks": len(exports),
            "frames": sum(len(export.frames) for export in exports),
            "pairs_at_lag_1": total_pairs,
            "censored_tracks": censored,
            "edge_ended_tracks": edge_ends,
            "gap_events": gaps,
        },
        "issues": [issue.to_document() for issue in issues],
        "accepted": not any(issue.severity == BLOCKING for issue in issues),
    }


def main(argv: list[str] | None = None) -> int:
    """Export one declared track table and print or write its coverage report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("track_table", type=Path)
    parser.add_argument("--output", type=Path, default=None)
    arguments = parser.parse_args(argv)
    document = json.loads(arguments.track_table.read_text(encoding="utf-8"))
    report = export_document(document)
    text = json.dumps(report, indent=2) + "\n"
    if arguments.output is None:
        sys.stdout.write(text)
    else:
        arguments.output.write_text(text, encoding="utf-8")
    return 0 if report["accepted"] else 1


__all__ = [
    "EXPORT_SCHEMA",
    "SCHEMA",
    "Issue",
    "TrackExport",
    "TrackWindow",
    "export_document",
    "export_track",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
