"""Bounded, journaled XY diagnostics for the loaded Ludl/DemoCamera profile.

Successful in-motion polls are retained as timestamp-bracketed raw position
samples. These are host-timed controller readbacks, not encoder latches or
exposure-synchronous positions. This module never connects to Micro-Manager;
the caller owns a constructed Core.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite
from pathlib import Path
from typing import Any
from uuid import uuid4

EXPECTED_DEVICES = {
    "COM22": ("SerialManager", "COM22"),
    "LudlController": ("Ludl", "LudlController"),
    "XYStage": ("Ludl", "XYStage"),
    "DHub": ("DemoCamera", "DHub"),
    "Camera": ("DemoCamera", "DCam"),
    "ZStage": ("DemoCamera", "DStage"),
}


def _utc() -> str:
    return datetime.now(UTC).isoformat()


def _finite(value: float, label: str) -> float:
    value = float(value)
    if not isfinite(value):
        raise ValueError(f"{label} must be finite")
    return value


def _labels(devices: Any) -> list[str]:
    if hasattr(devices, "size"):
        return [str(devices.get(i)) for i in range(devices.size())]
    return [str(item) for item in devices]


@dataclass
class MotionHandle:
    request_id: str
    target_xy_um: tuple[float, float]
    deadline_monotonic: float
    started_monotonic: float
    started_utc: str
    acknowledged_monotonic: float
    acknowledged_utc: str
    ack_latency_s: float
    status: str = "started"
    polls: int = 0
    latest_xy_um: tuple[float, float] | None = None
    latest_busy: bool | None = None
    stop_issued: bool = False
    idle_anchor_xy_um: tuple[float, float] | None = None
    idle_stable_since: float | None = None


@dataclass(frozen=True)
class MotionResult:
    request_id: str
    status: str
    target_xy_um: tuple[float, float]
    actual_xy_um: tuple[float, float]
    busy: bool
    ack_latency_s: float
    started_monotonic: float
    acknowledged_monotonic: float
    finished_monotonic: float
    started_utc: str
    acknowledged_utc: str
    finished_utc: str
    polls: int
    error: str | None = None


class LudlMotionHost:
    """Single-command authority for finite XY moves in an immutable envelope."""

    def __init__(
        self,
        core: Any,
        journal: str | Path,
        *,
        run_context: dict[str, Any],
        tolerance_um: float = 0.5,
        poll_interval_s: float = 0.05,
        allow_in_motion_speed_update: bool = False,
        expected_origin_xy_um: tuple[float, float] | None = None,
        allow_displaced_start: bool = False,
        motion_property_relative_tolerance: float = 0.0,
    ) -> None:
        self.core = core
        self.journal = Path(journal)
        if self.journal.exists():
            raise FileExistsError(self.journal)
        self.run_context = dict(run_context)
        self.tolerance = _finite(tolerance_um, "tolerance")
        self.poll_interval = _finite(poll_interval_s, "poll interval")
        self.motion_property_relative_tolerance = _finite(
            motion_property_relative_tolerance, "motion property relative tolerance"
        )
        if self.tolerance <= 0 or self.poll_interval <= 0:
            raise ValueError("tolerance and poll interval must be positive")
        if not 0 <= self.motion_property_relative_tolerance <= 0.05:
            raise ValueError("motion property relative tolerance must be between 0 and 0.05")
        self.allow_in_motion_speed_update = bool(allow_in_motion_speed_update)
        self._active: MotionHandle | None = None
        self._unresolved = False
        self._check_profile()
        initial_xy = self._read_xy()
        self.origin_xy_um = initial_xy
        if expected_origin_xy_um is not None:
            expected = (
                _finite(expected_origin_xy_um[0], "expected X"),
                _finite(expected_origin_xy_um[1], "expected Y"),
            )
            if (
                not allow_displaced_start
                and max(abs(initial_xy[i] - expected[i]) for i in range(2)) > self.tolerance
            ):
                raise RuntimeError(
                    f"initial XY {self.origin_xy_um} does not match expected anchor {expected}"
                )
            self.origin_xy_um = expected
        elif allow_displaced_start:
            raise ValueError("allow_displaced_start requires expected_origin_xy_um")
        self.fixed_z_um = _finite(core.get_position("ZStage"), "initial Z")
        self.envelope_xy_um = (
            (self.origin_xy_um[0] - 2000, self.origin_xy_um[0] + 2000),
            (self.origin_xy_um[1] - 2000, self.origin_xy_um[1] + 2000),
        )
        self._validate_readback(initial_xy)
        self.initial_motion_properties = {
            prop: _finite(core.get_property("XYStage", prop), prop)
            for prop in ("Speed", "StartSpeed", "Acceleration")
        }
        self._write_run_header()

    def _check_profile(self) -> None:
        labels = [x for x in _labels(self.core.get_loaded_devices()) if x != "Core"]
        actual = {
            name: (
                str(self.core.get_device_library(name)),
                str(self.core.get_device_name(name)),
            )
            for name in labels
        }
        if actual != EXPECTED_DEVICES:
            raise RuntimeError(f"loaded device inventory mismatch: {actual}")
        if str(self.core.get_property("LudlController", "Port")) != "COM22":
            raise RuntimeError("LudlController is not assigned to COM22")
        if (
            self.core.get_camera_device(),
            self.core.get_xy_stage_device(),
            self.core.get_focus_device(),
        ) != ("Camera", "XYStage", "ZStage"):
            raise RuntimeError("Core camera/XY/focus roles do not match the diagnostic profile")
        if self.core.is_sequence_running() or self.core.get_remaining_image_count():
            raise RuntimeError("stop Live and clear camera acquisition before motion diagnostics")
        if self.core.get_auto_shutter() or self.core.get_shutter_device():
            raise RuntimeError("diagnostic requires automatic shutter and shutter device disabled")

    def _read_xy(self) -> tuple[float, float]:
        return (
            _finite(self.core.get_x_position("XYStage"), "X readback"),
            _finite(self.core.get_y_position("XYStage"), "Y readback"),
        )

    def _verify_fixed_z(self) -> float:
        z = _finite(self.core.get_position("ZStage"), "Z readback")
        if abs(z - self.fixed_z_um) > self.tolerance:
            raise RuntimeError(f"Z readback changed from fixed origin: {z} vs {self.fixed_z_um} um")
        return z

    def _write_run_header(self) -> None:
        self.journal.parent.mkdir(parents=True, exist_ok=True)
        header = {
            "record_type": "run",
            "created_utc": _utc(),
            "run_context": self.run_context,
            "origin_xy_um": self.origin_xy_um,
            "fixed_z_um": self.fixed_z_um,
            "envelope_xy_um": self.envelope_xy_um,
            "profile_devices": EXPECTED_DEVICES,
            "initial_motion_properties": self.initial_motion_properties,
            "position_sample_schema_version": 1,
            "position_sampling_method": (
                "host polling around sequential controller XY readback calls; "
                "not encoder-latched or camera-exposure-synchronized"
            ),
            "position_poll_interval_s": self.poll_interval,
        }
        self.journal.write_text(json.dumps(header, allow_nan=False) + "\n", encoding="utf-8")

    def _log(
        self,
        request_id: str,
        action: str,
        status: str,
        *,
        parameters: dict[str, Any],
        timestamps: dict[str, Any] | None = None,
        readback: Any = None,
        error: str | None = None,
    ) -> None:
        entry = {
            "record_type": "action",
            "request_id": request_id,
            "action": action,
            "status": status,
            "utc": _utc(),
            "run_context": self.run_context,
            "parameters": parameters,
            "timestamps": timestamps or {},
            "readback": readback,
            "error": error,
        }
        with self.journal.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry, allow_nan=False) + "\n")
            stream.flush()

    def _read_xy_timed(
        self,
    ) -> tuple[tuple[float, float], dict[str, tuple[int, int]]]:
        """Read each axis separately and preserve each host call interval."""
        x_start_ns = time.monotonic_ns()
        x_raw = self.core.get_x_position("XYStage")
        x_end_ns = time.monotonic_ns()
        y_start_ns = time.monotonic_ns()
        y_raw = self.core.get_y_position("XYStage")
        y_end_ns = time.monotonic_ns()
        xy = (
            _finite(x_raw, "X readback"),
            _finite(y_raw, "Y readback"),
        )
        return xy, {"x": (x_start_ns, x_end_ns), "y": (y_start_ns, y_end_ns)}

    def _log_stage_position_sample(
        self,
        handle: MotionHandle,
        xy: tuple[float, float],
        busy: bool,
        axis_intervals_ns: dict[str, tuple[int, int]],
        busy_interval_ns: tuple[int, int],
    ) -> None:
        x_start, x_end = axis_intervals_ns["x"]
        y_start, y_end = axis_intervals_ns["y"]
        sample_midpoint_estimate_ns = (x_start + x_end + y_start + y_end) // 4
        entry = {
            "record_type": "stage_position_sample",
            "schema_version": 1,
            "event_id": f"{handle.request_id}:xy:{handle.polls:06d}",
            "request_id": handle.request_id,
            "sequence": handle.polls,
            "run_context": self.run_context,
            "device": "XYStage",
            "axes": ["x", "y"],
            "units": "um",
            "source": "controller_readback",
            "position_um": {"x": xy[0], "y": xy[1]},
            "stage_busy": busy,
            "motion_state": "reported_busy" if busy else "reported_not_busy",
            "timestamps": {
                "host_utc": _utc(),
                "host_clock_domain": "time.monotonic_ns",
                "host_monotonic_midpoint_estimate_ns": sample_midpoint_estimate_ns,
                "host_monotonic_bracket_ns": [x_start, y_end],
                "axis_readback_call_intervals_ns": {
                    axis: list(interval) for axis, interval in axis_intervals_ns.items()
                },
                "busy_call_interval_ns": list(busy_interval_ns),
            },
        }
        with self.journal.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry, allow_nan=False) + "\n")
            stream.flush()

    def _validate_target(self, x: float, y: float) -> tuple[float, float]:
        target = (_finite(x, "target X"), _finite(y, "target Y"))
        if not all(
            low <= value <= high
            for value, (low, high) in zip(target, self.envelope_xy_um, strict=True)
        ):
            raise ValueError("target outside immutable ±2000 um initial-origin envelope")
        return target

    def _validate_readback(self, xy: tuple[float, float]) -> None:
        if any(
            not low <= value <= high
            for value, (low, high) in zip(xy, self.envelope_xy_um, strict=True)
        ):
            raise RuntimeError(f"XY readback {xy} is outside immutable motion envelope")

    def _require_stable_idle(self) -> tuple[float, float]:
        self._check_profile()
        current = self._read_xy()
        self._validate_readback(current)
        self._verify_fixed_z()
        if bool(self.core.device_busy("XYStage")):
            self._unresolved = True
            raise RuntimeError("XYStage reports busy before a new action")
        stable_since = time.monotonic()
        stable_anchor = current
        while time.monotonic() - stable_since < 0.3:
            time.sleep(min(self.poll_interval, 0.05))
            now = self._read_xy()
            self._validate_readback(now)
            self._verify_fixed_z()
            if (
                bool(self.core.device_busy("XYStage"))
                or max(abs(now[i] - stable_anchor[i]) for i in range(2)) > self.tolerance / 4
            ):
                self._unresolved = True
                raise RuntimeError("XYStage was not stably idle before a new action")
        return current

    def start_move(self, x_um: float, y_um: float, *, timeout_s: float) -> MotionHandle:
        if self._unresolved or self._active is not None:
            raise RuntimeError("reconcile the previous move before issuing another command")
        target = self._validate_target(x_um, y_um)  # Always validate before command.
        timeout_s = _finite(timeout_s, "timeout")
        if timeout_s <= 0:
            raise ValueError("timeout must be positive")
        self._require_stable_idle()
        request_id = str(uuid4())
        params = {
            "target_xy_um": target,
            "fixed_z_um": self.fixed_z_um,
            "timeout_s": timeout_s,
        }
        proposed = time.monotonic()
        self._log(
            request_id,
            "move_xy",
            "proposed",
            parameters=params,
            timestamps={"proposed_monotonic": proposed, "proposed_utc": _utc()},
        )
        self._log(request_id, "move_xy", "accepted", parameters=params)
        started = time.monotonic()
        started_utc = _utc()
        self._log(
            request_id,
            "move_xy",
            "started",
            parameters=params,
            timestamps={"started_monotonic": started, "started_utc": started_utc},
        )
        try:
            self.core.set_xy_position(*target)  # Deliberately no wait_for_device.
        except Exception as exc:
            self._unresolved = True
            self._log(
                request_id,
                "move_xy",
                "outcome_unknown",
                parameters=params,
                timestamps={"started_monotonic": started},
                error=f"{type(exc).__name__}: {exc}",
            )
            raise
        ack = time.monotonic()
        ack_utc = _utc()
        handle = MotionHandle(
            request_id,
            target,
            started + timeout_s,
            started,
            started_utc,
            ack,
            ack_utc,
            ack - started,
        )
        self._active = handle
        self._log(
            request_id,
            "move_xy",
            "acknowledged",
            parameters=params,
            timestamps={
                "started_monotonic": started,
                "acknowledged_monotonic": ack,
                "started_utc": started_utc,
                "acknowledged_utc": ack_utc,
                "ack_latency_s": ack - started,
            },
        )
        return handle

    def poll(self, handle: MotionHandle) -> MotionResult | None:
        if handle is not self._active:
            raise RuntimeError("handle is not the active move")
        try:
            xy, axis_intervals_ns = self._read_xy_timed()
            self._validate_readback(xy)
            self._verify_fixed_z()
            busy_start_ns = time.monotonic_ns()
            busy = bool(self.core.device_busy("XYStage"))
            busy_end_ns = time.monotonic_ns()
        except Exception as exc:
            self._unresolved = True
            handle.status = "outcome_unknown"
            self._log(
                handle.request_id,
                "move_xy",
                handle.status,
                parameters={"target_xy_um": handle.target_xy_um},
                error=f"{type(exc).__name__}: {exc}",
            )
            raise RuntimeError("move readback failed; reconcile before another action") from exc
        handle.polls += 1
        handle.latest_xy_um, handle.latest_busy = xy, busy
        try:
            self._log_stage_position_sample(
                handle,
                xy,
                busy,
                axis_intervals_ns,
                (busy_start_ns, busy_end_ns),
            )
        except Exception as exc:
            # Journal failure during motion makes both the telemetry and action
            # record incomplete. Stop first: the usual stop helper logs before
            # issuing Core.stop(), so it cannot safely be used here.
            handle.status = "outcome_unknown"
            self._unresolved = True
            handle.stop_issued = True
            stop_error = None
            try:
                self.core.stop("XYStage")
            except Exception as stop_exc:  # noqa: BLE001 - preserve lock on any stop failure.
                stop_error = f"{type(stop_exc).__name__}: {stop_exc}"
            suffix = (
                f" Core.stop also failed: {stop_error}."
                if stop_error
                else " Core.stop was issued; stable state still requires reconciliation."
            )
            raise RuntimeError(
                "position telemetry journal write failed during motion; "
                "motion is locked pending read-only reconcile()." + suffix
            ) from exc
        delta = max(abs(xy[0] - handle.target_xy_um[0]), abs(xy[1] - handle.target_xy_um[1]))
        if busy:
            handle.idle_anchor_xy_um = None
            handle.idle_stable_since = None
        elif (
            handle.idle_anchor_xy_um is None
            or max(abs(xy[i] - handle.idle_anchor_xy_um[i]) for i in range(2)) > self.tolerance / 4
        ):
            handle.idle_anchor_xy_um, handle.idle_stable_since = xy, time.monotonic()
        elif (
            handle.idle_stable_since is not None
            and time.monotonic() - handle.idle_stable_since >= 0.3
        ):
            if delta <= self.tolerance:
                handle.status = "completed"
                return self._finish(handle, xy, busy)
            handle.status = "outcome_unknown"
            self._unresolved = True
            return self._finish(
                handle,
                xy,
                busy,
                status="outcome_unknown",
                error="Busy false and stable readback outside target tolerance",
            )
        if time.monotonic() >= handle.deadline_monotonic:
            self._stop_and_reconcile(handle, "deadline expired")
            xy = handle.latest_xy_um or xy
            busy = handle.latest_busy if handle.latest_busy is not None else busy
            if handle.status == "completed":
                return self._finish(handle, xy, busy)
            return self._finish(handle, xy, busy, status=handle.status, error="deadline expired")
        return None

    def _stop_and_reconcile(self, handle: MotionHandle, reason: str) -> None:
        params = {"target_xy_um": handle.target_xy_um}
        if handle.stop_issued:
            return
        handle.stop_issued = True
        stop_id = str(uuid4())
        self._log(stop_id, "stop_xy", "proposed", parameters={"reason": reason, **params})
        self._log(stop_id, "stop_xy", "accepted", parameters={"reason": reason, **params})
        self._log(stop_id, "stop_xy", "started", parameters={"reason": reason, **params})
        try:
            self.core.stop("XYStage")
            stable_since = None
            stable_xy = None
            reconcile_deadline = time.monotonic() + max(2.0, self.poll_interval * 10)
            while time.monotonic() < reconcile_deadline:
                xy = self._read_xy()
                self._validate_readback(xy)
                self._verify_fixed_z()
                busy = bool(self.core.device_busy("XYStage"))
                handle.latest_xy_um, handle.latest_busy = xy, busy
                if busy:
                    stable_since, stable_xy = None, None
                elif (
                    stable_xy is None
                    or max(abs(xy[i] - stable_xy[i]) for i in range(2)) > self.tolerance / 4
                ):
                    stable_xy, stable_since = xy, time.monotonic()
                elif stable_since is not None and time.monotonic() - stable_since >= 0.3:
                    handle.status = (
                        "completed"
                        if max(abs(xy[i] - handle.target_xy_um[i]) for i in range(2))
                        <= self.tolerance
                        else ("cancelled" if reason == "cancelled" else "failed")
                    )
                    self._unresolved = False
                    self._log(
                        stop_id,
                        "stop_xy",
                        "completed",
                        parameters={"reason": reason, **params},
                        readback={
                            "actual_xy_um": xy,
                            "busy": busy,
                            "stable_for_s": 0.3,
                        },
                    )
                    return
                time.sleep(min(self.poll_interval, 0.05))
            handle.status = "outcome_unknown"
            self._unresolved = True
            self._log(
                stop_id,
                "stop_xy",
                "outcome_unknown",
                parameters={"reason": reason, **params},
                readback={
                    "actual_xy_um": handle.latest_xy_um,
                    "busy": handle.latest_busy,
                },
                error="stop reconciliation did not establish 0.3 s stable idle readback",
            )
        except Exception as exc:  # noqa: BLE001 - any failed device RPC makes motion outcome uncertain.
            handle.status = "outcome_unknown"
            self._unresolved = True
            self._log(
                stop_id,
                "stop_xy",
                "outcome_unknown",
                parameters={"reason": reason},
                error=f"{type(exc).__name__}: {exc}",
            )

    def _finish(
        self,
        handle: MotionHandle,
        xy: tuple[float, float],
        busy: bool,
        *,
        status: str | None = None,
        error: str | None = None,
    ) -> MotionResult:
        final_status = status or handle.status
        finished, finished_utc = time.monotonic(), _utc()
        self._log(
            handle.request_id,
            "move_xy",
            final_status,
            parameters={"target_xy_um": handle.target_xy_um},
            timestamps={"finished_monotonic": finished, "finished_utc": finished_utc},
            readback={"actual_xy_um": xy, "busy": busy},
            error=error,
        )
        if final_status != "outcome_unknown":
            self._active = None
        return MotionResult(
            handle.request_id,
            final_status,
            handle.target_xy_um,
            xy,
            busy,
            handle.ack_latency_s,
            handle.started_monotonic,
            handle.acknowledged_monotonic,
            finished,
            handle.started_utc,
            handle.acknowledged_utc,
            finished_utc,
            handle.polls,
            error,
        )

    def wait(
        self, handle: MotionHandle, *, cancelled: Callable[[], bool] = lambda: False
    ) -> MotionResult:
        while True:
            if cancelled():
                self._stop_and_reconcile(handle, "cancelled")
                xy, busy = handle.latest_xy_um, handle.latest_busy
                if xy is None or busy is None:
                    self._unresolved = True
                    return self._finish(
                        handle,
                        self._read_xy(),
                        True,
                        status="outcome_unknown",
                        error="cancel reconciliation failed",
                    )
                return self._finish(
                    handle,
                    xy,
                    busy,
                    status=handle.status,
                    error="cancelled" if handle.status == "cancelled" else handle.status,
                )
            result = self.poll(handle)
            if result is not None:
                return result
            time.sleep(self.poll_interval)

    def reconcile(
        self, *, stable_for_s: float = 0.3, timeout_s: float = 3.0
    ) -> tuple[float, float, bool]:
        """Read current state after an unknown result; never issues motion."""
        stable_for_s, timeout_s = (
            _finite(stable_for_s, "stable duration"),
            _finite(timeout_s, "timeout"),
        )
        if stable_for_s < 0.3 or timeout_s < stable_for_s:
            raise ValueError("reconciliation requires at least 0.3 s stability within timeout")
        deadline = time.monotonic() + timeout_s
        stable_since = None
        stable_anchor = None
        xy, busy = self._read_xy(), True
        while time.monotonic() < deadline:
            xy = self._read_xy()
            self._validate_readback(xy)
            self._verify_fixed_z()
            busy = bool(self.core.device_busy("XYStage"))
            if busy:
                stable_since, stable_anchor = None, None
            elif (
                stable_anchor is None
                or max(abs(xy[i] - stable_anchor[i]) for i in range(2)) > self.tolerance / 4
            ):
                stable_anchor, stable_since = xy, time.monotonic()
            elif stable_since is not None and time.monotonic() - stable_since >= stable_for_s:
                self._unresolved = False
                self._active = None
                return xy[0], xy[1], False
            time.sleep(min(self.poll_interval, 0.05))
        self._unresolved = True
        raise RuntimeError("reconciliation did not establish stable idle readbacks within timeout")

    def set_motion_properties(
        self,
        *,
        speed: float,
        start_speed: float | None = None,
        accel: int | None = None,
        gate: str = "pre_move",
    ) -> dict[str, float]:
        if gate not in {"pre_move", "in_motion"}:
            raise ValueError("gate must be pre_move or in_motion")
        if self._unresolved:
            raise RuntimeError("reconcile motion outcome before changing properties")
        if gate == "in_motion" and (self._active is None or not self.allow_in_motion_speed_update):
            raise RuntimeError("in-motion speed updates are not enabled for this host")
        if gate == "pre_move" and self._active is not None:
            raise RuntimeError("pre-move properties cannot change during a move")
        if gate == "pre_move":
            self._require_stable_idle()
        if gate == "in_motion" and (start_speed is not None or accel is not None):
            raise ValueError("in-motion updates may change Speed only")
        requested = {"Speed": _finite(speed, "speed")}
        if gate == "pre_move":
            if start_speed is None or accel is None:
                raise ValueError("pre_move requires speed, start_speed and accel")
            requested["StartSpeed"] = _finite(start_speed, "start speed")
            requested["Acceleration"] = _finite(accel, "acceleration")
        if any(value <= 0 for prop, value in requested.items() if prop != "Acceleration"):
            raise ValueError("Speed and StartSpeed must be positive")
        if "Acceleration" in requested and (
            not requested["Acceleration"].is_integer() or not 1 <= requested["Acceleration"] <= 255
        ):
            raise ValueError("Acceleration must be an integer from 1 through 255")
        request_id = str(uuid4())
        self._log(
            request_id,
            "set_motion_properties",
            "proposed",
            parameters={
                "gate": gate,
                "requested": requested,
                "relative_tolerance": self.motion_property_relative_tolerance,
            },
        )
        self._log(
            request_id,
            "set_motion_properties",
            "accepted",
            parameters={
                "gate": gate,
                "requested": requested,
                "relative_tolerance": self.motion_property_relative_tolerance,
            },
        )
        started = time.monotonic()
        self._log(
            request_id,
            "set_motion_properties",
            "started",
            parameters={
                "gate": gate,
                "requested": requested,
                "relative_tolerance": self.motion_property_relative_tolerance,
            },
            timestamps={"started_monotonic": started, "started_utc": _utc()},
        )
        try:
            for prop, value in requested.items():
                if bool(self.core.has_property_limits("XYStage", prop)):
                    low = _finite(
                        self.core.get_property_lower_limit("XYStage", prop),
                        f"{prop} lower limit",
                    )
                    high = _finite(
                        self.core.get_property_upper_limit("XYStage", prop),
                        f"{prop} upper limit",
                    )
                    if not low <= value <= high:
                        raise ValueError(f"{prop} outside device limits [{low}, {high}]")
            for prop, value in requested.items():
                self.core.set_property("XYStage", prop, str(value))
            actual = {
                prop: _finite(self.core.get_property("XYStage", prop), f"{prop} readback")
                for prop in requested
            }
            mismatches = {
                prop: (actual[prop], value)
                for prop, value in requested.items()
                if abs(actual[prop] - value)
                > (
                    abs(value) * self.motion_property_relative_tolerance
                    if prop in {"Speed", "StartSpeed"}
                    else 0.0
                )
            }
            if mismatches:
                raise RuntimeError(f"motion-property readback mismatch: {mismatches}")
        except Exception as exc:
            self._log(
                request_id,
                "set_motion_properties",
                "failed",
                parameters={
                    "gate": gate,
                    "requested": requested,
                    "relative_tolerance": self.motion_property_relative_tolerance,
                },
                readback=actual if "actual" in locals() else None,
                error=f"{type(exc).__name__}: {exc}",
            )
            raise
        self._log(
            request_id,
            "set_motion_properties",
            "completed",
            parameters={
                "gate": gate,
                "requested": requested,
                "relative_tolerance": self.motion_property_relative_tolerance,
            },
            readback=actual,
        )
        return actual
