import json
from dataclasses import replace
from datetime import UTC, datetime

import numpy as np
import pytest
from planner import AcquisitionSettings, ActionStatus, Phase, RunStatus
from planner.scanning import ScanPosition, grid_positions

from ix83_acquisition.scan_host import (
    AcquisitionResult,
    DataReference,
    MoveResult,
    StageScanRunner,
)


class Backend:
    capabilities = frozenset({"stage.xy", "camera.snap", "camera.sequence", "storage.raw"})
    resources = frozenset({"stage", "camera", "storage"})
    setting_capabilities = frozenset({"exposure_ms"})

    def __init__(self, journal, failure=None):
        self.journal, self.failure = journal, failure
        self.calls = []
        self.position = (0, 0, 0)

    def move_to(self, request):
        assert json.loads(self.journal.read_text())["actions"][-1]["status"] == "started"
        self.calls.append(("move", request.position_xyz_um))
        if self.failure == "move":
            raise TimeoutError("no acknowledgement")
        self.position = request.position_xyz_um
        return MoveResult(request.request_id, self.position)

    def acquire(self, request):
        assert json.loads(self.journal.read_text())["actions"][-1]["status"] == "started"
        assert json.loads(self.journal.read_text())["status"] == "running"
        self.calls.append(("acquire", request))
        if self.failure == "second-image" and sum(c[0] == "acquire" for c in self.calls) == 2:
            raise ValueError("camera failed")
        frame_count = request.settings.frames
        dataset = DataReference(
            "memory://saved-dataset",
            "npy-frames",
            "QYX",
            (frame_count, 8, 8),
            "float64",
            frame_count,
            "completed",
            "0" * 64,
        )
        return AcquisitionResult(
            request.request_id,
            request.run_id,
            request.specimen_id,
            request.phase,
            request.coordinate_frame,
            request.calibration_id,
            request.tile_id,
            np.ones((8, 8)),
            self.position[:2],
            datetime.now(UTC),
            dataset,
        )


def setup(tmp_path, failure=None, cancelled=lambda: False):
    path = tmp_path / "scan.json"
    backend = Backend(path, failure)
    runner = StageScanRunner(
        backend,
        limits_xy_um=((-500, 500), (-500, 500)),
        fixed_z_um=0,
        origin_xy_um=(0, 0),
        journal=path,
        cancelled=cancelled,
    )
    return runner, backend


def test_grid_donor_order_orientation_and_serpentine():
    grid = grid_positions((10, 20), rows=2, columns=3, step_xy_um=(5, 7))
    assert [(p.x_um, p.y_um) for p in grid] == [
        (10, 20),
        (10, 27),
        (15, 20),
        (15, 27),
        (20, 20),
        (20, 27),
    ]
    oriented = grid_positions(
        (10, 20),
        rows=2,
        columns=2,
        step_xy_um=(5, 7),
        x_sign=-1,
        y_sign=1,
        swap_xy=True,
        serpentine=True,
    )
    assert [(p.x_um, p.y_um) for p in oriented] == [(10, 20), (17, 20), (17, 15), (10, 15)]


def test_all_bounds_checked_before_any_command(tmp_path):
    runner, backend = setup(tmp_path)
    with pytest.raises(ValueError, match="envelope"):
        runner.run(
            [ScanPosition("good", 0, 0), ScanPosition("bad", 501, 0)],
            AcquisitionSettings(),
            specimen_id="s",
        )
    assert backend.calls == [] and not runner.journal.exists()


def test_binding_resources_are_checked_before_any_command(tmp_path):
    runner, backend = setup(tmp_path)
    backend.resources = frozenset({"stage", "camera"})
    with pytest.raises(RuntimeError, match="lacks required resources: storage"):
        runner.run([ScanPosition("tile", 0, 0)], AcquisitionSettings(), specimen_id="s")
    assert backend.calls == [] and not runner.journal.exists()


