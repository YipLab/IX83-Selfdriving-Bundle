"""Hardware-free tests for the throughput accounting harness."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import account
import pytest
from account import AccountingError

HERE = Path(__file__).resolve().parent
SESSION = (
    Path(__file__).resolve().parents[2]
    / "08_session_logs"
    / "20261024T_long_strip_broom_01"
)
LOG = json.loads((HERE / "consumer.example.json").read_text(encoding="utf-8"))


def _log(**overrides: Any) -> dict[str, Any]:
    document = copy.deepcopy(LOG)
    document.update(overrides)
    return document


def _row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "frame_id": 1,
        "attempted_ns": 0,
        "published_ns": 100_000_000,
        "processed_ns": 180_000_000,
        "released_ns": 200_000_000,
        "dropped": False,
    }
    row.update(overrides)
    return row


@pytest.mark.skipif(
    not (SESSION / "run_snake_06").is_dir(), reason="recorded run is not present"
)
def test_a_complete_run_accounts_capture_pose_timing_and_persistence() -> None:
    document = account.account_run(SESSION / "run_snake_06")
    categories = document["categories"]
    assert categories["captured"]["value"] == 279
    assert categories["persisted"]["value"] == 279
    assert categories["missing"]["value"] == 0
    assert categories["attempted"]["status"] == "not_recorded"
    assert categories["published"]["status"] == "not_recorded"
    assert categories["processed"]["status"] == "not_recorded"
    assert document["findings"] == []
    assert document["camera_mode"]["exposure_ms"] == 10.0
    assert document["camera_mode"]["binning_xy"] == [1, 1]


@pytest.mark.skipif(
    not (SESSION / "run_snake_05").is_dir(), reason="recorded run is not present"
)
def test_a_failed_run_keeps_its_missing_frames_and_reason() -> None:
    document = account.account_run(SESSION / "run_snake_05")
    assert document["categories"]["captured"]["value"] == 284
    assert document["categories"]["missing"]["value"] == 2
    codes = {finding["code"]: finding["severity"] for finding in document["findings"]}
    assert codes["captured_without_pose"] == "blocking"
    assert codes["run_incomplete"] == "warning"
    assert "pose association" in next(
        finding["detail"]
        for finding in document["findings"]
        if finding["code"] == "run_incomplete"
    )


def test_a_run_without_a_report_is_refused(tmp_path: Path) -> None:
    with pytest.raises(AccountingError, match="report"):
        account.account_run(tmp_path)


def test_the_consumer_example_accounts_its_fixture(tmp_path: Path) -> None:
    document = account.account_consumer(LOG, source="fixture")
    categories = document["categories"]
    assert categories["attempted"]["value"] == 7
    assert categories["published"]["value"] == 6
    assert categories["refused"]["value"] == 1
    assert categories["processed"]["value"] == 6
    assert categories["released"]["value"] == 6
    assert categories["missing"]["value"] == 0
    assert categories["captured"]["status"] == "not_recorded"
    assert document["queue"]["value"] == {"peak_occupancy": 1, "capacity": 2}
    latency = document["latency"]["value"]["publish_to_process_ms"]
    assert latency["median"] == 80.0
    assert latency["p95"] == 260.0
    assert latency["max"] == 260.0
    assert document["restarts"]["value"] == 1
    codes = {finding["code"] for finding in document["findings"]}
    assert codes == {"frames_dropped", "latency_over_budget"}


def test_a_missing_publication_is_blocking() -> None:
    log = _log()
    log["rows"][1]["published_ns"] = None
    log["rows"][1]["dropped"] = False
    document = account.account_consumer(log)
    codes = {finding["code"]: finding["severity"] for finding in document["findings"]}
    assert codes["missing_publications"] == "blocking"
    assert document["categories"]["missing"]["value"] == 1


def test_an_unreleased_frame_is_reported_at_close() -> None:
    log = _log()
    log["rows"][2]["released_ns"] = None
    document = account.account_consumer(log)
    assert "unreleased_at_close" in {
        finding["code"] for finding in document["findings"]
    }


def test_a_sequence_gap_is_reported() -> None:
    log = _log()
    del log["rows"][2]
    document = account.account_consumer(log)
    assert "sequence_gap" in {finding["code"] for finding in document["findings"]}


def test_queue_occupancy_over_capacity_is_blocking() -> None:
    log = _log()
    for row in log["rows"]:
        row["released_ns"] = None
    log["budget"]["queue_capacity"] = 2
    document = account.account_consumer(log)
    finding = next(
        item for item in document["findings"] if item["code"] == "queue_overflow"
    )
    assert finding["severity"] == "blocking"
    assert document["queue"]["value"]["peak_occupancy"] == 6


def test_latency_budget_and_clock_uncertainty_are_carried() -> None:
    log = _log()
    document = account.account_consumer(log)
    assert document["latency"]["value"]["clock_uncertainty_ms"] == 0.5

    clean = _log()
    for row in clean["rows"]:
        if row["published_ns"] is not None:
            row["processed_ns"] = row["published_ns"] + 10_000_000
    document = account.account_consumer(clean)
    assert "latency_over_budget" not in {
        finding["code"] for finding in document["findings"]
    }


def test_without_a_capacity_queue_is_not_recorded() -> None:
    log = _log()
    log["budget"] = {"max_latency_ms": 150.0}
    document = account.account_consumer(log)
    assert document["queue"]["status"] == "not_recorded"


def test_duplicate_frame_ids_are_refused() -> None:
    log = _log()
    log["rows"][1]["frame_id"] = log["rows"][0]["frame_id"]
    with pytest.raises(AccountingError, match="repeated frame ids"):
        account.account_consumer(log)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"schema": "other"}, "schema"),
        ({"rows": []}, "rows"),
    ],
)
def test_invalid_logs_are_refused(change: dict[str, Any], message: str) -> None:
    with pytest.raises(AccountingError, match=message):
        account.account_consumer(_log(**change))


def test_a_malformed_row_is_refused() -> None:
    log = _log()
    log["rows"][0]["frame_id"] = -1
    with pytest.raises(AccountingError, match="frame_id"):
        account.account_consumer(log)


def test_cli_accounts_a_run_and_a_consumer_log(tmp_path: Path) -> None:
    out = tmp_path / "accounting.json"
    if (SESSION / "run_snake_06").is_dir():
        assert (
            account.main(["--run", str(SESSION / "run_snake_06"), "--out", str(out)])
            == 0
        )
        document = json.loads(out.read_text(encoding="utf-8"))
        assert document["source"]["mode"] == "recorded_run"
        assert document["categories"]["captured"]["value"] == 279

    log_path = tmp_path / "log.json"
    log_path.write_text(json.dumps(LOG), encoding="utf-8")
    assert account.main(["--consumer-log", str(log_path), "--out", str(out)]) == 0
    document = json.loads(out.read_text(encoding="utf-8"))
    assert document["source"]["mode"] == "consumer_log"

    missing = tmp_path / "absent"
    assert account.main(["--run", str(missing)]) == 2
