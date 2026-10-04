from types import SimpleNamespace

import pytest

from ix83_acquisition import MockCamera, MockXYZStage
from ix83_acquisition.mda import read_mda_settings
from ix83_acquisition.rtaspt_backend import RtasptBackend


def test_studio_fields_and_disabled_channels_are_normalized():
    settings = SimpleNamespace(
        channel_group=lambda: "Channel",
        use_frames=lambda: True,
        num_frames=lambda: 3,
        interval_ms=lambda: 50,
        channels=lambda: [
            SimpleNamespace(config="Demo", exposure=10, use_channel=True),
            SimpleNamespace(config="Disabled", exposure=10, use_channel=False),
        ],
        root=None,
        prefix="test",
        save=False,
    )
    studio = SimpleNamespace(
        acquisitions=lambda: SimpleNamespace(get_acquisition_settings=lambda: settings)
    )
    result = read_mda_settings(studio)
    assert result.frames == 3 and result.interval_s == 0.05
    assert len(result.channels) == 1 and result.channels[0].channel.preset == "Demo"
    assert result.output_dir == ""
    settings.use_slices = True
    with pytest.raises(ValueError, match="use_slices"):
        read_mda_settings(studio)
    settings.use_slices = False
    settings.use_channels = False
    with pytest.raises(ValueError, match="channel selection is disabled"):
        read_mda_settings(studio)


def test_rtaspt_compatibility_backend_uses_local_devices():
    backend = RtasptBackend(MockCamera(shape_yx=(8, 8)), MockXYZStage(), channel_group="Channel")
    image = backend.acquire(SimpleNamespace(color="Demo", exposure_ms=10))
    assert image.shape == (8, 8)
    backend.update_config(SimpleNamespace(acquisition=SimpleNamespace(channel_group="Other")))
    assert backend.channel_group == "Other"
    backend.close()
