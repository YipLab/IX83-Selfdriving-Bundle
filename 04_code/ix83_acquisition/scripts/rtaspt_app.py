"""Run RTASPT's CLI/GUI with the bundle's single-camera acquisition backend.

Use Python 3.12 with RTASPT's processing dependencies installed. This launcher
does not load a Micro-Manager configuration. Demo mode refuses real devices.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

package_root = Path(__file__).resolve().parents[1]
bundle_root = package_root.parents[1]
sys.path.insert(0, str(package_root / "src"))
sys.path.insert(0, str(bundle_root / "03_external/Realtime-Anisotropy-SPT-Analysis/src"))


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--devices", choices=("mock", "demo"), default="mock")
    options, arguments = parser.parse_known_args()
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError("RTASPT requires Python 3.12")
    from rtaspt.cli import main as run_app

    from ix83_acquisition import MockCamera, MockXYZStage
    from ix83_acquisition.rtaspt_backend import RtasptBackend

    def backend_factory(config):
        if config.detector_config.type != "single":
            raise ValueError("The bundle baseline requires detector_config.type: single")
        if options.devices == "mock":
            camera = MockCamera(shape_yx=config.acquisition.image_shape,
                                seed=config.acquisition.random_seed)
            stage = MockXYZStage()
        else:
            from ix83_acquisition.pycromanager import (
                PycroManagerCamera,
                PycroManagerXYZStage,
                connect_core,
            )

            core = connect_core()
            devices = core.get_loaded_devices()
            for index in range(devices.size()):
                label = devices.get(index)
                if label != "Core" and core.get_device_library(label) != "DemoCamera":
                    raise RuntimeError(f"Demo mode refuses loaded real device {label!r}")
            if (core.get_camera_device(), core.get_xy_stage_device(), core.get_focus_device()) != (
                "Camera", "XYStage", "ZStage",
            ):
                raise RuntimeError("Load ix83_demo_mmconfig.cfg before using demo mode")
            if core.is_sequence_running():
                raise RuntimeError("Stop MMStudio Live before acquiring")
            camera = PycroManagerCamera(core)
            stage = PycroManagerXYZStage(core, xy_stage="XYStage", z_stage="ZStage")
        return RtasptBackend(camera, stage, channel_group=config.acquisition.channel_group)

    return run_app(arguments, backend_factory=backend_factory)


if __name__ == "__main__":
    raise SystemExit(main())
