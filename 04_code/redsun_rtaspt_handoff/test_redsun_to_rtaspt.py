"""Hardware-free tests for the Redsun-to-RTASPT adapter.

Every test uses a synthetic Zarr v3 store plus a synthetic
``redsun-planner.snap-position-association-v4`` sidecar under ``tmp_path``. No
camera, stage, laser, GPU or GUI is touched, and nothing outside ``tmp_path`` is
written.

Run with the Redsun application environment (it owns ``zarr``)::

    python -m pytest test_redsun_to_rtaspt.py -q
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
import pytest
import yaml

import redsun_to_rtaspt as r2r
import verify_product

DATA_KEY = "mmcamera-buffer"
#: Invertible stage->pixel declaration used by tests that are not about the transform.
MATRIX = "0.0,-5.5,0.0;-5.5,0.0,0.0"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def serpentine_positions(
    n_slow: int,
    n_fast: int,
    *,
    step: float = 10.0,
    step_x: float | None = None,
    step_y: float | None = None,
    x0: float = 100.0,
    y0: float = 200.0,
) -> list[tuple[float, float]]:
    """Positions of Redsun's grid walk: fast along y, alternating per column."""
    delta_x = step if step_x is None else step_x
    delta_y = step if step_y is None else step_y
    points: list[tuple[float, float]] = []
    for slow in range(n_slow):
        for fast in range(n_fast):
            index = fast if slow % 2 == 0 else n_fast - 1 - fast
            points.append((x0 + slow * delta_x, y0 + index * delta_y))
    return points


def frame_data(frames: int, height: int, width: int, dtype: str) -> np.ndarray:
    base = np.arange(height * width, dtype=np.int64).reshape(height, width) % 97
    return np.stack(
        [(index * 100 + base) % 60000 for index in range(frames)]
    ).astype(np.uint16)


def make_snapshot(
    root: Path,
    positions: list[tuple[float, float]],
    *,
    shape: tuple[int, int] = (8, 8),
    dtype: str = "uint16",
    data_key: str = DATA_KEY,
    sidecar_patch: dict | None = None,
    times: list[float] | None = None,
    store_name: str = "grid",
) -> dict:
    """Write a Zarr v3 store, its sidecar, and return the paths and the pixels."""
    import zarr

    height, width = shape
    store = root / f"{store_name}.zarr"
    group = zarr.open_group(str(store), mode="w")
    frames = len(positions)
    if dtype == "uint16":
        shape_tuple: tuple[int, ...] = (frames, height, width)
        np_dtype = "uint16"
        data = frame_data(frames, height, width, np_dtype)
    elif dtype == "float16":
        shape_tuple = (frames, height, width)
        np_dtype = "float16"
        data = np.zeros(shape_tuple, dtype=np_dtype)
    elif dtype == "2d":
        shape_tuple = (height, width)
        np_dtype = "uint16"
        data = frame_data(1, height, width, np_dtype)[0]
    else:
        raise AssertionError(f"unsupported fixture dtype {dtype!r}")
    chunks = (1, height, width) if len(shape_tuple) == 3 else (height, width)
    array = group.create_array(data_key, shape=shape_tuple, dtype=np_dtype, chunks=chunks)
    array[:] = data

    stamps = times if times is not None else [1_792_817_000.0 + 1.25 * i for i in range(frames)]
    sidecar_payload = {
        "schema": r2r.SIDECAR_SCHEMA,
        "data_key": data_key,
        "run_uid": "00000000-0000-0000-0000-00000000test",
        "exit_status": "success",
        "frames_written": frames,
        "stage_coordinate_basis": "stage-xy-reported-um",
        "stage_readback_keys": {
            "x": "asi_stage-xy-axis-x",
            "y": "asi_stage-xy-axis-y",
        },
        "camera_name": "mmcamera",
        "camera_binning_xy": [1, 1],
        "camera_exposure_ms": 10.0,
        "frames": [
            {
                "frame_id": index + 1,
                "array_index": index,
                "time": stamps[index],
                "stage_xy_um": [float(x), float(y)],
                "readbacks": {
                    "asi_stage-xy-axis-x": float(x),
                    "asi_stage-xy-axis-y": float(y),
                },
            }
            for index, (x, y) in enumerate(positions)
        ],
        "camera_roi_binned_pixels": {"x": 0, "y": 0, "width": width, "height": height},
    }
    if sidecar_patch:
        sidecar_payload.update(sidecar_patch)
    sidecar = root / f"{store_name}.positions.json"
    sidecar.write_text(json.dumps(sidecar_payload, indent=2), encoding="utf-8")
    return {
        "store": store,
        "sidecar": sidecar,
        "data": data,
        "positions": positions,
        "array": array,
    }


def run_cli(*args: str) -> int:
    return r2r.main([str(item) for item in args])


