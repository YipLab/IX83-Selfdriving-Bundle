from __future__ import annotations

import json
import time

import pytest

from ix83_acquisition.scan_host.ludl_motion import EXPECTED_DEVICES, LudlMotionHost


class FakeCore:
    def __init__(self):
        self.xy = [100.0, -50.0]
        self.z = 12.0
        self.target = None
        self.busy = False
        self.stop_calls = 0
        self.stop_stuck = False
        self.set_calls = []
        self.properties = {"Speed": 10.0, "StartSpeed": 100.0, "Acceleration": 4.0}
        self.property_readback_offsets = {}
        self.move_reads = []
        self.settle_busy_polls = 0

    def get_loaded_devices(self):
        return list(EXPECTED_DEVICES)

    def get_device_library(self, name):
        return EXPECTED_DEVICES[name][0]

    def get_device_name(self, name):
        return EXPECTED_DEVICES[name][1]

    def get_property(self, device, prop):
        if (device, prop) == ("LudlController", "Port"):
            return "COM22"
        return str(self.properties[prop] + self.property_readback_offsets.get(prop, 0.0))

    def get_xy_stage_device(self):
        return "XYStage"

    def get_camera_device(self):
        return "Camera"

    def get_focus_device(self):
        return "ZStage"

    def is_sequence_running(self):
        return False

    def get_remaining_image_count(self):
        return 0

    def get_auto_shutter(self):
        return False

    def get_shutter_device(self):
        return ""

    def get_x_position(self, stage):
        if self.move_reads:
            self.xy[0] = self.move_reads.pop(0)
        return self.xy[0]

    def get_y_position(self, stage):
        return self.xy[1]

    def get_position(self, stage):
        return self.z

    def device_busy(self, stage):
        if self.settle_busy_polls:
            self.settle_busy_polls -= 1
            return True
        return self.busy

    def set_xy_position(self, x, y):
        self.set_calls.append((x, y))
        self.target = [x, y]
        self.busy = True

    def advance(self, xy=None, busy=False):
        if xy is not None:
            self.xy[:] = xy
        self.busy = busy

    def stop(self, stage):
        assert stage == "XYStage"
        self.stop_calls += 1
        if not self.stop_stuck:
            self.busy = False
            self.settle_busy_polls = 2

    def get_property_lower_limit(self, stage, prop):
        return 0

    def get_property_upper_limit(self, stage, prop):
        return 10

    def set_property(self, stage, prop, value):
        self.properties[prop] = float(value)

    def has_property_limits(self, stage, prop):
        return False


def make(tmp_path, core=None, **kwargs):
    return LudlMotionHost(
        core or FakeCore(),
        tmp_path / "actions.jsonl",
        run_context={"run_id": "test-run", "profile": "ludl-demo"},
        **kwargs,
    )


def poll_until_result(host, handle):
    deadline = time.monotonic() + 1.5
    while time.monotonic() < deadline:
        result = host.poll(handle)
        if result is not None:
            return result
        time.sleep(0.05)
    raise AssertionError("motion did not reach a terminal or unknown result")


def test_envelope_is_relative_to_immutable_initial_origin_and_checked_before_command(
    tmp_path,
):
    core = FakeCore()
    host = make(tmp_path, core)
    with pytest.raises(ValueError):
        host.start_move(host.origin_xy_um[0] + 2000.01, host.origin_xy_um[1], timeout_s=1)
    assert core.set_calls == []
    handle = host.start_move(110, -40, timeout_s=2)
    core.advance([110.2, -39.9], busy=False)
    result = poll_until_result(host, handle)
    assert result.status == "completed"
    assert result.ack_latency_s >= 0
    assert result.started_utc and result.acknowledged_utc and result.finished_utc
    assert host.fixed_z_um == 12.0
    assert all("z" not in "".join(map(str, c)).lower() for c in core.set_calls)