def test_scan_records_saved_prefix_and_returns_origin(tmp_path):
    runner, backend = setup(tmp_path)
    result = runner.run(
        grid_positions((0, 0), rows=2, columns=2, step_xy_um=(25, 25)),
        AcquisitionSettings(frames=3),
        specimen_id="s",
        phase=Phase.REVISIT,
    )
    assert result.status is RunStatus.COMPLETED and len(result.positions) == 4
    assert len(result.execution_bindings) == 1
    assert result.execution_bindings[0].resources == backend.resources
    assert backend.calls[-1] == ("move", (0, 0, 0))
    assert all(c[1].phase is Phase.REVISIT for c in backend.calls if c[0] == "acquire")
    journal_record = json.loads(runner.journal.read_text())
    assert journal_record["status"] == "completed"
    assert journal_record["execution_bindings"][0]["provider"].endswith("Backend")
    assert journal_record["resolved"]["requirements"]["resources"] == [
        {"name": "stage", "mode": "exclusive"},
        {"name": "camera", "mode": "exclusive"},
        {"name": "storage", "mode": "exclusive"},
    ]
    first_request_id = result.actions[0].request_id
    first_action_events = [a.status for a in result.actions if a.request_id == first_request_id]
    assert first_action_events == [
        ActionStatus.PROPOSED,
        ActionStatus.ACCEPTED,
        ActionStatus.STARTED,
        ActionStatus.COMPLETED,
    ]
    with pytest.raises(FileExistsError):
        runner.run([ScanPosition("again", 0, 0)], AcquisitionSettings(), specimen_id="s")


@pytest.mark.parametrize(
    "failure,status,prefix",
    [("move", RunStatus.OUTCOME_UNKNOWN, 0), ("second-image", RunStatus.FAILED, 1)],
)
def test_failure_preserves_prefix_and_never_returns_or_retries(tmp_path, failure, status, prefix):
    runner, backend = setup(tmp_path, failure)
    result = runner.run(
        grid_positions((0, 0), rows=2, columns=1, step_xy_um=(25, 25)),
        AcquisitionSettings(),
        specimen_id="s",
    )
    assert result.status is status and len(result.positions) == prefix
    assert not any(a.action == "return_to_origin" for a in result.actions)
    assert len(backend.calls) == (1 if failure == "move" else 4)


def test_cancel_between_tiles_retains_prefix(tmp_path):
    runner, backend = setup(tmp_path)
    runner.cancelled = lambda: sum(c[0] == "acquire" for c in backend.calls) == 1
    result = runner.run(
        grid_positions((0, 0), rows=3, columns=1, step_xy_um=(25, 25)),
        AcquisitionSettings(),
        specimen_id="s",
    )
    assert result.status is RunStatus.CANCELLED and len(result.positions) == 1
    assert backend.calls[-1] == ("move", (0, 0, 0))


def test_unsupported_settings_rejected_before_move(tmp_path):
    runner, backend = setup(tmp_path)
    with pytest.raises(ValueError, match="loaded channel"):
        runner.run(
            [ScanPosition("tile", 0, 0)], AcquisitionSettings(channel_id="488"), specimen_id="s"
        )
    assert backend.calls == []


def test_incomplete_dataset_reference_is_rejected_before_recording_position(tmp_path):
    runner, backend = setup(tmp_path)
    original = backend.acquire

    def incomplete(request):
        result = original(request)
        return replace(
            result,
            dataset=DataReference(
                "memory://incomplete",
                "npy-frames",
                "QYX",
                (1, 8, 8),
                "float64",
                1,
                "cancelled",
                "0" * 64,
            ),
        )

    backend.acquire = incomplete
    run = runner.run([ScanPosition("tile", 0, 0)], AcquisitionSettings(), specimen_id="s")
    assert run.status is RunStatus.FAILED
    assert not run.positions
    assert "dataset is not complete" in run.errors[0]


def test_bad_readback_blocks_capture_and_return(tmp_path):
    runner, backend = setup(tmp_path)
    original = backend.move_to

    def incorrect(request):
        original(request)
        return MoveResult(request.request_id, (50, 0, 0))

    backend.move_to = incorrect
    result = runner.run([ScanPosition("tile", 0, 0)], AcquisitionSettings(), specimen_id="s")
    assert result.status is RunStatus.OUTCOME_UNKNOWN
    assert len(backend.calls) == 1 and not result.positions
    assert result.actions[-1].status is ActionStatus.OUTCOME_UNKNOWN