def read_frames(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def read_request(out: Path) -> dict:
    return yaml.safe_load((out / "request.yaml").read_text(encoding="utf-8"))


def read_handoff(out: Path) -> dict:
    return json.loads((out / "handoff.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_handoff_writes_pinned_request_and_single_series_movie(tmp_path, capsys):
    import tifffile

    snapshot = make_snapshot(tmp_path, serpentine_positions(2, 2))
    out = tmp_path / "handoff"
    assert run_cli(
        snapshot["store"], snapshot["sidecar"], out, "--transform-matrix", MATRIX
    ) == 0
    for name in ("request.yaml", "frames.csv", "provenance.json", "handoff.json"):
        assert (out / name).is_file(), name
    movies = list(out.glob("*_tiles.ome.tif"))
    assert len(movies) == 1

    request = read_request(out)
    assert request["order"] == "as_given"
    assert request["kind"] == "settled"
    assert request["tile_shape"] == [8, 8]
    assert request["images"]["kind"] == "movie"
    assert request["images"]["path"] == movies[0].name
    assert request["frames"] == "frames.csv"
    assert request["transform"]["matrix"] == [
        [0.0, -5.5, 0.0],
        [-5.5, 0.0, 0.0],
    ]
    assert request["duplicates"]["gate_px"] == 6.0

    # One OME series with a leading T axis is what TiffSeriesReader needs.
    with tifffile.TiffFile(movies[0]) as handle:
        assert len(handle.series) == 1
        assert handle.series[0].axes == "TYX"
        assert handle.series[0].shape == (4, 8, 8)
        assert len(handle.pages) == 4

    frames = read_frames(out / "frames.csv")
    assert [row["frame"] for row in frames] == ["0", "1", "2", "3"]
    for row, (x, y) in zip(frames, snapshot["positions"]):
        assert float(row["x_um"]) == pytest.approx(x)
        assert float(row["y_um"]) == pytest.approx(y)
    assert float(frames[0]["time_s"]) == 0.0
    assert float(frames[1]["time_s"]) == pytest.approx(1.25, abs=1e-6)

    read = tifffile.imread(movies[0])
    assert np.array_equal(read, snapshot["data"])

    handoff = read_handoff(out)
    assert handoff["schema"] == r2r.HANDOFF_SCHEMA
    assert handoff["frame_count"] == 4
    assert handoff["order"]["request_order"] == "as_given"
    assert handoff["request"]["order"] == "as_given"
    assert handoff["tile_shape"] == [8, 8]
    assert handoff["source"]["store_sha256"]
    assert handoff["source"]["sidecar_sha256"]
    provenance = json.loads((out / "provenance.json").read_text(encoding="utf-8"))
    assert provenance["source"]["frame_count"] == 4
    assert provenance["order"]["mode"] == "as_given"
    assert provenance["outputs"]["movie"]["sha256"]
    assert provenance["hardware_commands_issued"] is False
    assert provenance["pixels_synthesised"] is False


def test_request_carries_only_schema_keys(tmp_path):
    snapshot = make_snapshot(tmp_path, serpentine_positions(2, 2))
    out = tmp_path / "handoff"
    assert run_cli(snapshot["store"], snapshot["sidecar"], out, "--transform-matrix", MATRIX) == 0
    request = read_request(out)
    assert set(request) <= r2r.RTASPT_REQUEST_KEYS
    assert "anisotropy" not in request
    assert "tracking" not in request
    assert "window" not in request
    assert "identity" not in request
    assert "linking" not in request


def test_lattice_spacing_is_row_then_column(tmp_path):
    snapshot = make_snapshot(
        tmp_path, serpentine_positions(3, 4, step_x=12.5, step_y=7.5)
    )
    out = tmp_path / "handoff"
    assert run_cli(snapshot["store"], snapshot["sidecar"], out, "--transform-matrix", MATRIX) == 0
    request = read_request(out)
    # build_tiles reads lattice_spacing_um as (row spacing, column spacing):
    # rows come from y, columns from x, so the declared pair is [dy, dx].
    assert request["lattice_spacing_um"] == pytest.approx([7.5, 12.5])


# ---------------------------------------------------------------------------
# Order handling
# ---------------------------------------------------------------------------


def test_order_raster_permutes_movie_with_table_and_keeps_request_pinned(tmp_path):
    import tifffile

    snapshot = make_snapshot(tmp_path, serpentine_positions(3, 3))
    out = tmp_path / "handoff"
    assert run_cli(
        snapshot["store"],
        snapshot["sidecar"],
        out,
        "--transform-matrix",
        MATRIX,
        "--order",
        "raster",
    ) == 0
    request = read_request(out)
    assert request["order"] == "as_given", "the request must never say raster"
    handoff = read_handoff(out)
    emitted = handoff["order"]["emitted_frame_order"]
    assert handoff["order"]["mode"] == "raster"
    assert emitted != list(range(9)), "a serpentine grid must reorder under raster"

    frames = read_frames(out / "frames.csv")
    for row, source in zip(frames, emitted):
        x, y = snapshot["positions"][source]
        assert float(row["x_um"]) == pytest.approx(x)
        assert float(row["y_um"]) == pytest.approx(y)

    movie = next(out.glob("*_tiles.ome.tif"))
    read = tifffile.imread(movie)
    for page, source in enumerate(emitted):
        assert np.array_equal(read[page], snapshot["data"][source])


def test_order_serpentine_on_serpentine_store_is_identity(tmp_path):
    snapshot = make_snapshot(tmp_path, serpentine_positions(2, 3))
    out = tmp_path / "handoff"
    assert run_cli(
        snapshot["store"], snapshot["sidecar"], out, "--transform-matrix", MATRIX, "--order", "serpentine"
    ) == 0
    assert read_handoff(out)["order"]["emitted_frame_order"] == list(range(6))


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


def test_missing_sidecar_refused(tmp_path):
    snapshot = make_snapshot(tmp_path, serpentine_positions(2, 2))
    snapshot["sidecar"].unlink()
    assert run_cli(snapshot["store"], snapshot["sidecar"], tmp_path / "out", "--transform-matrix", MATRIX) == 2
    assert not (tmp_path / "out").exists()


def test_frame_count_mismatch_refused(tmp_path, capsys):
    positions = serpentine_positions(2, 2)
    snapshot = make_snapshot(tmp_path, positions, sidecar_patch={"frames_written": 3})
    assert run_cli(snapshot["store"], snapshot["sidecar"], tmp_path / "out", "--transform-matrix", MATRIX) == 2
    assert "E-FRAME-COUNT" in capsys.readouterr().err


def test_sidecar_listing_fewer_frames_refused(tmp_path, capsys):
    import zarr

    positions = serpentine_positions(2, 2)
    snapshot = make_snapshot(tmp_path, positions)
    payload = json.loads(snapshot["sidecar"].read_text(encoding="utf-8"))
    payload["frames"] = payload["frames"][:3]
    snapshot["sidecar"].write_text(json.dumps(payload), encoding="utf-8")
    assert run_cli(snapshot["store"], snapshot["sidecar"], tmp_path / "out", "--transform-matrix", MATRIX) == 2
    assert "E-FRAME-COUNT" in capsys.readouterr().err


def test_duplicate_stage_position_refused(tmp_path, capsys):
    positions = serpentine_positions(2, 2)
    positions[2] = positions[1]
    snapshot = make_snapshot(tmp_path, positions)
    assert run_cli(snapshot["store"], snapshot["sidecar"], tmp_path / "out", "--transform-matrix", MATRIX) == 2
    assert "E-POSITION-DUPLICATE" in capsys.readouterr().err


def test_non_monotonic_stage_order_refused(tmp_path, capsys):
    positions = serpentine_positions(3, 3)
    positions[0], positions[1] = positions[1], positions[0]
    snapshot = make_snapshot(tmp_path, positions)
    assert run_cli(snapshot["store"], snapshot["sidecar"], tmp_path / "out", "--transform-matrix", MATRIX) == 2
    assert "E-POSITION-TRAVERSAL" in capsys.readouterr().err


def test_incomplete_grid_refused(tmp_path, capsys):
    positions = serpentine_positions(2, 2) + [(300.0, 400.0)]
    snapshot = make_snapshot(tmp_path, positions)
    assert run_cli(snapshot["store"], snapshot["sidecar"], tmp_path / "out", "--transform-matrix", MATRIX) == 2
    assert "E-LATTICE" in capsys.readouterr().err


def test_time_order_refused(tmp_path, capsys):
    snapshot = make_snapshot(
        tmp_path,
        serpentine_positions(2, 3),
        times=[100.0, 90.0, 80.0, 70.0, 60.0, 50.0],
    )
    assert run_cli(snapshot["store"], snapshot["sidecar"], tmp_path / "out", "--transform-matrix", MATRIX) == 2
    assert "E-TIME-ORDER" in capsys.readouterr().err


def test_interrupted_run_refused(tmp_path, capsys):
    snapshot = make_snapshot(
        tmp_path, serpentine_positions(2, 2), sidecar_patch={"exit_status": "failed"}
    )
    assert run_cli(snapshot["store"], snapshot["sidecar"], tmp_path / "out", "--transform-matrix", MATRIX) == 2
    assert "E-SIDECAR-STATUS" in capsys.readouterr().err


def test_unsupported_sidecar_schema_refused(tmp_path, capsys):
    snapshot = make_snapshot(
        tmp_path,
        serpentine_positions(2, 2),
        sidecar_patch={"schema": "redsun-planner.snap-position-association-v2"},
    )
    assert run_cli(snapshot["store"], snapshot["sidecar"], tmp_path / "out", "--transform-matrix", MATRIX) == 2
    assert "E-SIDECAR-SCHEMA" in capsys.readouterr().err


def test_dtype_without_tiff_sample_format_refused(tmp_path, capsys):
    snapshot = make_snapshot(tmp_path, serpentine_positions(2, 2), dtype="float16")
    assert run_cli(snapshot["store"], snapshot["sidecar"], tmp_path / "out", "--transform-matrix", MATRIX) == 2
    assert "E-DTYPE" in capsys.readouterr().err


def test_two_dimensional_store_refused(tmp_path, capsys):
    snapshot = make_snapshot(tmp_path, serpentine_positions(2, 2), dtype="2d")
    assert run_cli(snapshot["store"], snapshot["sidecar"], tmp_path / "out", "--transform-matrix", MATRIX) == 2
    assert "E-SHAPE" in capsys.readouterr().err


def test_camera_roi_mismatch_refused(tmp_path, capsys):
    snapshot = make_snapshot(
        tmp_path,
        serpentine_positions(2, 2),
        sidecar_patch={"camera_roi_binned_pixels": {"x": 0, "y": 0, "width": 16, "height": 16}},
    )
    assert run_cli(snapshot["store"], snapshot["sidecar"], tmp_path / "out", "--transform-matrix", MATRIX) == 2
    assert "E-ROI" in capsys.readouterr().err


def test_missing_data_key_refused(tmp_path, capsys):
    snapshot = make_snapshot(tmp_path, serpentine_positions(2, 2))
    assert run_cli(
        snapshot["store"], snapshot["sidecar"], tmp_path / "out", "--transform-matrix", MATRIX, "--data-key", "other"
    ) == 2
    assert "E-DATA-KEY" in capsys.readouterr().err


def test_no_transform_declaration_refused(tmp_path, capsys):
    snapshot = make_snapshot(tmp_path, serpentine_positions(2, 2))
    assert run_cli(snapshot["store"], snapshot["sidecar"], tmp_path / "out") == 2
    assert "E-TRANSFORM-MISSING" in capsys.readouterr().err


def test_singular_matrix_refused(tmp_path, capsys):
    snapshot = make_snapshot(tmp_path, serpentine_positions(2, 2))
    assert run_cli(
        snapshot["store"], snapshot["sidecar"], tmp_path / "out", "--transform-matrix", "1,2,0;2,4,0"
    ) == 2
    assert "E-TRANSFORM-MATRIX" in capsys.readouterr().err


def test_crop_outside_plane_refused(tmp_path, capsys):
    snapshot = make_snapshot(tmp_path, serpentine_positions(2, 2))
    assert run_cli(
        snapshot["store"], snapshot["sidecar"], tmp_path / "out", "--transform-matrix", MATRIX, "--crop", "0:16,0:4"
    ) == 2
    assert "E-CROP" in capsys.readouterr().err


def test_existing_output_requires_force(tmp_path, capsys):
    snapshot = make_snapshot(tmp_path, serpentine_positions(2, 2))
    out = tmp_path / "handoff"
    assert run_cli(snapshot["store"], snapshot["sidecar"], out, "--transform-matrix", MATRIX) == 0
    assert run_cli(snapshot["store"], snapshot["sidecar"], out, "--transform-matrix", MATRIX) == 2
    assert "E-OUTPUT-EXISTS" in capsys.readouterr().err
    assert run_cli(snapshot["store"], snapshot["sidecar"], out, "--transform-matrix", MATRIX, "--force") == 0


def test_buffer_directory_accepted_as_store_path(tmp_path):
    """The caller may pass the .zarr group or the buffer array dir beneath it."""
    snapshot = make_snapshot(tmp_path, serpentine_positions(2, 2))
    out = tmp_path / "handoff"
    assert run_cli(
        snapshot["store"] / DATA_KEY, snapshot["sidecar"], out, "--transform-matrix", MATRIX
    ) == 0
    movies = list(out.glob("*_tiles.ome.tif"))
    assert [item.name for item in movies] == ["grid_tiles.ome.tif"]
    handoff = read_handoff(out)
    assert handoff["source"]["store"].endswith(DATA_KEY)
    assert handoff["request"]["order"] == "as_given"


def test_registration_discovered_from_buffer_directory_form(tmp_path):
    known = np.array([[0.05, -4.0, 3.0], [-4.0, -0.05, 7.0]])
    snapshot = make_snapshot(tmp_path / "run" / "buffer", serpentine_positions(2, 2))
    _write_registration(tmp_path / "run", snapshot, known)
    out = tmp_path / "handoff"
    assert run_cli(snapshot["store"] / DATA_KEY, snapshot["sidecar"], out) == 0
    assert np.allclose(read_request(out)["transform"]["matrix"], known, atol=1e-8)


# ---------------------------------------------------------------------------
# Crop
# ---------------------------------------------------------------------------


def test_crop_applies_to_movie_and_tile_shape(tmp_path):
    import tifffile

    snapshot = make_snapshot(tmp_path, serpentine_positions(2, 2))
    out = tmp_path / "handoff"
    assert run_cli(
        snapshot["store"], snapshot["sidecar"], out, "--transform-matrix", MATRIX, "--crop", "2:6,1:5"
    ) == 0
    request = read_request(out)
    assert request["tile_shape"] == [4, 4]
    handoff = read_handoff(out)
    assert handoff["crop"] == {"y": [2, 6], "x": [1, 5], "source_plane": [8, 8]}
    movie = next(out.glob("*_tiles.ome.tif"))
    read = tifffile.imread(movie)
    assert read.shape == (4, 4, 4)
    assert np.array_equal(read, snapshot["data"][:, 2:6, 1:5])


# ---------------------------------------------------------------------------
# Registration-derived transform
# ---------------------------------------------------------------------------


def _write_registration(
    root: Path,
    snapshot: dict,
    matrix: np.ndarray,
    *,
    sidecar_sha: str | None = None,
    residual_rms_px: float = 0.25,
) -> Path:
    calibrated = root / "calibrated"
    calibrated.mkdir(parents=True, exist_ok=True)
    placements = calibrated / "registered_snap_frame_placements.csv"
    x0, y0 = snapshot["positions"][0]
    with placements.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(
            [
                "frame_index",
                "graph_component",
                "registration_origin_x_px",
                "registration_origin_y_px",
            ]
        )
        for index, (x, y) in enumerate(snapshot["positions"]):
            dx, dy = x - x0, y - y0
            px = matrix[0][0] * dx + matrix[0][1] * dy + matrix[0][2]
            py = matrix[1][0] * dx + matrix[1][1] * dy + matrix[1][2]
            writer.writerow([index, 0, f"{px:.9f}", f"{py:.9f}"])
    digest = sidecar_sha or r2r.sha256_file(snapshot["sidecar"])
    report = {
        "schema": "redsun-searching-imaging.snap-mosaic-report-v1",
        "registration_id": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "source_positions_path": str(snapshot["sidecar"]),
        "source_sidecar_sha256": digest,
        "frame_placements_file": placements.name,
        "edge_residual_summary_px": {
            "rms": residual_rms_px,
            "maximum": 0.6,
            "accepted_edge_count": 12,
        },
        "placement_graph": {"component_count": 1},
    }
    report_path = calibrated / "registered_snap_mosaic_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report_path


def test_transform_fitted_from_saved_registration(tmp_path):
    known = np.array([[0.05, -4.0, 3.0], [-4.0, -0.05, 7.0]])
    snapshot = make_snapshot(tmp_path / "run" / "buffer", serpentine_positions(3, 3))
    _write_registration(tmp_path / "run", snapshot, known)
    out = tmp_path / "handoff"
    assert run_cli(snapshot["store"], snapshot["sidecar"], out) == 0
    request = read_request(out)
    assert np.allclose(request["transform"]["matrix"], known, atol=1e-8)
    assert request["duplicates"]["registration_residual_px"] == pytest.approx(0.25)
    handoff = read_handoff(out)
    assert handoff["transform"]["source"].startswith("registration-fit:")
    assert handoff["transform"]["calibration_id"].startswith(
        "mosaic-affine-fit-from-registration-0123456789ab"
    )
    assert handoff["redsun_preprocessing_id"] is None


def test_stale_registration_refused(tmp_path, capsys):
    known = np.array([[0.05, -4.0, 3.0], [-4.0, -0.05, 7.0]])
    snapshot = make_snapshot(tmp_path / "run" / "buffer", serpentine_positions(2, 2))
    _write_registration(tmp_path / "run", snapshot, known, sidecar_sha="0" * 64)
    assert run_cli(snapshot["store"], snapshot["sidecar"], tmp_path / "out") == 2
    assert "E-REGISTRATION-STALE" in capsys.readouterr().err


def test_an_explicit_registration_record_is_digest_checked(tmp_path, capsys):
    """A named record must describe this sidecar, not just exist.

    The discovery path always compared digests; the explicit `--registration-record` path did not, so a
    record written for another capture would have supplied that capture's placement while every count
    still agreed.
    """
    known = np.array([[0.05, -4.0, 3.0], [-4.0, -0.05, 7.0]])
    snapshot = make_snapshot(tmp_path / "run" / "buffer", serpentine_positions(2, 2))
    report_path = _write_registration(
        tmp_path / "run", snapshot, known, sidecar_sha="f" * 64
    )
    out = tmp_path / "out"
    assert (
        run_cli(
            snapshot["store"],
            snapshot["sidecar"],
            out,
            "--registration-record",
            str(report_path),
        )
        == 2
    )
    assert "E-REGISTRATION-STALE" in capsys.readouterr().err
    assert not out.exists(), "a refusal must create no output directory"


def test_an_explicit_registration_record_matching_this_sidecar_is_used(tmp_path):
    known = np.array([[0.05, -4.0, 3.0], [-4.0, -0.05, 7.0]])
    snapshot = make_snapshot(tmp_path / "run" / "buffer", serpentine_positions(2, 2))
    report_path = _write_registration(tmp_path / "run", snapshot, known)
    out = tmp_path / "handoff"
    assert (
        run_cli(
            snapshot["store"],
            snapshot["sidecar"],
            out,
            "--registration-record",
            str(report_path),
        )
        == 0
    )
    assert read_handoff(out)["transform"]["source"].startswith("registration-fit:")


def test_a_residual_above_the_duplicate_gate_is_refused(tmp_path, capsys):
    """The declared residual sets RTASPT's merge radius, so a residual outside the gate cannot be passed on.

    Measured 2026-10-25 on one 4x4 stack with identical pixels: a 1.34 px residual stayed at the 6 px
    floor and produced 4617 objects, while a stale 25.62 px placement widened the radius to 76.85 px and
    star-linked 364 of 6102 detections into one object. Declaring that number is what caused it, so the
    adapter refuses instead.
    """
    known = np.array([[0.05, -4.0, 3.0], [-4.0, -0.05, 7.0]])
    snapshot = make_snapshot(tmp_path / "run" / "buffer", serpentine_positions(2, 2))
    _write_registration(tmp_path / "run", snapshot, known, residual_rms_px=25.615)
    out = tmp_path / "out"
    assert run_cli(snapshot["store"], snapshot["sidecar"], out) == 2
    assert "E-REGISTRATION-RESIDUAL" in capsys.readouterr().err
    assert not out.exists(), "a refusal must create no output directory"


def test_a_residual_inside_the_duplicate_gate_is_declared(tmp_path):
    known = np.array([[0.05, -4.0, 3.0], [-4.0, -0.05, 7.0]])
    snapshot = make_snapshot(tmp_path / "run" / "buffer", serpentine_positions(2, 2))
    _write_registration(tmp_path / "run", snapshot, known, residual_rms_px=1.3395)
    out = tmp_path / "handoff"
    assert run_cli(snapshot["store"], snapshot["sidecar"], out) == 0
    request = read_request(out)
    assert request["duplicates"]["registration_residual_px"] == pytest.approx(1.3395)
    assert request["duplicates"]["gate_px"] == pytest.approx(6.0)


def test_registration_record_supplies_preprocessing_id(tmp_path):
    known = np.array([[0.05, -4.0, 3.0], [-4.0, -0.05, 7.0]])
    snapshot = make_snapshot(tmp_path / "run" / "buffer", serpentine_positions(2, 2))
    report_path = _write_registration(tmp_path / "run", snapshot, known)
    record = tmp_path / "run" / "calibrated" / "registration_record.json"
    record.write_text(
        json.dumps({"fit_parameters": {"preprocessing_id": "raw-saved-camera-frames-v1"}}),
        encoding="utf-8",
    )
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    payload["registration_record_path"] = str(record)
    report_path.write_text(json.dumps(payload), encoding="utf-8")
    out = tmp_path / "handoff"
    assert run_cli(snapshot["store"], snapshot["sidecar"], out) == 0
    handoff = read_handoff(out)
    assert handoff["redsun_preprocessing_id"] == "raw-saved-camera-frames-v1"
    assert handoff["redsun_preprocessing_id_source"].startswith("registration-record:")


# ---------------------------------------------------------------------------
# Detection declaration
# ---------------------------------------------------------------------------


def test_detection_declaration_defaults_to_trackpy(tmp_path):
    """The default request must not change: trackpy, and the region block inert."""
    snapshot = make_snapshot(tmp_path, serpentine_positions(2, 2))
    out = tmp_path / "handoff"
    assert run_cli(snapshot["store"], snapshot["sidecar"], out, "--transform-matrix", MATRIX) == 0
    detection = read_request(out)["detection"]
    assert detection == {
        "backend": "trackpy",
        "diameter": r2r.DEFAULT_DETECTION_DIAMETER,
        "min_mass": r2r.DEFAULT_DETECTION_MIN_MASS,
        "processes": 1,
        "temporal_median_window": None,
        "threshold": None,
        "min_area_px": 1,
        "max_area_px": None,
    }
    assert read_handoff(out)["request"]["detection"] == detection
    provenance = json.loads((out / "provenance.json").read_text(encoding="utf-8"))
    assert provenance["detection"] == detection


def test_region_detection_options_are_declared_and_digest_chained(tmp_path):
    """A declared region backend reaches request.yaml and the request digest."""
    snapshot = make_snapshot(tmp_path, serpentine_positions(2, 2))
    out = tmp_path / "region"
    common = (
        snapshot["store"],
        snapshot["sidecar"],
        "--transform-matrix",
        MATRIX,
        "--detection-backend",
        "region",
        "--detection-min-area-px",
        "40",
        "--detection-max-area-px",
        "80000",
    )
    assert run_cli(*common, out, "--detection-threshold", "500") == 0
    request = read_request(out)
    detection = request["detection"]
    assert detection["backend"] == "region"
    assert detection["threshold"] == pytest.approx(500.0)
    assert detection["min_area_px"] == 40
    assert detection["max_area_px"] == 80000

    handoff = read_handoff(out)
    assert handoff["request"]["detection"] == detection
    provenance = json.loads((out / "provenance.json").read_text(encoding="utf-8"))
    assert provenance["detection"] == detection
    # The declaration is inside the digest chain: request.yaml's sha256 is
    # recorded in provenance.json and handoff.json.
    digest = r2r.sha256_file(out / "request.yaml")
    assert provenance["outputs"]["request"]["sha256"] == digest
    assert handoff["request"]["sha256"] == digest

    # Changing one detection option changes the request digest, so a product
    # cannot be replayed against a different detector without noticing.
    other = tmp_path / "region_other_threshold"
    assert run_cli(*common, other, "--detection-threshold", "600") == 0
    assert r2r.sha256_file(other / "request.yaml") != digest


def test_the_gaussian_backend_is_selectable(tmp_path):
    snapshot = make_snapshot(tmp_path, serpentine_positions(2, 2))
    out = tmp_path / "gaussian"
    assert run_cli(
        snapshot["store"],
        snapshot["sidecar"],
        out,
        "--transform-matrix",
        MATRIX,
        "--detection-backend",
        "gaussian",
    ) == 0
    detection = read_request(out)["detection"]
    assert detection["backend"] == "gaussian"
    assert detection["threshold"] is None


def test_impossible_region_area_band_is_refused(tmp_path, capsys):
    snapshot = make_snapshot(tmp_path, serpentine_positions(2, 2))
    out = tmp_path / "refused"
    assert run_cli(
        snapshot["store"],
        snapshot["sidecar"],
        out,
        "--transform-matrix",
        MATRIX,
        "--detection-backend",
        "region",
        "--detection-min-area-px",
        "100",
        "--detection-max-area-px",
        "50",
    ) == 2
    assert "E-DETECTION" in capsys.readouterr().err
    assert not out.exists(), "a refusal must create no output directory"


def test_a_non_finite_region_threshold_is_refused(tmp_path, capsys):
    snapshot = make_snapshot(tmp_path, serpentine_positions(2, 2))
    out = tmp_path / "refused"
    assert run_cli(
        snapshot["store"],
        snapshot["sidecar"],
        out,
        "--transform-matrix",
        MATRIX,
        "--detection-backend",
        "region",
        "--detection-threshold",
        "nan",
    ) == 2
    assert "E-DETECTION" in capsys.readouterr().err
    assert not out.exists()


# ---------------------------------------------------------------------------
# Product verification
# ---------------------------------------------------------------------------


def _fake_product(root: Path, handoff_path: Path, *, tile_offset: int = 0, order: str = "as_given") -> Path:
    """Write the product files RTASPT would write for the given handoff."""
    handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
    out_dir = handoff_path.parent
    frames = read_frames(out_dir / handoff["outputs"]["frames"]["path"])
    product = root / "searchscan"
    product.mkdir(parents=True, exist_ok=True)
    record = {
        "kind": "settled",
        "frames": str((out_dir / "frames.csv").resolve()),
        "transform": handoff["transform"],
        "tile_shape": handoff["tile_shape"],
        "images": {
            "kind": "movie",
            "path": str((out_dir / handoff["outputs"]["movie"]["path"]).resolve()),
        },
        "order": order,
        "notes": [],
    }
    (product / "request_used.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    with (product / "tiles.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(
            ["tile_index", "tile_uid", "row", "col", "stage_x_um", "stage_y_um", "offset_x_px", "offset_y_px"]
        )
        for index, row in enumerate(frames):
            shifted = frames[(index + tile_offset) % len(frames)]
            writer.writerow(
                [
                    index,
                    f"tile-{index}",
                    0,
                    0,
                    f"{float(shifted['x_um']):.6f}",
                    f"{float(shifted['y_um']):.6f}",
                    0.0,
                    0.0,
                ]
            )
    with (product / "detections.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["frame", "tile_index", "x", "y"])
        for index in range(len(frames)):
            writer.writerow([index, index, 1.0, 1.0])
    with (product / "objects.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["tile_index", "x", "y"])
        for index in range(len(frames)):
            writer.writerow([index, 1.0, 1.0])
    (product / "search_scan.json").write_text(
        json.dumps({"schema": r2r.RTASPT_REQUEST_SCHEMA, "counts": {
            "tiles": len(frames), "detections": len(frames), "objects": len(frames)
        }}),
        encoding="utf-8",
    )
    return product


def test_verify_product_passes_on_a_consistent_product(tmp_path):
    snapshot = make_snapshot(tmp_path, serpentine_positions(2, 2))
    out = tmp_path / "handoff"
    assert run_cli(snapshot["store"], snapshot["sidecar"], out, "--transform-matrix", MATRIX) == 0
    product = _fake_product(tmp_path, out / "handoff.json")
    report = verify_product.verify(out / "handoff.json", product)
    assert report["passed"], report["failed"]
    names = {check["check"] for check in report["checks"]}
    assert "tile_stage_coordinates_match_frame_rows" in names
    assert "request_used_order_as_given" in names
    assert report["source_identity"].startswith("unverified")


def test_verify_product_can_require_and_compare_processing_input_provenance(tmp_path):
    snapshot = make_snapshot(tmp_path, serpentine_positions(2, 2))
    out = tmp_path / "handoff"
    assert run_cli(snapshot["store"], snapshot["sidecar"], out, "--transform-matrix", MATRIX) == 0
    product = _fake_product(tmp_path, out / "handoff.json")
    handoff_path = out / "handoff.json"
    missing = verify_product.verify(handoff_path, product, require_input_provenance=True)
    assert "processing_input_provenance" in missing["failed"]

    handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
    entries = [
        {"role": role, "path": str((out / handoff["outputs"][key]["path"]).resolve()),
         "sha256": handoff["outputs"][key]["sha256"],
         "bytes": (out / handoff["outputs"][key]["path"]).stat().st_size}
        for role, key in (("frame_table", "frames"), ("image", "movie"))
    ]
    provenance = {"schema": "rtaspt-search-input-provenance-v1", "status": "complete", "image_source_kind": "movie",
                  "inputs_before": entries, "inputs_after": entries, "unchanged_at_boundaries": True}
    provenance_path = product / "input_provenance.json"
    provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
    record_path = product / "search_scan.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["products"] = {"input_provenance.json": "input_provenance.json"}
    record_path.write_text(json.dumps(record), encoding="utf-8")
    report = verify_product.verify(handoff_path, product, require_input_provenance=True)
    assert report["passed"], report["failed"]
    assert report["source_identity"].startswith("matching input digests")

    provenance["status"] = "in_progress"
    provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
    interrupted = verify_product.verify(handoff_path, product, require_input_provenance=True)
    assert "processing_input_provenance" in interrupted["failed"]
    provenance["status"] = "complete"
    entries[1]["sha256"] = "0" * 64
    provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
    changed = verify_product.verify(handoff_path, product, require_input_provenance=True)
    assert "processing_input_provenance" in changed["failed"]


def test_verify_product_catches_silent_renumbering(tmp_path):
    snapshot = make_snapshot(tmp_path, serpentine_positions(2, 2))
    out = tmp_path / "handoff"
    assert run_cli(snapshot["store"], snapshot["sidecar"], out, "--transform-matrix", MATRIX) == 0
    product = _fake_product(tmp_path, out / "handoff.json", tile_offset=1)
    report = verify_product.verify(out / "handoff.json", product)
    assert not report["passed"]
    assert "tile_stage_coordinates_match_frame_rows" in report["failed"]


def test_verify_product_catches_a_dropped_order_pin(tmp_path):
    snapshot = make_snapshot(tmp_path, serpentine_positions(2, 2))
    out = tmp_path / "handoff"
    assert run_cli(snapshot["store"], snapshot["sidecar"], out, "--transform-matrix", MATRIX) == 0
    product = _fake_product(tmp_path, out / "handoff.json", order="serpentine")
    report = verify_product.verify(out / "handoff.json", product)
    assert not report["passed"]
    assert "request_used_order_as_given" in report["failed"]


def test_verify_product_catches_a_tile_count_mismatch(tmp_path):
    snapshot = make_snapshot(tmp_path, serpentine_positions(2, 2))
    out = tmp_path / "handoff"
    assert run_cli(snapshot["store"], snapshot["sidecar"], out, "--transform-matrix", MATRIX) == 0
    product = _fake_product(tmp_path, out / "handoff.json")
    rows = read_frames(product / "tiles.csv")
    with (product / "tiles.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows[:-1])
    report = verify_product.verify(out / "handoff.json", product)
    assert not report["passed"]
    assert "tile_count_tiles_csv" in report["failed"]


@pytest.mark.parametrize("name", ["movie", "frames", "request"])
def test_verify_product_catches_handoff_file_mutation(tmp_path, name):
    snapshot = make_snapshot(tmp_path, serpentine_positions(2, 2))
    out = tmp_path / "handoff"
    assert run_cli(snapshot["store"], snapshot["sidecar"], out, "--transform-matrix", MATRIX) == 0
    product = _fake_product(tmp_path, out / "handoff.json")
    handoff = json.loads((out / "handoff.json").read_text(encoding="utf-8"))
    target = out / handoff["outputs"][name]["path"]
    with target.open("ab") as handle:
        handle.write(b"\n")
    report = verify_product.verify(out / "handoff.json", product)
    assert not report["passed"]
    assert f"handoff_{name}_sha256" in report["failed"]


def test_verify_product_catches_truncated_frame_table_even_with_updated_digest(tmp_path):
    snapshot = make_snapshot(tmp_path, serpentine_positions(2, 2))
    out = tmp_path / "handoff"
    assert run_cli(snapshot["store"], snapshot["sidecar"], out, "--transform-matrix", MATRIX) == 0
    product = _fake_product(tmp_path, out / "handoff.json")
    handoff_path = out / "handoff.json"
    handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
    frames_path = out / handoff["outputs"]["frames"]["path"]
    rows = read_frames(frames_path)
    with frames_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows[:-1])
    handoff["outputs"]["frames"]["sha256"] = r2r.sha256_file(frames_path)
    handoff_path.write_text(json.dumps(handoff), encoding="utf-8")
    report = verify_product.verify(handoff_path, product)
    assert "handoff_frame_table_count" in report["failed"]
    assert "tile_stage_coordinates_match_frame_rows" in report["failed"]


def test_verify_product_catches_negative_detection_and_missing_object_provenance(tmp_path):
    snapshot = make_snapshot(tmp_path, serpentine_positions(2, 2))
    out = tmp_path / "handoff"
    assert run_cli(snapshot["store"], snapshot["sidecar"], out, "--transform-matrix", MATRIX) == 0
    product = _fake_product(tmp_path, out / "handoff.json")
    (product / "detections.csv").write_text("frame,tile_index,x,y\n0,-1,1,1\n", encoding="utf-8")
    (product / "objects.csv").write_text("x,y\n1,1\n", encoding="utf-8")
    report = verify_product.verify(out / "handoff.json", product)
    assert "detections_tile_index_in_range" in report["failed"]
    assert "objects_have_tile_provenance" in report["failed"]


def test_verify_product_catches_truncated_transform(tmp_path):
    snapshot = make_snapshot(tmp_path, serpentine_positions(2, 2))
    out = tmp_path / "handoff"
    assert run_cli(snapshot["store"], snapshot["sidecar"], out, "--transform-matrix", MATRIX) == 0
    product = _fake_product(tmp_path, out / "handoff.json")
    request_path = product / "request_used.json"
    request = json.loads(request_path.read_text(encoding="utf-8"))
    request["transform"]["matrix"][0].pop()
    request_path.write_text(json.dumps(request), encoding="utf-8")
    report = verify_product.verify(out / "handoff.json", product)
    assert "request_used_transform" in report["failed"]


@pytest.mark.parametrize("name", ["detections.csv", "objects.csv"])
def test_verify_product_refuses_missing_product_tables(tmp_path, name):
    snapshot = make_snapshot(tmp_path, serpentine_positions(2, 2))
    out = tmp_path / "handoff"
    assert run_cli(snapshot["store"], snapshot["sidecar"], out, "--transform-matrix", MATRIX) == 0
    product = _fake_product(tmp_path, out / "handoff.json")
    (product / name).unlink()
    report = verify_product.verify(out / "handoff.json", product)
    assert f"{name.removesuffix('.csv')}_table_present" in report["failed"]


def test_verify_product_accepts_empty_objects_with_provenance_header(tmp_path):
    snapshot = make_snapshot(tmp_path, serpentine_positions(2, 2))
    out = tmp_path / "handoff"
    assert run_cli(snapshot["store"], snapshot["sidecar"], out, "--transform-matrix", MATRIX) == 0
    product = _fake_product(tmp_path, out / "handoff.json")
    (product / "objects.csv").write_text("tile_index,x,y\n", encoding="utf-8")
    record_path = product / "search_scan.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["counts"]["objects"] = 0
    record_path.write_text(json.dumps(record), encoding="utf-8")
    report = verify_product.verify(out / "handoff.json", product)
    assert report["passed"], report["failed"]
