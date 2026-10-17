from datetime import UTC, datetime
from types import SimpleNamespace

import numpy as np
import review_cli
from planner import Calibration, Phase, Region, RunStatus, SearchObservation
from planner.contracts import WorkflowRun


def test_review_cli_builds_and_opens_saved_checkpoint_page(tmp_path, monkeypatch):
    now = datetime.now(UTC)
    observation = SearchObservation(
        "specimen",
        Phase.SURVEY,
        "stage",
        "cal",
        now,
        now,
        (5, 5),
        "tile-0",
        "request-0",
        run_id="run-0",
        data_reference="mock-reference",
        image_shape_yx=(4, 4),
    )
    run = WorkflowRun(
        run_id="run-0",
        specimen_id="specimen",
        status=RunStatus.REVIEW_PENDING,
        observations=[observation],
    )
    calibration = Calibration("cal", "stage", ((1, 0), (0, 1)), (1.5, 1.5), (5, 5))
    region = Region(0, 0, 10, 10)
    monkeypatch.setattr(
        review_cli, "load_review_run", lambda _path: (run, None, calibration, region, calibration)
    )
    monkeypatch.setattr(
        review_cli,
        "replay_frames",
        lambda _path: iter((SimpleNamespace(pixels=np.arange(16, dtype=np.uint8).reshape(4, 4)),)),
    )
    opened = []
    monkeypatch.setattr(review_cli.webbrowser, "open", lambda uri: opened.append(uri) or True)

    output = tmp_path / "review.html"
    assert review_cli.main([str(tmp_path / "checkpoint.json"), "--output", str(output)]) == 0
    page = output.read_text(encoding="utf-8")
    assert "Survey overview" in page
    assert "data:image/png;base64," in page
    assert ".frame svg { position: absolute;" in page
    assert opened == [output.resolve().as_uri()]
