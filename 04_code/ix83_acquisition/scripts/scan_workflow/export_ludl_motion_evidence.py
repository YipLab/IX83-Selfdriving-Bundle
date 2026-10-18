"""Render hardware-free figures and workflow notes from a Ludl motion record.

This exporter only reads a saved JSON record. Positions and velocities are
host-side readbacks sampled at irregular poll times, not encoder/exposure
synchronized measurements. Requested speed properties are nominal settings.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

WORKFLOW = """%%{init: {'themeCSS': '.nodeLabel, .cluster-label { font-size: 22px !important; } .edgeLabel { font-size: 17px !important; }'}}%%
flowchart LR
  V[\"Validate saved record and bounds\"] --> M[\"Finite MOVE command\"]
  M --> A[\"Command acknowledgement\"]
  A --> P[\"Asynchronous busy and XY polling\"]
  P --> C{\"Complete?\"}
  C -->|yes| D[\"Record completion and readback\"]
  C -->|timeout or error| S[\"Stop if available; reconcile outcome\"]
  S --> R[\"No automatic retry\"]
  classDef component fill:#f3f6fa,stroke:#40566d,stroke-width:1px
  class V,M,A,P,C,D,S,R component
"""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value))


def points_xy(items: list[dict[str, Any]]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rows = [
        (float(item["elapsed_s"]), float(item["x_um"]), float(item["y_um"]))
        for item in items
        if all(f in item and finite(item[f]) for f in ("elapsed_s", "x_um", "y_um"))
    ]
    if not rows:
        return np.array([]), np.array([]), np.array([])
    arr = np.asarray(rows, dtype=float)
    order = np.argsort(arr[:, 0], kind="stable")
    arr = arr[order]
    # Duplicate host timestamps cannot define a finite difference. Keep the
    # final readback at each timestamp, preserving chronological acquisition.
    _, reverse_indices = np.unique(arr[::-1, 0], return_index=True)
    arr = arr[np.sort(len(arr) - 1 - reverse_indices)]
    return arr[:, 0], arr[:, 1], arr[:, 2]


def windowed_velocity(
    t: np.ndarray, p: np.ndarray, window_s: float = 1.0
) -> tuple[np.ndarray, np.ndarray]:
    """Robust local slope over ~1 s, avoiding adjacent-poll noise estimates."""
    if len(t) < 2:
        return np.array([]), np.array([])
    centers, values = [], []
    for i, center in enumerate(t):
        lo = np.searchsorted(t, center - window_s / 2, side="left")
        hi = np.searchsorted(t, center + window_s / 2, side="right")
        if hi - lo < 2:
            # Expand to nearest neighboring samples until a slope is defined.
            lo, hi = max(0, i - 1), min(len(t), i + 2)
        if hi - lo < 2:
            continue
        tt, pp = t[lo:hi], p[lo:hi]
        # Median of all pairwise slopes resists an isolated noisy readback.
        slopes = [
            (pp[j] - pp[k]) / (tt[j] - tt[k])
            for k in range(len(tt))
            for j in range(k + 1, len(tt))
            if tt[j] > tt[k]
        ]
        if slopes:
            centers.append(float(center))
            values.append(float(np.median(slopes)))
    return np.asarray(centers), np.asarray(values)


def draw(record: dict[str, Any], input_path: Path, output: Path) -> dict[str, Any]:
    origin = np.asarray(record["origin_xy_um"], dtype=float)
    limits = np.asarray(record["limits_xy_um"], dtype=float)
    if (
        origin.shape != (2,)
        or limits.shape != (2, 2)
        or not np.isfinite(origin).all()
        or not np.isfinite(limits).all()
    ):
        raise ValueError("origin_xy_um and limits_xy_um must be finite XY values")
    if np.any(limits[:, 0] >= limits[:, 1]):
        raise ValueError("each XY lower limit must be below its upper limit")
    relative_limits = limits - origin[:, None]

    runs = record.get("runs", [])
    if not runs:
        raise ValueError("record contains no runs")
    colors = plt.get_cmap("tab10")
    run_labels = {str(run.get("name", f"run {i + 1}")): f"R{i + 1}" for i, run in enumerate(runs)}
    fig, axes = plt.subplots(2, 2, figsize=(13, 9), constrained_layout=True)
    ax_xy, ax_pos, ax_vel, ax_time = axes.flat
    ax_xy.add_patch(
        plt.Rectangle(
            (relative_limits[0, 0], relative_limits[1, 0]),
            relative_limits[0, 1] - relative_limits[0, 0],
            relative_limits[1, 1] - relative_limits[1, 0],
            facecolor="#e7eef5",
            edgecolor="#40566d",
            alpha=0.7,
            label="configured XY limits",
        )
    )
    ax_xy.scatter([0], [0], marker="+", s=90, color="black", label="initial origin")
    summary_runs = []
    path_x: list[float] = []
    path_y: list[float] = []
    for idx, run in enumerate(runs):
        color = colors(idx % 10)
        t, x, y = points_xy(run.get("trace", []))
        xr, yr = x - origin[0], y - origin[1]
        label = str(run.get("name", f"run {idx + 1}"))
        plot_label = run_labels[label]
        if len(t):
            path_x.extend(xr.tolist())
            path_y.extend(yr.tolist())
            ax_xy.plot(
                xr, yr, marker=".", markersize=4, linewidth=1.1, color=color, label=plot_label
            )
            ax_pos.plot(
                t, xr, marker=".", markersize=3, linewidth=1, color=color, label=f"{plot_label} X"
            )
            ax_pos.plot(
                t,
                yr,
                marker=".",
                markersize=3,
                linewidth=1,
                linestyle="--",
                color=color,
                alpha=0.8,
                label=f"{plot_label} Y",
            )
        for axis_name, p in (("X", xr), ("Y", yr)):
            tv, v = windowed_velocity(t, p)
            if len(tv):
                ax_vel.plot(
                    tv,
                    v,
                    color=color,
                    linestyle="-" if axis_name == "X" else "--",
                    label=f"{plot_label} {axis_name}",
                )
        for update in run.get("speed_updates", []):
            if finite(update.get("elapsed_s")):
                when = float(update["elapsed_s"])
                ax_pos.axvline(when, color=color, alpha=0.22, linewidth=0.9)
                ax_vel.axvline(when, color=color, alpha=0.22, linewidth=0.9)
                ax_pos.text(
                    when,
                    0.98 - 0.12 * (idx % 4),
                    f"{plot_label}: Speed={update.get('readback', update.get('requested', '?'))} nominal",
                    transform=ax_pos.get_xaxis_transform(),
                    rotation=0,
                    va="top",
                    ha="center",
                    fontsize=7,
                    color=color,
                )

        ack = run.get("command_ack_elapsed_s")
        elapsed = float(t[-1]) if len(t) else None
        summary_runs.append(
            {
                "name": label,
                "status": run.get("status"),
                "kind": run.get("kind"),
                "command_ack_elapsed_s": ack,
                "last_trace_elapsed_s": elapsed,
                "core_wait_timeout_ms": record.get("core_wait_timeout_ms"),
                "serial_answer_timeout_ms": record.get("serial_answer_timeout_ms"),
                "trace_samples": len(t),
                "error": run.get("error") or run.get("result", {}).get("error"),
            }
        )
        if finite(ack):
            ax_time.scatter(
                [idx],
                [float(ack)],
                marker="o",
                color=color,
                label="acknowledgement" if idx == 0 else None,
            )
        if elapsed is not None:
            ax_time.scatter(
                [idx],
                [elapsed],
                marker="s",
                color=color,
                label="last trace sample" if idx == 0 else None,
            )

    # Keep the three timeout concepts visibly distinct even when a particular
    # run's elapsed time is much shorter than their reference lines.
    for seconds, label, color, style in (
        (5.0, "Core wait timeout demonstration (5 s)", "#b22222", ":"),
        (60.0, "Core wait timeout setting (60 s)", "#7b3294", "--"),
        (50.0, "Serial answer timeout (50 s)", "#008837", "-."),
    ):
        ax_time.axhline(seconds, color=color, linestyle=style, linewidth=1.1, label=label)

    ax_xy.set(
        xlabel="X from initial origin (µm)",
        ylabel="Y from initial origin (µm)",
        title="Bounded XY readback path",
        xlim=(relative_limits[0, 0], relative_limits[0, 1]),
        ylim=(relative_limits[1, 0], relative_limits[1, 1]),
        aspect="equal",
    )
    ax_xy.legend(fontsize=7, loc="upper right", title="Full configured bounds", title_fontsize=7)
    if path_x:
        # A full instrument envelope can be millimeters wide while this
        # diagnostic move is tens of micrometers. Keep the envelope visible
        # and add a clearly marked zoom so the readback path remains legible.
        inset = ax_xy.inset_axes([0.08, 0.08, 0.52, 0.52])
        inset.plot(path_x, path_y, marker="o", markersize=2.5, linewidth=1, color="#1673a5")
        inset.scatter([0], [0], marker="+", s=45, color="black")
        dx = max(2.0, (max(path_x) - min(path_x)) * 0.2)
        dy = max(2.0, (max(path_y) - min(path_y)) * 0.3)
        inset.set_xlim(min(path_x) - dx, max(path_x) + dx)
        inset.set_ylim(min(path_y) - dy, max(path_y) + dy)
        inset.set_aspect("equal", adjustable="datalim")
        inset.set_title("Readback detail", fontsize=8)
        inset.tick_params(labelsize=6)
        inset.grid(alpha=0.2)
    ax_pos.set(
        xlabel="Host elapsed time (s)",
        ylabel="Position from origin (µm)",
        title="Position vs host readback time",
    )
    ax_pos.legend(fontsize=7, ncol=2, loc="best", title="Solid X, dashed Y", title_fontsize=7)
    ax_vel.set(
        xlabel="Host elapsed time (s)",
        ylabel="Estimated velocity (µm/s)",
        title="Robust ~1 s windowed finite-difference estimate",
    )
    ax_vel.legend(fontsize=7, ncol=3, loc="best", title="Solid X, dashed Y", title_fontsize=7)
    ax_time.set(
        xlabel="Run index",
        ylabel="Elapsed time (s)",
        title="Acknowledgement and observed duration vs timeout settings",
        xticks=list(range(len(runs))),
        xticklabels=[run_labels[str(r.get("name", f"run {i + 1}"))] for i, r in enumerate(runs)],
    )
    ax_time.legend(fontsize=7, loc="best")
    fig.suptitle("Ludl motion evidence — host-side observations", fontsize=15)
    output.mkdir(parents=True, exist_ok=True)
    for ext in ("png", "svg"):
        fig.savefig(output / f"ludl_motion_evidence.{ext}", dpi=180 if ext == "png" else None)
    plt.close(fig)

    (output / "workflow.mmd").write_text(WORKFLOW, encoding="utf-8")
    (output / "workflow.md").write_text(
        "# Ludl timeout investigation workflow\n\n"
        "```mermaid\n" + WORKFLOW + "```\n\n"
        "The bundle host validates bounds before issuing a finite MOVE. It records command acknowledgement separately from asynchronous busy/XY polling. "
        "Completion requires an observed terminal state; timeout or error leads to stop when available and outcome reconciliation. "
        "No automatic retry is authorized by this workflow.\n\n"
        "**Timing distinction:** Core wait timeout is recorded independently from the serial answer timeout. The 5 s Core timeout demonstration, 60 s Core setting, "
        "and 50 s serial answer timeout are separate settings and must not be conflated. A command acknowledgement, polling duration, or property update does not by itself measure motion.\n\n"
        "**Measurement limits:** XY values are host readbacks at irregular polling timestamps. They are not encoder synchronized to camera exposure and may include communication/readback noise. "
        "Velocity uses a robust approximately 1 s local finite-difference window, not adjacent-sample differences. Speed property updates are nominal requested/readback settings, not measured physical velocity.\n",
        encoding="utf-8",
    )

    source_files = [{"path": str(input_path), "sha256": sha256(input_path)}]
    exporter = Path(__file__).resolve()
    source_files.append({"path": str(exporter), "sha256": sha256(exporter)})
    for item in record.get("source_files", []):
        raw = Path(item["path"])
        candidate = (input_path.parent / raw).resolve() if not raw.is_absolute() else raw
        entry = {"path": str(raw), "exists": candidate.is_file()}
        if candidate.is_file():
            entry["sha256"] = sha256(candidate)
        source_files.append(entry)
    manifest = {
        "schema": "ix83-ludl-motion-evidence-v1",
        "physical_acceptance_claimed": False,
        "record": str(input_path),
        "origin_xy_um": origin.tolist(),
        "limits_xy_um": limits.tolist(),
        "limits_relative_to_origin_xy_um": relative_limits.tolist(),
        "initial_settings": record.get("initial_settings"),
        "core_wait_timeout_ms": record.get("core_wait_timeout_ms"),
        "serial_answer_timeout_ms": record.get("serial_answer_timeout_ms"),
        "runs": summary_runs,
        "figure_run_labels": run_labels,
        "restoration": record.get("restoration"),
        "source_files": source_files,
        "measurement_caveat": "irregular host readback timestamps; not encoder/exposure synchronized; speed properties are nominal settings",
        "velocity_method": "median pairwise slope within approximately 1 s local window",
        "figures": [
            "ludl_motion_evidence.png",
            "ludl_motion_evidence.svg",
            "workflow.mmd",
            "workflow.md",
        ],
    }
    (output / "figure_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--record", required=True, type=Path, help="saved hardware-free JSON evidence record"
    )
    parser.add_argument(
        "--output", type=Path, help="output directory; defaults to the record's directory"
    )
    args = parser.parse_args()
    input_path = args.record.resolve()
    record = json.loads(input_path.read_text(encoding="utf-8"))
    manifest = draw(record, input_path, (args.output or input_path.parent).resolve())
    print(
        json.dumps(
            {
                "output": str((args.output or input_path.parent).resolve()),
                "runs": len(manifest["runs"]),
                "source_sha256": manifest["source_files"][0]["sha256"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
