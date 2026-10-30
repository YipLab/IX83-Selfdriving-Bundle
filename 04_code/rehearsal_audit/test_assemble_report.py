"""Hardware-free tests for the T7 rehearsal report generator.

The generator's whole point is that it does not assert: a stage is `completed` only
when its artifact is inside the run root and a figure was read from it, and the
one-session claim is refused when the root carries more than one session. These tests
build run roots on disk and check both halves - the schema it emits, and the claims it
refuses.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from assemble_report import assemble, verify


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def _session_log(root: Path, stem: str, *, ran_plan: bool) -> None:
    """Write one app session log, with a plan completion marker when it ran one."""
    log = root / "logs" / "ix71-test-session" / "app" / f"{stem}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    body = "[INFO][AcquisitionPresenter -> acq_ctrl]: " + (
        "'execute_asi_snap_coverage_survey_and_prepare_review' ended\n"
        if ran_plan
        else "preconditions satisfied; nothing was written\n"
    )
    log.write_text(body, encoding="utf-8")


def _complete_run_root(root: Path, *, sessions: int = 1) -> Path:
    """Write artifacts for all ten stages into one run root."""
    _write(
        root / "survey" / "survey.positions.json",
        {
            "frames_written": 9,
            "exit_status": "success",
            "camera_exposure_ms": 10.0,
            "illumination_device": "laser488",
            "illumination_intensity_mw": 1.0,
        },
    )
    _write(
        root / "survey" / "checkpoint_mosaic" / "registration.json",
        {
            "passed_pair_count": 12,
            "pair_count": 12,
            "status": "complete",
            "registration_backend": "rtaspt",
        },
    )
    _write(
        root / "survey" / "decision.json",
        {"accepted_target_ids": ["t1", "t2"], "decision_source": "automatic"},
    )
    _write(
        root / "revisit" / "result.json",
        {"selected_targets": ["t1", "t2"], "status": "reviewed"},
    )
    _write(
        root / "broom" / "process" / "mosaic" / "compose_report.json",
        {
            "canvas": {"shape_yx": [100, 200]},
            "registration": {"measured_join_count": 11},
        },
    )
    _write(
        root / "rehearsal" / "manifest.json",
        {"artifacts": [{"path": "a.tif", "sha256": "0" * 64}]},
    )
    _write(root / "rtaspt" / "process" / "dataset_record.json", {"frame_count": 300})
    _write(
        root / "rtaspt" / "process" / "processing_summary.json",
        {"anisotropy_computed": False},
    )
    tracks = root / "rtaspt" / "track" / "tracks.csv"
    tracks.parent.mkdir(parents=True, exist_ok=True)
    tracks.write_text("track_id,x_um,y_um\n1,0.0,0.0\n2,1.0,1.0\n", encoding="utf-8")
    _session_log(root, "2026-10-29T10-00-00_100", ran_plan=True)
    for index in range(1, sessions):
        _session_log(root, f"2026-10-29T1{index}-00-00_200", ran_plan=True)
    return root


def test_all_ten_stages_complete_in_one_session(tmp_path: Path) -> None:
    """A complete single-session root yields ten completed stages and the claim."""
    report = assemble(
        _complete_run_root(tmp_path / "run"),
        rehearsal="test",
        specimen_id="specimen",
        calibration_id="cal",
        profile="profile",
        profile_revision="rev",
        authorization="test",
        attempt="t7",
    )

    assert [stage["number"] for stage in report["stages"]] == list(range(1, 11))
    assert report["stage_summary"]["by_status"] == {"completed": 10}
    assert report["one_session"]["established"] is True
    assert report["one_session"]["session_ids"] == ["ix71-test-session/2026-10-29T10-00-00_100"]
    # Every stage carries both the Close-out names and the auditor's mirror fields.
    for stage in report["stages"]:
        assert stage["status"] == stage["state"] == "completed"
        assert stage["artifact"]["sha256"]
        assert stage["artifact_check"]["found"][0]["sha256"] == stage["artifact"]["sha256"]
        assert stage["measured"]
    for key in (
        "specimen_id",
        "calibration_id",
        "profile",
        "profile_revision",
        "resolved_backends",
        "authorization",
        "started_at",
        "finished_at",
        "software",
    ):
        assert key in report


def test_a_missing_artifact_is_not_applied_never_completed(tmp_path: Path) -> None:
    """A stage with no artifact is not_applied with its reason, not completed."""
    root = _complete_run_root(tmp_path / "run")
    (root / "rtaspt" / "track" / "tracks.csv").unlink()

    report = assemble(
        root,
        rehearsal="test",
        specimen_id="specimen",
        calibration_id="cal",
        profile="profile",
        profile_revision="rev",
        authorization="test",
        attempt="t7",
    )

    tracking = report["stages"][-1]
    assert tracking["stage"] == "SPT-tracking"
    assert tracking["status"] == "not_applied"
    assert tracking["artifact"] is None
    assert tracking["notes"] == "no track table under the run root"
    assert tracking["status"] != "completed"
    assert report["stage_summary"]["by_status"] == {"completed": 9, "not_applied": 1}
    # The absence is named at the top level as well, so a reader cannot miss it.
    assert any("SPT-tracking" in item for item in report["not_covered"])


def test_two_sessions_refuse_the_one_session_claim(tmp_path: Path) -> None:
    """Two sessions that ran a plan make the one-session claim false, and it says so."""
    root = _complete_run_root(tmp_path / "run", sessions=2)

    report = assemble(
        root,
        rehearsal="test",
        specimen_id="specimen",
        calibration_id="cal",
        profile="profile",
        profile_revision="rev",
        authorization="test",
        attempt="t7",
    )

    claim = report["one_session"]
    assert claim["claimed"] is False
    assert claim["established"] is False
    assert len(claim["session_ids"]) == 2
    assert "2 sessions that ran a plan" in claim["reason"]
    for session in claim["session_ids"]:
        assert session in claim["reason"]


def test_an_idle_preflight_session_does_not_count_as_a_second_session(
    tmp_path: Path,
) -> None:
    """A preflight that launched no plan is reported, but is not a second session."""
    root = _complete_run_root(tmp_path / "run")
    _session_log(root, "2026-10-29T09-59-00_100", ran_plan=False)

    report = assemble(
        root,
        rehearsal="test",
        specimen_id="specimen",
        calibration_id="cal",
        profile="profile",
        profile_revision="rev",
        authorization="test",
        attempt="t7",
    )

    assert report["one_session"]["established"] is True
    assert len(report["one_session"]["session_logs_idle"]) == 1
    assert len(report["one_session"]["session_ids"]) == 1


def test_a_run_root_without_session_logs_cannot_claim_one_session(
    tmp_path: Path,
) -> None:
    """No session evidence is an honest 'cannot establish', not a pass."""
    root = _complete_run_root(tmp_path / "run")
    for log in (root / "logs").rglob("*.log"):
        log.unlink()

    report = assemble(
        root,
        rehearsal="test",
        specimen_id="specimen",
        calibration_id="cal",
        profile="profile",
        profile_revision="rev",
        authorization="test",
        attempt="t7",
    )

    assert report["one_session"]["established"] is False
    assert "cannot be established" in report["one_session"]["reason"]


def test_verify_recomputes_every_declared_digest(tmp_path: Path) -> None:
    """The check re-hashes the artifacts, so a changed file is a problem."""
    root = _complete_run_root(tmp_path / "run")
    report = assemble(
        root,
        rehearsal="test",
        specimen_id="specimen",
        calibration_id="cal",
        profile="profile",
        profile_revision="rev",
        authorization="test",
        attempt="t7",
    )
    written = tmp_path / "rehearsal_report.json"
    written.write_text(json.dumps(report), encoding="utf-8")
    assert verify(written) == 0

    (root / "rtaspt" / "process" / "dataset_record.json").write_text(
        json.dumps({"frame_count": 301}), encoding="utf-8"
    )
    assert verify(written) == 1


def test_an_unreadable_run_root_is_refused(tmp_path: Path) -> None:
    """A path that is not a directory is a refusal, not an empty report."""
    with pytest.raises(FileNotFoundError):
        assemble(
            tmp_path / "absent",
            rehearsal="test",
            specimen_id="specimen",
            calibration_id="cal",
            profile="profile",
            profile_revision="rev",
            authorization="test",
            attempt="t7",
        )

def test_a_capture_whose_own_record_says_it_failed_is_not_completed(
    tmp_path: Path,
) -> None:
    """A sidecar with exit_status 'fail' is a failed stage, however many frames it has.

    Found on the recorded T2 attempt 1: it wrote six frames before the shutter refused,
    and the first version of this tool scored it `completed`.
    """
    root = _complete_run_root(tmp_path / "run")
    _write(
        root / "survey" / "survey.positions.json",
        {
            "frames_written": 6,
            "exit_status": "fail",
            "camera_exposure_ms": 10.0,
            "illumination_device": "laser488",
            "illumination_intensity_mw": 1.0,
        },
    )

    report = assemble(
        root,
        rehearsal="test",
        specimen_id="specimen",
        calibration_id="cal",
        profile="profile",
        profile_revision="rev",
        authorization="test",
        attempt="t7",
    )

    grid = report["stages"][0]
    assert grid["status"] == "failed"
    assert grid["measured"] == "6 frames written, exit_status 'fail'"
    assert "exit_status 'fail'" in grid["notes"]


def test_a_registration_with_no_accepted_pair_is_not_completed(tmp_path: Path) -> None:
    """Zero accepted pairs is a failed registration, not a completed stage."""
    root = _complete_run_root(tmp_path / "run")
    _write(
        root / "survey" / "checkpoint_mosaic" / "registration.json",
        {
            "passed_pair_count": 0,
            "pair_count": 13,
            "status": "no_accepted_pairs",
            "registration_backend": "rtaspt",
        },
    )

    report = assemble(
        root,
        rehearsal="test",
        specimen_id="specimen",
        calibration_id="cal",
        profile="profile",
        profile_revision="rev",
        authorization="test",
        attempt="t7",
    )

    registration = report["stages"][2]
    assert registration["status"] == "failed"
    assert "accepted no pair" in registration["notes"]


def test_a_partial_registration_graph_is_unknown_not_completed(tmp_path: Path) -> None:
    """Some pairs but not a connected graph is 'unknown', never 'completed'."""
    root = _complete_run_root(tmp_path / "run")
    _write(
        root / "survey" / "checkpoint_mosaic" / "registration.json",
        {
            "passed_pair_count": 7,
            "pair_count": 36,
            "status": "partial",
            "registration_backend": "rtaspt",
        },
    )

    report = assemble(
        root,
        rehearsal="test",
        specimen_id="specimen",
        calibration_id="cal",
        profile="profile",
        profile_revision="rev",
        authorization="test",
        attempt="t7",
    )

    registration = report["stages"][2]
    assert registration["status"] == "unknown"
    assert "not 'complete'" in registration["notes"]
