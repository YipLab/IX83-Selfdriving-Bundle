"""Export review figures and workflow diagrams for bounded scan records.

Geometry fixtures are illustrative. Run overlays are read from saved JSON and
are labeled from their recorded provenance; this utility never contacts devices.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from source_bootstrap import enable_source_tree

BUNDLE = enable_source_tree()

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon, Rectangle
from planner.bounded_scanning import (
    BroomScanPlan,
    ConfirmedBoundary,
    CornerObservation,
    SnapScanPlan,
    plan_broom_scan,
    plan_snap_scan,
)

WORKFLOW = """%%{init: {'themeCSS': '.nodeLabel, .cluster-label { font-size: 22px !important; } .edgeLabel { font-size: 17px !important; }'}}%%
flowchart LR
  subgraph BIO["Biological replay"]
    R["Replay frames"] --> I["Intensity and confidence"] --> P["Speed proposal"]
  end
  P --> H["Single run owner: bundle host"]
  H --> D["Demo/mock devices"]
  H --> S["Storage and action journal"]
  classDef component fill:#f3f6fa,stroke:#40566d,stroke-width:1px
  class BIO,R,I,P,H,D,S component
"""

WORKFLOW_MD = (
    """# Bounded scan workflow

The biological replay stage analyzes saved frames and publishes typed intensity
and confidence observations. A speed proposal is advisory. The bundle host is
the single run owner: it validates proposals against the confirmed geometry,
execution limits and declared capabilities before any action. Device bindings
and storage/action journaling remain under that host.

```mermaid
"""
    + WORKFLOW
    + """```

