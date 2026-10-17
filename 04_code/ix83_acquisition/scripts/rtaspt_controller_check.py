"""Exercise RTASPT's real GUI controller/MDA runner with local mock devices.

No napari window or Micro-Manager connection is opened. Run on Python 3.12
with the rtaspt-controller-check extra; Qt tests use the offscreen platform.
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import numpy as np

package_root = Path(__file__).resolve().parents[1]
bundle_root = package_root.parents[1]
sys.path.insert(0, str(package_root / "src"))
sys.path.insert(0, str(bundle_root / "03_external/Realtime-Anisotropy-SPT-Analysis/src"))


def main() -> None:
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError("RTASPT requires Python 3.12")
    from rtaspt.cli import _make_live_mda_runner
    from rtaspt.config import load_config
    from rtaspt.io import read_tiff
    from rtaspt.live import LiveAcquisitionController, LiveError, MDAComplete, MDASettings

    from ix83_acquisition import MockCamera, MockXYZStage
    from ix83_acquisition.rtaspt_backend import RtasptBackend

    with TemporaryDirectory(prefix="ix83-controller-") as temporary:
        config = load_config(package_root / "configs/rtaspt_mock.yaml")
        config = replace(
            config,
            acquisition=replace(
                config.acquisition, output_dir=temporary, interval_s=0.01, interval_ms=10
            ),
        )
        captures = []
        backends = []
        closed = []

        class Backend(RtasptBackend):
            def acquire(self, event):
                pixels = super().acquire(event)
                captures.append((event, pixels.copy()))
                return pixels

            def close(self):
                super().close()
                closed.append(self)

        def factory(runtime):
            backend = Backend(
                MockCamera(shape_yx=(96, 96)),
                MockXYZStage(),
                channel_group=runtime.acquisition.channel_group,
            )
            backends.append(backend)
            return backend

        settings_reads = []

        def settings_loader(current):
            # The initial free-run snapshot is 10 ms. During MDA the real
            # controller refreshes before each timepoint; later reads use 20 ms.
            settings_reads.append(True)
            exposure = 20 if len(settings_reads) >= 4 else 10
            channels = (replace(config.acquisition.channels[0], exposure_ms=exposure),)
            return MDASettings("Channel", channels, 3, 10, temporary, "controller")

        runner = _make_live_mda_runner(SimpleNamespace(channel=None), (), backend_factory=factory)
        controller = LiveAcquisitionController(
            config, mda_runner=runner, settings_loader=settings_loader, backend_factory=factory
        )

        def wait_until(predicate):
            deadline = time.monotonic() + 5
            while not predicate():
                if time.monotonic() > deadline:
                    raise TimeoutError("controller did not complete")
                time.sleep(0.01)

        try:
            controller.start_freerun()
            wait_until(lambda: len(captures) >= 2)
            controller.stop_freerun()
            wait_until(lambda: controller.state == "idle")
            live_count = len(captures)
            assert len(closed) == 1
            captures.clear()
            controller.start_mda()
            wait_until(lambda: controller.state in ("idle", "failed"))
            events = controller.drain_events()
            errors = [event for event in events if isinstance(event, LiveError)]
            assert not errors, errors
            (complete,) = [event for event in events if isinstance(event, MDAComplete)]
            raw, axes = read_tiff(complete.result.acquisition.raw_path)
            np.testing.assert_array_equal(raw, np.stack([pixels for _, pixels in captures]))
            assert axes == "QYX" and len(captures) == 3
            exposures = [event.exposure_ms for event, _ in captures]
            assert exposures == [10, 20, 20], exposures
            assert len(backends) == len(closed) == 2
            print(
                json.dumps(
                    {
                        "result": "PASS",
                        "free_run_frames": live_count,
                        "mda_frames": len(captures),
                        "exposures_ms": exposures,
                        "raw_pixels_equal": True,
                        "backends_closed": len(closed),
                    },
                    indent=2,
                )
            )
        finally:
            controller.shutdown()


if __name__ == "__main__":
    main()