def test_acknowledgement_does_not_wait_and_false_busy_outside_target_is_unknown(
    tmp_path,
):
    core = FakeCore()
    host = make(tmp_path, core)
    handle = host.start_move(101, -50, timeout_s=2)
    assert core.set_calls == [(101.0, -50.0)]
    assert host.poll(handle) is None  # Busy, and still at the starting point.
    core.advance([100.0, -50.0], busy=False)
    result = poll_until_result(host, handle)
    assert result.status == "outcome_unknown"
    assert "Busy false" in result.error
    assert host._unresolved


def test_cancellation_stops_and_reconciles_before_another_move(tmp_path):
    core = FakeCore()
    host = make(tmp_path, core)
    handle = host.start_move(110, -50, timeout_s=5)
    core.advance([105, -50], busy=True)
    core.settle_busy_polls = 2
    started = time.monotonic()
    result = host.wait(handle, cancelled=lambda: True)
    assert time.monotonic() - started >= 0.3
    assert result.status == "cancelled"
    assert core.stop_calls == 1
    assert not core.busy
    # Stop was confirmed idle and the current readback was journaled.
    next_handle = host.start_move(111, -50, timeout_s=1)
    assert next_handle.target_xy_um == (111.0, -50.0)


def test_unknown_busy_outcome_blocks_until_readback_reconciled(tmp_path):
    core = FakeCore()
    host = make(tmp_path, core)
    handle = host.start_move(110, -50, timeout_s=5)
    core.stop_stuck = True
    host._stop_and_reconcile(handle, "deadline expired")
    assert host._unresolved
    with pytest.raises(RuntimeError):
        host.start_move(111, -50, timeout_s=1)
    with pytest.raises(RuntimeError, match="stable idle readbacks"):
        host.reconcile(stable_for_s=0.3, timeout_s=0.3)
    core.advance([109.8, -50], busy=False)
    x, y, busy = host.reconcile()
    assert not busy and (x, y) == (109.8, -50.0)


def test_motion_properties_require_limits_and_readback(tmp_path):
    core = FakeCore()
    host = make(tmp_path, core)
    result = host.set_motion_properties(speed=2, start_speed=0.5, accel=3)
    assert result == {"Speed": 2.0, "StartSpeed": 0.5, "Acceleration": 3.0}
    with pytest.raises(ValueError):
        host.set_motion_properties(speed=11, start_speed=0.5, accel=256)
    unrestricted = host.set_motion_properties(speed=20, start_speed=100, accel=4)
    assert unrestricted["Speed"] == 20  # No false 0..10 bound when driver limits are unavailable.
    core2 = FakeCore()
    host2 = make(tmp_path / "second", core2, allow_in_motion_speed_update=True)
    handle = host2.start_move(110, -50, timeout_s=5)
    with pytest.raises(ValueError):
        host2.set_motion_properties(speed=2, start_speed=0.5, accel=3, gate="in_motion")
    changed = host2.set_motion_properties(speed=2, gate="in_motion")
    assert changed["Speed"] == 2
    assert host2.poll(handle) is None


def test_relative_property_tolerance_accepts_small_quantization_and_rejects_stale_value(
    tmp_path,
):
    core = FakeCore()
    core.properties.update(Speed=100.0, StartSpeed=100.0, Acceleration=4.0)
    core.property_readback_offsets["Speed"] = 0.4
    host = make(tmp_path, core, motion_property_relative_tolerance=0.01)
    actual = host.set_motion_properties(speed=100, start_speed=100, accel=4)
    assert actual["Speed"] == 100.4
    assert actual["StartSpeed"] == 100

    stale_core = FakeCore()
    stale_core.property_readback_offsets["Speed"] = 5.0
    stale_host = make(tmp_path / "stale", stale_core, motion_property_relative_tolerance=0.01)
    with pytest.raises(RuntimeError, match="readback mismatch"):
        stale_host.set_motion_properties(speed=5, start_speed=100, accel=4)