**Evidence boundary:** this diagram records workflow ownership; it is not proof
of hardware acceptance. Biological replay, intensity/confidence calculations,
and speed proposals do not command devices. A proposal does not execute until
the host accepts and dispatches it under its policy.
"""
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_boundary(run_dir: Path) -> tuple[ConfirmedBoundary, Path]:
    source = run_dir / "corner_confirmations.json"
    data = json.loads(source.read_text(encoding="utf-8"))
    corners = tuple(
        CornerObservation(
            tuple(item["corner_xy_um"]),
            item["confirmed"],
            item["confirmation_id"],
            tuple(item["readback_xy_um"]),
        )
        for item in data["corners"]
    )
    frame, boundary_id = data["coordinate_frame"], data["boundary_id"]
    boundary = (
        ConfirmedBoundary.from_opposite_corners(
            *corners, coordinate_frame=frame, boundary_id=boundary_id
        )
        if len(corners) == 2
        else ConfirmedBoundary.from_polygon(
            corners, coordinate_frame=frame, boundary_id=boundary_id
        )
    )
    return boundary, source


def _run_geometry(
    run_dir: Path,
) -> tuple[ConfirmedBoundary, dict[str, Any], dict[str, Any], list[Path]]:
    boundary, corner_path = _load_boundary(run_dir)
    scan_path = run_dir / "scan.json"
    scan = json.loads(scan_path.read_text(encoding="utf-8"))
    return (
        boundary,
        scan,
        json.loads(corner_path.read_text(encoding="utf-8")),
        [corner_path, scan_path],
    )


def _fixture_boundaries() -> tuple[ConfirmedBoundary, ConfirmedBoundary]:
    rectangle = tuple(
        CornerObservation(p, True, f"fixture-rect-{i}", p)
        for i, p in enumerate(((10, 20), (250, 170)))
    )
    polygon = tuple(
        CornerObservation(p, True, f"fixture-poly-{i}", p)
        for i, p in enumerate(((290, 20), (510, 30), (485, 185), (275, 160)))
    )
    return (
        ConfirmedBoundary.from_opposite_corners(
            *rectangle,
            coordinate_frame="fixture-stage-xy",
            boundary_id="fixture-rectangle",
        ),
        ConfirmedBoundary.from_polygon(
            polygon,
            coordinate_frame="fixture-stage-xy",
            boundary_id="fixture-quadrilateral",
        ),
    )


def _points_from_snap(scan: dict[str, Any], *, completed: bool) -> list[tuple[float, float]]:
    records = (
        scan.get("positions", [])
        if completed
        else scan.get("resolved", {}).get("planned_positions", [])
    )
    result = []
    for item in records:
        xy = item.get("stage_xy_um") if completed else None
        if xy is None:
            xy = (item.get("x_um"), item.get("y_um"))
        if len(xy) == 2 and all(isinstance(v, (int, float)) and math.isfinite(v) for v in xy):
            result.append((float(xy[0]), float(xy[1])))
    return result


def _points_from_broom(scan: dict[str, Any]) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for action in scan.get("actions", []):
        readback = action.get("readback", {})
        samples = readback.get("samples", []) if isinstance(readback, dict) else []
        for sample in samples:
            xyz = sample.get("readback_xyz_um")
            if (
                xyz
                and len(xyz) >= 2
                and all(isinstance(v, (int, float)) and math.isfinite(v) for v in xyz[:2])
            ):
                points.append((float(xyz[0]), float(xyz[1])))
    return points


def _polygon(ax, points: tuple[tuple[float, float], ...], **kwargs: Any) -> None:
    ax.add_patch(Polygon(points, closed=True, **kwargs))


def _draw_case(
    ax,
    boundary: ConfirmedBoundary,
    mode: str,
    *,
    run: dict[str, Any] | None = None,
    run_kind: str | None = None,
) -> dict[str, Any]:
    footprint, overlap, parameter_source = _run_geometry_parameters(run)
    illustrative_parameters = "unknown" in parameter_source
    planned_label = (
        "illustrative geometry path" if illustrative_parameters else "planned snap snake"
    )
    center_label = (
        "safe center region (illustrative)" if illustrative_parameters else "safe center region"
    )
    footprint_label = (
        "camera footprint (illustrative)" if illustrative_parameters else "camera footprint"
    )
    planned: list[tuple[float, float]] = []
    _polygon(
        ax,
        boundary.vertices_xy_um,
        facecolor="#dce9f3",
        edgecolor="#254f70",
        linewidth=1.8,
        alpha=0.5,
    )
    if mode == "snap":
        plan: SnapScanPlan | BroomScanPlan = plan_snap_scan(boundary, footprint, overlap)
        planned = [(p.x_um, p.y_um) for p in plan.positions]
        ax.plot(
            [p[0] for p in planned],
            [p[1] for p in planned],
            color="#1673a5",
            linewidth=1.0,
            marker="o",
            markersize=2.7,
            label=planned_label,
            zorder=3,
        )
        overlay = _points_from_snap(run, completed=True) if run and run_kind == "snap" else []
    else:
        plan = plan_broom_scan(boundary, footprint, overlap, serpentine=(mode == "broom snake"))
        for index, strip in enumerate(plan.strips):
            ax.annotate(
                "",
                xy=strip.end_xy_um,
                xytext=strip.start_xy_um,
                arrowprops={"arrowstyle": "->", "color": "#1673a5", "lw": 1.2},
            )
            if index == 0:
                ax.plot(
                    [],
                    [],
                    color="#1673a5",
                    label="illustrative broom strip"
                    if illustrative_parameters
                    else "planned broom strip",
                )
        ax.plot(
            [p[0] for p in plan.travel_xy_um],
            [p[1] for p in plan.travel_xy_um],
            color="#1673a5",
            alpha=0.45,
            linewidth=0.8,
            linestyle="--",
            label="bounded transit",
        )
        recorded_strips = (run or {}).get("geometry", {}).get("strips", [])
        matches_recorded_geometry = len(recorded_strips) == len(plan.strips) and all(
            all(
                math.isclose(float(actual), float(expected), abs_tol=1e-8)
                for actual, expected in zip(
                    (*recorded["start_xy_um"], *recorded["end_xy_um"]),
                    (*strip.start_xy_um, *strip.end_xy_um),
                    strict=True,
                )
            )
            for recorded, strip in zip(recorded_strips, plan.strips, strict=True)
        )
        overlay = (
            _points_from_broom(run)
            if run and run_kind == "broom" and matches_recorded_geometry
            else []
        )
    _polygon(
        ax,
        plan.center_boundary_xy_um,
        facecolor="#79bd8a",
        edgecolor="#327746",
        linewidth=1.0,
        alpha=0.18,
        linestyle="--",
        label=center_label,
    )
    if planned:
        x, y = planned[len(planned) // 2]
        ax.add_patch(
            Rectangle(
                (x - footprint[0] / 2, y - footprint[1] / 2),
                *footprint,
                facecolor="#f0b44d",
                edgecolor="#9a6000",
                alpha=0.23,
                linewidth=1.2,
                label=footprint_label,
            )
        )
    elif isinstance(plan, BroomScanPlan) and plan.strips:
        x, y = plan.strips[0].start_xy_um
        ax.add_patch(
            Rectangle(
                (x - footprint[0] / 2, y - footprint[1] / 2),
                *footprint,
                facecolor="#f0b44d",
                edgecolor="#9a6000",
                alpha=0.23,
                linewidth=1.2,
                label=footprint_label,
            )
        )
    if overlay:
        ax.plot(
            [p[0] for p in overlay],
            [p[1] for p in overlay],
            color="#c1362d",
            marker="x",
            linewidth=1.0,
            markersize=4,
            label="run readbacks" if run_kind == "broom" else "completed snaps",
            zorder=5,
        )
    for i, p in enumerate(boundary.vertices_xy_um):
        ax.scatter(*p, color="#17202a", s=13, zorder=6)
        ax.annotate(f"R{i + 1}", p, xytext=(3, 3), textcoords="offset points", fontsize=7)
    ax.set_aspect("equal", adjustable="datalim")
    ax.set_xlabel("stage X (µm)")
    ax.set_ylabel("stage Y (µm)")
    ax.grid(True, linewidth=0.35, alpha=0.45)
    ax.legend(fontsize=6, loc="best")
    if illustrative_parameters:
        ax.text(
            0.02,
            0.02,
            "run footprint/overlap unknown; geometry shown is illustrative",
            transform=ax.transAxes,
            fontsize=6,
            color="#7a3e00",
            va="bottom",
        )
    return {
        "plan_type": mode,
        "planned_count": len(plan.positions)
        if isinstance(plan, SnapScanPlan)
        else len(plan.strips),
        "actual_overlay_points": len(overlay),
        "footprint_xy_um": footprint,
        "overlap": overlap,
        "geometry_parameter_source": parameter_source,
        "center_boundary_xy_um": plan.center_boundary_xy_um,
        "coverage_claim": plan.coverage_claim,
    }


def _source_provenance(scan: dict[str, Any]) -> dict[str, str]:
    resolved = scan.get("resolved", {})
    backend = (
        scan.get("backend")
        or scan.get("capture_mode")
        or resolved.get("backend")
        or resolved.get("capture_mode")
    )
    if backend is None:
        binding = scan.get("execution_bindings")
        providers = (
            ", ".join(
                str(item.get("provider", "unknown")) for item in binding if isinstance(item, dict)
            )
            if isinstance(binding, list)
            else ""
        )
        suffix = f"; declared binding provider(s): {providers}" if providers else ""
        return {
            "execution_provenance": "unknown",
            "claim": "saved record does not identify mock versus physical execution" + suffix,
        }
    return {
        "execution_provenance": str(backend),
        "claim": "recorded execution provenance only; this exporter does not establish physical acceptance",
    }


def _run_kind(scan: dict[str, Any]) -> str | None:
    resolved = scan.get("resolved", {})
    raw = (
        scan.get("mode")
        or scan.get("workflow")
        or resolved.get("mode")
        or resolved.get("demo_mode")
    )
    lowered = str(raw).lower() if raw is not None else ""
    return "broom" if "broom" in lowered else "snap" if "snap" in lowered else None


def _find_value(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        if key in value:
            return value[key]
        for child in value.values():
            found = _find_value(child, key)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_value(child, key)
            if found is not None:
                return found
    return None


def _run_geometry_parameters(
    scan: dict[str, Any] | None,
) -> tuple[tuple[float, float], float, str]:
    if scan is None:
        return (36.0, 28.0), 0.2, "illustrative geometry fixture"
    footprint = _find_value(scan, "footprint_xy_um")
    overlap = _find_value(scan, "overlap")
    valid_footprint = (
        isinstance(footprint, (list, tuple))
        and len(footprint) == 2
        and all(isinstance(v, (int, float)) and math.isfinite(v) and v > 0 for v in footprint)
    )
    valid_overlap = (
        isinstance(overlap, (int, float)) and math.isfinite(overlap) and 0 <= overlap < 1
    )
    if valid_footprint and valid_overlap:
        return (
            (float(footprint[0]), float(footprint[1])),
            float(overlap),
            "saved run parameters",
        )
    return (
        (36.0, 28.0),
        0.2,
        "illustrative 36 x 28 µm footprint; actual run footprint/overlap unknown",
    )


def export(output_dir: Path, run_dirs: list[Path], geometry_only: bool) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    runs = [_run_geometry(path) for path in run_dirs]
    boundaries = list(_fixture_boundaries()) if geometry_only or not runs else []
    if runs:
        boundaries.extend(item[0] for item in runs)
    if not boundaries:
        boundaries = list(_fixture_boundaries())
    rows = len(boundaries)
    fig, axes = plt.subplots(rows, 3, figsize=(15, max(5, rows * 4.5)), squeeze=False)
    entries: list[dict[str, Any]] = []
    titles = ("Snap snake", "Broom alternating", "Broom same-direction + flyback")
    for row, boundary in enumerate(boundaries):
        run_info = (
            runs[row - (2 if geometry_only else 0)]
            if row >= (2 if geometry_only else 0) and runs
            else None
        )
        for col, mode in enumerate(("snap", "broom snake", "broom unidirectional")):
            scan, run_kind = (run_info[1], _run_kind(run_info[1])) if run_info else (None, None)
            item = _draw_case(axes[row][col], boundary, mode, run=scan, run_kind=run_kind)
            identity = boundary.boundary_id
            short_identity = f"{identity[:25]}…{identity[-8:]}" if len(identity) > 40 else identity
            axes[row][col].set_title(
                f"{boundary.kind.replace('_', ' ')} · {titles[col]}\n{short_identity}",
                fontsize=9,
            )
            item.update(
                {
                    "boundary_id": boundary.boundary_id,
                    "boundary_kind": boundary.kind,
                    "coordinate_frame": boundary.coordinate_frame,
                    "confirmed_readback_vertices_xy_um": boundary.vertices_xy_um,
                }
            )
            if run_info:
                source = run_info[3]
                item.update(_source_provenance(scan or {}))
                item["source_run_dir"] = str(run_dirs[row - (2 if geometry_only else 0)])
                item["source_scan_sha256"] = _sha256(source[1])
                item["source_corner_confirmations_sha256"] = _sha256(source[0])
                item["run_id"] = (scan or {}).get("run_id") or "unknown"
                item["specimen_id"] = (scan or {}).get("specimen_id") or "unknown"
            else:
                item.update(
                    {
                        "execution_provenance": "geometry_fixture_only",
                        "claim": "illustrative geometry; no device execution or physical acceptance",
                    }
                )
            entries.append(item)
    fig.suptitle("Corner-confirmed bounded scan geometry", fontsize=15)
    fig.text(
        0.5,
        0.012,
        "Green: feasible camera-center region after footprint erosion. Orange: full camera footprint. "
        "Polygon edge fill is not claimed; red overlays require a saved run record.",
        ha="center",
        fontsize=9,
    )
    fig.tight_layout(rect=(0, 0.04, 1, 0.96))
    figure_base = output_dir / "bounded_scan_comparison"
    fig.savefig(figure_base.with_suffix(".png"), dpi=180, bbox_inches="tight")
    fig.savefig(figure_base.with_suffix(".svg"), bbox_inches="tight")
    plt.close(fig)
    (output_dir / "workflow.mmd").write_text(WORKFLOW, encoding="utf-8")
    (output_dir / "workflow.md").write_text(WORKFLOW_MD, encoding="utf-8")
    source_records = []
    for run_dir, (_, scan, _, paths) in zip(run_dirs, runs, strict=True):
        source_records.append(
            {
                "run_dir": str(run_dir),
                "run_id": scan.get("run_id") or "unknown",
                "specimen_id": scan.get("specimen_id") or "unknown",
                "scan_sha256": _sha256(paths[1]),
                "corner_confirmations_sha256": _sha256(paths[0]),
                **_source_provenance(scan),
            }
        )
    manifest = {
        "schema": "ix83-bounded-scan-evidence-v1",
        "generated_from_geometry_fixtures": geometry_only,
        "physical_acceptance_claimed": False,
        "coverage_caveat": "plans constrain full camera footprints; polygon edge fill is not claimed",
        "sources": source_records,
        "figures": [asdict_record(entry) for entry in entries],
        "outputs": [
            "bounded_scan_comparison.png",
            "bounded_scan_comparison.svg",
            "workflow.mmd",
            "workflow.md",
        ],
    }
    (output_dir / "figure_manifest.json").write_text(
        json.dumps(manifest, indent=2, allow_nan=False), encoding="utf-8"
    )


def asdict_record(value: dict[str, Any]) -> dict[str, Any]:
    def convert(item: Any) -> Any:
        if isinstance(item, tuple):
            return [convert(part) for part in item]
        if isinstance(item, list):
            return [convert(part) for part in item]
        if isinstance(item, dict):
            return {key: convert(part) for key, part in item.items()}
        return item

    return convert(value)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-dir",
        type=Path,
        action="append",
        default=[],
        help="saved demo run directory; repeat to overlay multiple runs",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--geometry-only",
        action="store_true",
        help="export illustrative two/four-corner fixtures",
    )
    args = parser.parse_args(argv)
    for run_dir in args.run_dir:
        if (
            not (run_dir / "corner_confirmations.json").is_file()
            or not (run_dir / "scan.json").is_file()
        ):
            parser.error(
                f"run directory must contain corner_confirmations.json and scan.json: {run_dir}"
            )
    export(args.output_dir, args.run_dir, args.geometry_only)


if __name__ == "__main__":
    main()
