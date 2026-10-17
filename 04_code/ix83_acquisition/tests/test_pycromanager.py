"""Regression coverage for Java Core stage readbacks without hardware."""

import unittest

from ix83_acquisition import Position
from ix83_acquisition.pycromanager import PycroManagerXYZStage


class ScalarReadbackCore:
    def get_xy_stage_device(self):
        return "XYStage"

    def get_xy_stage_position(self):
        raise AssertionError("Do not unpack the Java Point2D return value")

    def get_x_position(self, label):
        return 10.005

    def get_y_position(self, label):
        return 4.995

    def get_position(self, label):
        return 2.0


class StageReadbackTests(unittest.TestCase):
    def test_java_core_uses_scalar_xy_readbacks(self):
        stage = PycroManagerXYZStage(ScalarReadbackCore(), xy_stage="XYStage", z_stage="ZStage")
        self.assertEqual(stage.position, Position(10.005, 4.995, 2.0))

    def test_mismatched_stage_rejected_before_motion(self):
        stage = PycroManagerXYZStage(ScalarReadbackCore(), xy_stage="OtherStage", z_stage="ZStage")
        with self.assertRaisesRegex(RuntimeError, "expected 'OtherStage'"):
            stage.move_to(Position(1.0, 2.0, 3.0))

    def test_bounds_rejected_without_sending_device_commands(self):
        # This Core has readbacks only: any attempted write would fail the test.
        stage = PycroManagerXYZStage(
            ScalarReadbackCore(),
            xy_stage="XYStage",
            z_stage="ZStage",
            limits_um=((0, 1000), (0, 1000), (2, 2)),
        )
        for target in (Position(1000.1, 0, 2), Position(0, -0.1, 2), Position(0, 0, 3)):
            with self.assertRaisesRegex(ValueError, "outside stage limits"):
                stage.move_to(target)

    def test_invalid_bounds_rejected_at_construction(self):
        with self.assertRaisesRegex(ValueError, "finite and ordered"):
            PycroManagerXYZStage(
                ScalarReadbackCore(),
                xy_stage="XYStage",
                z_stage="ZStage",
                limits_um=((1, 0), (0, 1), (0, 1)),
            )


if __name__ == "__main__":
    unittest.main()
