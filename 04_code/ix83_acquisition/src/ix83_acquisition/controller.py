"""Acquisition-only lifecycle extracted from RTASPT's live-controller pattern.

No analysis, GUI, device discovery, storage backend or automatic hardware startup.
Callbacks execute on the acquisition worker; callers route GUI updates separately.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field, replace
from itertools import repeat
from math import isfinite
from queue import Empty, SimpleQueue
from typing import Literal

from .interfaces import Camera, Channel, Frame, Position, SequenceCamera, XYZStage

RunState = Literal["completed", "cancelled", "failed"]


@dataclass(frozen=True)
class CaptureRequest:
    exposure_ms: float = 10.0
    position: Position | None = None
    channel: Channel | None = None
    timepoint: int = 0
    start_after_s: float | None = None
    target_id: str | None = None
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def validate(self) -> None:
        if not isfinite(self.exposure_ms) or self.exposure_ms <= 0:
            raise ValueError("exposure must be positive and finite")
        if self.timepoint < 0:
            raise ValueError("timepoint must be nonnegative")
        if self.start_after_s is not None and (
            not isfinite(self.start_after_s) or self.start_after_s < 0
        ):
            raise ValueError("requested start offset must be nonnegative and finite")


@dataclass(frozen=True)
class RunResult:
    run_id: str
    state: RunState
    frames_acquired: int
    error: str | None = None
    frames_requested: int | None = None


@dataclass(frozen=True)
class PreviewReady:
    run_id: str


@dataclass(frozen=True)
class SequenceRequest:
    frames: int
    exposure_ms: float = 50
    channel: Channel | None = None
    target_id: str | None = None
    timeout_s: float = 10
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def validate(self) -> None:
        if isinstance(self.frames, bool) or not isinstance(self.frames, int) or self.frames < 1:
            raise ValueError("sequence frame count must be a positive integer")
        if not isfinite(self.timeout_s) or self.timeout_s <= 0:
            raise ValueError("sequence timeout must be positive and finite")
        CaptureRequest(exposure_ms=self.exposure_ms).validate()


class AcquisitionController:
    """Single worker owns the camera/stage across preview and finite runs.

    The bounded preview ring may discard old frames. Finite-run callbacks receive
    every captured frame, independent of preview capacity. Stop is cooperative
    between driver calls and during waits; blocked drivers cannot be interrupted.
    """

    def __init__(self, camera: Camera, stage: XYZStage, *, preview_capacity: int = 16) -> None:
        if preview_capacity < 1:
            raise ValueError("preview capacity must be positive")
        self.camera = camera
        self.stage = stage
        self._frames: deque[Frame] = deque(maxlen=preview_capacity)
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._done = threading.Event()
        self._done.set()
        self._stop = threading.Event()
        self._state = "idle"
        self._closing = False
        self._result: RunResult | None = None
        self._events: SimpleQueue[PreviewReady | RunResult] = SimpleQueue()
        self._preview_pending = False
        self._run_id = ""

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    def preview(self) -> tuple[Frame, ...]:
        with self._lock:
            return tuple(self._frames)

    def drain_events(self) -> list[PreviewReady | RunResult]:
        with self._lock:
            events: list[PreviewReady | RunResult] = []
            while True:
                try:
                    events.append(self._events.get_nowait())
                except Empty:
                    break
            self._preview_pending = False
            return events

    def start_finite(
        self,
        requests: Iterable[CaptureRequest],
        *,
        interval_s: float = 0.0,
        on_frame: Callable[[Frame], None] | None = None,
    ) -> str:
        # Validate lazily so large scans need not allocate a second event table.
        return self._start(iter(requests), "finite", interval_s, on_frame)

    def start_free_run(self, request: CaptureRequest, *, interval_s: float = 0.1) -> str:
        request.validate()
        return self._start(repeat(request), "freerun", interval_s, None)

    def start_sequence(
        self,
        request: SequenceRequest,
        *,
        on_frame: Callable[[Frame], None] | None = None,
    ) -> str:
        """Own one fixed-position, fixed-channel native camera sequence."""
        request.validate()
        if not isinstance(self.camera, SequenceCamera):
            raise ValueError("camera does not support finite sequences")
        return self._start(iter(()), "sequence", 0, on_frame, request)

    def _start(
        self,
        requests: Iterator[CaptureRequest],
        mode: str,
        interval_s: float,
        on_frame: Callable[[Frame], None] | None,
        sequence_request: SequenceRequest | None = None,
    ) -> str:
        if not isfinite(interval_s) or interval_s < 0:
            raise ValueError("interval must be nonnegative and finite")
        with self._lock:
            if self._state == "closed" or self._closing:
                raise RuntimeError("controller is closed")
            if self._thread is not None and not self._done.is_set():
                raise RuntimeError("camera is already owned by an active acquisition")
            self._frames.clear()
            self.drain_events()
            self._result = None
            self._stop.clear()
            self._done = threading.Event()
            self._run_id = uuid.uuid4().hex
            self._state = mode
            self._thread = threading.Thread(
                target=self._run,
                args=(requests, mode, interval_s, on_frame, sequence_request),
                daemon=True,
            )
            self._thread.start()
            return self._run_id

    def _run(
        self,
        requests: Iterator[CaptureRequest],
        mode: str,
        interval_s: float,
        on_frame: Callable[[Frame], None] | None,
        sequence_request: SequenceRequest | None = None,
    ) -> None:
        count = 0
        outcome: RunState = "completed"
        error: str | None = None
        started = time.monotonic()

        def publish(frame: Frame) -> None:
            frame.pixels.flags.writeable = False
            with self._lock:
                self._frames.append(frame)
                if not self._preview_pending:
                    self._events.put(PreviewReady(self._run_id))
                    self._preview_pending = True
            if on_frame is not None:
                on_frame(frame)

        try:
            if sequence_request is not None:
                assert isinstance(self.camera, SequenceCamera)
                position = self.stage.position
                stream = self.camera.stream_sequence(
                    frames=sequence_request.frames,
                    exposure_ms=sequence_request.exposure_ms,
                    stage_position=position,
                    channel=sequence_request.channel,
                    stop_requested=self._stop.is_set,
                    timeout_s=sequence_request.timeout_s,
                )
                try:
                    for captured in stream:
                        frame = replace(
                            captured,
                            sequence=count,
                            timepoint=count,
                            request_id=f"{sequence_request.request_id}:{count}",
                            target_id=sequence_request.target_id,
                        )
                        count += 1
                        publish(frame)
                finally:
                    # Generator cleanup stops a native camera even if a sink fails.
                    close_stream = getattr(stream, "close", None)
                    if close_stream is not None:
                        close_stream()
                if not self._stop.is_set() and count != sequence_request.frames:
                    raise RuntimeError(f"incomplete sequence: {count}/{sequence_request.frames}")
            while not self._stop.is_set():
                try:
                    request = next(requests)
                except StopIteration:
                    break
                request.validate()
                offset_s = max(count * interval_s, request.start_after_s or 0.0)
                if self._stop.wait(max(0.0, started + offset_s - time.monotonic())):
                    break
                if self._stop.is_set():
                    break
                if request.position is not None:
                    self.stage.move_to(request.position)
                if self._stop.is_set():
                    break
                position = self.stage.position
                captured = self.camera.snap(
                    stage_position=position,
                    exposure_ms=request.exposure_ms,
                    channel=request.channel,
                )
                frame = replace(
                    captured,
                    sequence=count,
                    request_id=uuid.uuid4().hex if mode == "freerun" else request.request_id,
                    target_id=request.target_id,
                    timepoint=count if mode == "freerun" else request.timepoint,
                )
                count += 1
                publish(frame)
            if self._stop.is_set():
                outcome = "cancelled"
        except Exception as exc:
            outcome, error = "failed", f"{type(exc).__name__}: {exc}"
        finally:
            with self._lock:
                self._result = RunResult(
                    self._run_id,
                    outcome,
                    count,
                    error,
                    sequence_request.frames if sequence_request is not None else None,
                )
                self._state = "closing" if self._closing else "idle"
                self._events.put(self._result)
                self._done.set()

    def wait(self, timeout: float | None = None) -> RunResult:
        with self._lock:
            thread = self._thread
            run_id = self._run_id
            done = self._done
        if thread is None:
            raise RuntimeError("no acquisition has been started")
        if thread is threading.current_thread():
            raise RuntimeError("cannot join the acquisition worker from its callback")
        # Explicit worker completion retains ownership across interrupted joins
        # and signals; a thread object's reported liveness is not device cleanup.
        if not done.wait(timeout):
            raise TimeoutError("acquisition worker is still running")
        with self._lock:
            if self._run_id != run_id:
                raise RuntimeError("another acquisition replaced this run before wait completed")
            if self._result is None:
                raise RuntimeError("acquisition ended without a result")
            return self._result

    def stop(self, timeout: float = 5.0) -> RunResult:
        self.request_stop()
        return self.wait(timeout)

    def request_stop(self) -> None:
        """Signal cancellation without joining; safe from a frame callback."""
        self._stop.set()

    def close(self, timeout: float = 5.0) -> None:
        # Serialize close/start, and leave resources open if the worker times out.
        with self._lock:
            if self._state == "closed":
                return
            thread = self._thread
            self._closing = True
            self._state = "closing"
            self._stop.set()
        if thread is not None:
            self.wait(timeout)
        with self._lock:
            self._state = "closed"
            try:
                self.camera.close()
            finally:
                self.stage.close()