@pytest.mark.parametrize("tolerance", [-0.01, float("nan"), 0.0501])
def test_property_relative_tolerance_rejects_invalid_or_broad_values(tmp_path, tolerance):
    with pytest.raises(ValueError, match="relative tolerance"):
        make(tmp_path, motion_property_relative_tolerance=tolerance)


def test_false_idle_with_changing_position_is_unknown_until_stable_reconciliation(
    tmp_path,
):
    core = FakeCore()
    host = make(tmp_path, core)
    handle = host.start_move(110, -50, timeout_s=3)
    core.busy = False  # Simulates Ludl Busy() returning false on serial status error.
    core.move_reads = [103.0, 105.0, 108.0, 109.5, 110.0]
    assert host.poll(handle) is None
    assert host._active is handle
    assert not host._unresolved  # Changing false-idle readbacks remain pending.
    x, y, busy = host.reconcile(stable_for_s=0.3, timeout_s=2)
    assert (x, y, busy) == (110.0, -50.0, False)
    assert not host._unresolved


def test_false_idle_overshoot_can_settle_into_target_before_deadline(tmp_path):
    core = FakeCore()
    host = make(tmp_path, core)
    handle = host.start_move(150, -50, timeout_s=3)
    core.busy = False
    core.move_reads = [151.5, 150.8, 150.3]
    result = poll_until_result(host, handle)
    assert result.status == "completed"
    assert result.actual_xy_um == (150.3, -50.0)


def test_stable_false_idle_off_target_remains_unknown_and_locked(tmp_path):
    core = FakeCore()
    host = make(tmp_path, core)
    handle = host.start_move(150, -50, timeout_s=3)
    core.advance([149.0, -50], busy=False)
    result = poll_until_result(host, handle)
    assert result.status == "outcome_unknown"
    assert host._unresolved
    with pytest.raises(RuntimeError):
        host.start_move(151, -50, timeout_s=1)


def test_displaced_start_keeps_expected_origin_envelope(tmp_path):
    core = FakeCore()
    core.xy[:] = [101.0, -49.5]
    with pytest.raises(RuntimeError, match="expected anchor"):
        make(tmp_path / "strict", core, expected_origin_xy_um=(100.0, -50.0))
    host = make(
        tmp_path / "resume",
        core,
        expected_origin_xy_um=(100.0, -50.0),
        allow_displaced_start=True,
    )
    assert host.origin_xy_um == (100.0, -50.0)
    assert host.envelope_xy_um == ((-1900.0, 2100.0), (-2050.0, 1950.0))


def test_expected_task_origin_is_enforced_before_host_is_ready(tmp_path):
    core = FakeCore()
    with pytest.raises(RuntimeError, match="expected anchor"):
        LudlMotionHost(
            core,
            tmp_path / "bad.jsonl",
            run_context={},
            expected_origin_xy_um=(101.0, -50.0),
        )


def test_active_speed_change_only_writes_speed(tmp_path):
    core = FakeCore()
    host = make(tmp_path, core, allow_in_motion_speed_update=True)
    before = dict(core.properties)
    handle = host.start_move(110, -50, timeout_s=3)
    host.set_motion_properties(speed=20, gate="in_motion")
    assert core.properties["Speed"] == 20
    assert core.properties["StartSpeed"] == before["StartSpeed"]
    assert core.properties["Acceleration"] == before["Acceleration"]
    assert host.poll(handle) is None


def test_jsonl_contains_action_lifecycle_and_context(tmp_path):
    core = FakeCore()
    host = make(tmp_path, core)
    handle = host.start_move(101, -50, timeout_s=2)
    core.advance([101, -50], busy=False)
    result = poll_until_result(host, handle)
    assert result.status == "completed"
    rows = [json.loads(line) for line in (tmp_path / "actions.jsonl").read_text().splitlines()]
    actions = [row for row in rows if row["record_type"] == "action"]
    assert {"proposed", "accepted", "started", "acknowledged", "completed"} <= {
        row["status"] for row in actions
    }
    assert all(row["run_context"]["run_id"] == "test-run" for row in actions)
