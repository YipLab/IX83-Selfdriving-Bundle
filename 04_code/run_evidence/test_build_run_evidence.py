"""Hardware-free tests for the run-evidence builder.

Every fixture is a small synthetic run directory: a report, a strip record, two
position sidecars, a timing sidecar and the recorder's run manifest. Nothing here
reads a recorded Zarr store, opens a device or imports an acquisition host.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import build_run_evidence as builder
import pytest

ATTEMPT = "ix71-test-99"
STORE = "run_asi_pvcam_coordinated_broom_00001.zarr"


def _write(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
    return path


def _report(
    *,
    outcome: str = "success",
    frames: int = 3,
    error: str | None = None,
    route_as_text: bool = False,
) -> dict[str, Any]:
    start: Any = "-1.0 2.0" if route_as_text else [-1.0, 2.0]
    end: Any = "3.0 2.0" if route_as_text else [3.0, 2.0]
    return {
        "schema": "ix71.asi-broom-snake.v1",
        "confirmation_id": ATTEMPT,
        "anchor_xy_um": [0.0, 0.0],
        "planned_anchor_xy_um": [0.0, 0.0],
        "strip_span_um": 4.0,
        "field_um": 219.0,
        "overlap": 0.2,
        "span_y_um": 219.0,
        "setpoint_mw": 1.0,
        "route": [{"row": 0, "start_xy_um": start, "end_xy_um": end}],
        "session_outcome": outcome,
        "error": error,
        "document_counts": {"start": 1, "stop": 1},
        "stores": {f"{STORE}:mmcamera": [frames, 4, 4]},
    }


def _positions(frames: int = 3, *, gap: bool = False) -> dict[str, Any]:
    rows = []
    for index in range(frames):
        frame_id = index + 1
        rows.append(
            {
                "frame_id": frame_id,
                "array_index": index if not gap or index < 2 else index + 1,
                "time": 100.0 + index,
                "stage_xy_um": [float(index), 2.0],
                "pose_phase": "steady",
                "readbacks": {"asi_stage-xy-axis-x": float(index)},
            }
        )
    return {
        "schema": "redsun-planner.snap-position-association-v4",
        "store_uri": None,
        "exit_status": "success",
        "frames_written": frames,
        "stage_coordinate_basis": "stage-xy-reported-um",
        "stage_readback_keys": {"x": "asi_stage-xy-axis-x", "y": "asi_stage-xy-axis-y"},
        "camera_name": "mmcamera",
        "camera_binning_xy": [1, 1],
        "camera_exposure_ms": 10.0,
        "camera_properties": {"Binning": "1"},
        "camera_roi_sensor_pixels": {"x": 0, "y": 0, "width": 1200, "height": 1200},
        "camera_roi_binned_pixels": {"x": 0, "y": 0, "width": 1200, "height": 1200},
        "frames": rows,
    }


def _timing() -> dict[str, Any]:
    return {
        "schema": "ix71.broom-timing.v1",
        "timestamp_semantics": "service_arrival_after_core_frame_read",
        "clock": "python.time.monotonic_ns",
        "frame_metadata_semantics": "raw per-frame MMCore tags; not exposure intervals",
        "written_count": 3,
        "records": [],
    }


def _strips(
    *, complete: bool = True, statuses: list[str] | None = None
) -> dict[str, Any]:
    statuses = statuses or ["associated_receipt"] * 3
    return {
        "schema": "ix71.asi-broom-strips.v1",
        "confirmation_id": ATTEMPT,
        "coordinate_frame": "stage-xy-reported-um",
        "footprint_xy_um": [219.0, 219.0],
        "overlap": 0.2,
        "complete": complete,
        "interrupted": False,
        "anchor": {
            "anchor_xy_um": [0.0, 0.0],
            "return_attempted": True,
            "final_xy_um": [0.0, 0.0],
            "return_error_um": [0.1, -0.1],
        },
        "strips": [
            {
                "row": 0,
                "start_xy_um": [-1.0, 2.0],
                "end_xy_um": [3.0, 2.0],
                "terminal_state": "completed",
                "captured_count": 3,
                "pose_sources": ["camera_receipt"],
                "frame_poses": [{"status": status} for status in statuses],
            }
        ],
    }


def _run_tree(
    tmp_path: Path,
    *,
    report: dict[str, Any] | None = None,
    positions: dict[str, Any] | None = None,
    strips: dict[str, Any] | None = None,
    frames: int = 3,
    run_manifest: bool = True,
) -> tuple[Path, Path]:
    run_dir = tmp_path / "run"
    sidecar_dir = run_dir / "ix71-asi-sapphire-snake" / "2026-10-26" / "mmcamera"
    _write(run_dir / f"{ATTEMPT}-report.json", report or _report(frames=frames))
    _write(run_dir / "strips" / f"asi-broom-{ATTEMPT}-strips.json", strips or _strips())
    _write(
        sidecar_dir / f"{STORE.removesuffix('.zarr')}.positions.json",
        positions or _positions(frames),
    )
    _write(sidecar_dir / f"{STORE.removesuffix('.zarr')}.timing.json", _timing())
    if run_manifest:
        _write(
            sidecar_dir / "run_manifest_20261026T000000Z.json",
            {
                "schema": "ix71.broom-run-manifest.v1",
                "attempt_id": "0f3c9a52-test",
                "confirmation_id": ATTEMPT,
                "created_at": "2026-10-26T00:00:00+00:00",
                "strip_count": 1,
                "complete": True,
                "interrupted": False,
                "stores": [f"{STORE}"],
            },
        )
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(
        "schema_version: 1.0\n"
        "session: test-session\n"
        "services:\n"
        "  camera1_ioc:\n"
        "    plugin_id: mmcore-camera\n"
        "    args: {adapter: PVCAM, device: Camera-1}\n"
        "  asi_stage_ioc:\n"
        "    plugin_id: asi-serial-stage\n"
        "    args:\n"
        "      port: COM9\n"
        "      counts-per-um: 5.0\n"
        "      speed-mm-s: 0.1\n"
        "      backlash-mm: 0.016\n"
        "      absolute-takeup-um: 2.0\n"
        "      max-xy-offset-um: 1500\n",
        encoding="utf-8",
    )
    return run_dir, profile_path


def test_complete_record_states_every_field_with_its_source(tmp_path: Path) -> None:
    run_dir, profile = _run_tree(tmp_path)
    record = builder.build(run_dir, profile, [])

    assert record["schema"] == "ix71.run-evidence.v1"
    assert record["run"]["confirmation_id"]["value"] == ATTEMPT
    assert record["run"]["attempt_id"]["value"] == "0f3c9a52-test"
    assert record["run"]["session_outcome"]["value"] == "success"
    assert record["camera"]["exposure_ms"]["value"] == 10.0
    assert record["camera"]["exposure_ms"]["status"] == "declared"
    assert record["camera"]["exposure_ms"]["source"].endswith(".positions.json")
    assert record["camera"]["binning_xy"]["value"] == [1, 1]
    assert record["camera"]["adapter"]["value"] == "PVCAM"
    assert record["stage"]["counts_per_um"]["value"] == 5.0
    assert record["coordinates"]["basis"]["value"] == "stage-xy-reported-um"
    assert record["coordinates"]["pose_sources"]["value"] == ["camera_receipt"]
    assert record["coordinates"]["pose_phase_counts"]["value"] == {"steady": 3}
    assert record["coordinates"]["timestamp_semantics"]["value"] == (
        "service_arrival_after_core_frame_read"
    )
    assert record["coordinates"]["pose_clock"]["value"] == "python.time.monotonic_ns"
    assert record["geometry"]["route_rows"]["value"][0]["start_xy_um"] == [-1.0, 2.0]
    assert record["frames"]["accounting_ok"] is True
    assert record["blocking"] == []
    assert record["unresolved"] == [
        "illumination.mode",
        "illumination.objective",
        "calibration.id",
        "calibration.mode_match",
        "specimen.specimen_id",
        "specimen.field_id",
    ]
    assert record["identity_complete"] is False
    assert record["accepted"] is False
    digests = record["products"]["digests"]
    assert {entry["path"].rsplit("/", 1)[-1] for entry in digests} == {
        f"{ATTEMPT}-report.json",
        f"asi-broom-{ATTEMPT}-strips.json",
        "run_manifest_20261026T000000Z.json",
        f"{STORE.removesuffix('.zarr')}.positions.json",
        f"{STORE.removesuffix('.zarr')}.timing.json",
    }


def test_every_declared_or_derived_field_names_a_source(tmp_path: Path) -> None:
    run_dir, profile = _run_tree(tmp_path)
    record = builder.build(run_dir, profile, [])

    def check(node: Any, prefix: str = "") -> None:
        if isinstance(node, dict) and "status" in node and "value" in node:
            if node["status"] in {"declared", "derived"}:
                assert node["source"], f"{prefix} has no source"
            return
        if isinstance(node, dict):
            for key, value in node.items():
                check(value, f"{prefix}.{key}" if prefix else key)
        elif isinstance(node, list):
            for index, value in enumerate(node):
                check(value, f"{prefix}[{index}]")

    check(record, "record")


def test_failed_outcome_is_blocking_and_carries_the_reason(tmp_path: Path) -> None:
    run_dir, profile = _run_tree(
        tmp_path,
        report=_report(
            outcome="failed",
            error="pose association was required but failed for some frames",
        ),
    )
    record = builder.build(run_dir, profile, [])

    assert "run_outcome_failed" in record["blocking"]
    failed = next(
        item for item in record["findings"] if item["code"] == "run_outcome_failed"
    )
    assert "pose association" in failed["detail"]
    assert record["accepted"] is False


def test_frame_count_mismatch_is_blocking(tmp_path: Path) -> None:
    run_dir, profile = _run_tree(tmp_path, report=_report(frames=4))
    record = builder.build(run_dir, profile, [])

    assert "frame_count_mismatch" in record["blocking"]
    assert record["frames"]["accounting_ok"] is False
    assert record["frames"]["mismatches"][0]["sidecar_frames"] == 3
    assert record["frames"]["mismatches"][0]["store_frames"] == 4


def test_non_monotonic_frame_ids_are_blocking(tmp_path: Path) -> None:
    positions = _positions(3)
    positions["frames"][2]["frame_id"] = 1
    run_dir, profile = _run_tree(tmp_path, positions=positions)
    record = builder.build(run_dir, profile, [])

    assert "frame_id_not_monotonic" in record["blocking"]
    sidecar = record["frames"]["sidecars"][0]
    assert sidecar["frame_ids_strictly_increasing"] is False


def test_array_index_gap_is_a_warning_not_a_blocker(tmp_path: Path) -> None:
    run_dir, profile = _run_tree(tmp_path, positions=_positions(3, gap=True))
    record = builder.build(run_dir, profile, [])

    codes = {item["code"]: item["severity"] for item in record["findings"]}
    assert codes["array_index_gap"] == "warning"
    assert "array_index_gap" not in record["blocking"]


def test_pose_association_failures_are_reported_by_reason(tmp_path: Path) -> None:
    run_dir, profile = _run_tree(
        tmp_path,
        strips=_strips(
            statuses=[
                "associated_receipt",
                "associated_receipt",
                "X bracket 0.3s exceeds limit",
            ]
        ),
    )
    record = builder.build(run_dir, profile, [])

    finding = next(
        item
        for item in record["findings"]
        if item["code"] == "pose_association_incomplete"
    )
    assert finding["detail"] == {"X bracket 0.3s exceeds limit": 1}
    assert record["coordinates"]["frame_status_counts"]["value"] == {
        "associated_receipt": 2,
        "X bracket 0.3s exceeds limit": 1,
    }


def test_route_recorded_as_text_is_a_warning_and_the_strip_record_wins(
    tmp_path: Path,
) -> None:
    run_dir, profile = _run_tree(tmp_path, report=_report(route_as_text=True))
    record = builder.build(run_dir, profile, [])

    codes = {item["code"]: item["severity"] for item in record["findings"]}
    assert codes["route_encoding_inconsistent"] == "warning"
    assert record["geometry"]["route_rows"]["value"][0]["start_xy_um"] == [-1.0, 2.0]
    assert record["geometry"]["route_rows"]["status"] == "mismatch"


def test_missing_run_manifest_is_blocking_and_unresolved(tmp_path: Path) -> None:
    run_dir, profile = _run_tree(tmp_path, run_manifest=False)
    record = builder.build(run_dir, profile, [])

    assert "missing_run_manifest" in record["blocking"]
    assert record["run"]["attempt_id"]["status"] == "unresolved"
    assert "run.attempt_id" in record["unresolved"]


def test_complete_but_failed_is_reported_as_information(tmp_path: Path) -> None:
    run_dir, profile = _run_tree(
        tmp_path,
        report=_report(outcome="failed", error="stopped after a rejected pose"),
    )
    record = builder.build(run_dir, profile, [])

    codes = {item["code"]: item["severity"] for item in record["findings"]}
    assert codes["complete_but_failed"] == "info"
    assert record["run"]["complete"]["value"] is True


def test_missing_sidecar_is_refused(tmp_path: Path) -> None:
    run_dir, profile = _run_tree(tmp_path)
    for path in (run_dir / "ix71-asi-sapphire-snake").rglob("*.positions.json"):
        path.unlink()

    with pytest.raises(builder.EvidenceError, match="positions.json"):
        builder.build(run_dir, profile, [])


def test_ambiguous_acquisition_directory_is_refused(tmp_path: Path) -> None:
    run_dir, profile = _run_tree(tmp_path)
    (run_dir / "second-session").mkdir()
    with pytest.raises(builder.EvidenceError, match="exactly one acquisition"):
        builder.build(run_dir, profile, [])


def test_regeneration_is_deterministic_apart_from_the_timestamp(tmp_path: Path) -> None:
    run_dir, profile = _run_tree(tmp_path)
    first = builder.build(run_dir, profile, [])
    second = builder.build(run_dir, profile, [])
    first.pop("created_utc")
    second.pop("created_utc")
    assert first == second


def test_unreadable_profile_is_refused(tmp_path: Path) -> None:
    run_dir, profile = _run_tree(tmp_path)
    profile.write_text("not: [a profile", encoding="utf-8")
    with pytest.raises(builder.EvidenceError, match="not YAML"):
        builder.build(run_dir, profile, [])


@pytest.mark.parametrize("name", ["run", "profile"])
def test_missing_inputs_are_refused(tmp_path: Path, name: str) -> None:
    run_dir, profile = _run_tree(tmp_path)
    if name == "run":
        run_dir = tmp_path / "absent"
        with pytest.raises(builder.EvidenceError, match="run directory not found"):
            builder.build(run_dir, profile, [])
    else:
        profile = tmp_path / "absent.yaml"
        with pytest.raises(builder.EvidenceError, match="profile not found"):
            builder.build(run_dir, profile, [])
