"""Shared recorded-acquisition validation for bundle execution paths."""
from __future__ import annotations

from samplescout.contracts import AcquisitionSettings, DatasetReference


def validate_dataset_reference(
    reference: DatasetReference | None,
    settings: AcquisitionSettings,
    image_shape_yx: tuple[int, int],
) -> DatasetReference:
    """Require a complete typed dataset matching the requested image result."""
    if not isinstance(reference, DatasetReference):
        raise TypeError("completed acquisition requires a typed dataset reference")
    if reference.terminal_status != "completed":
        raise ValueError("acquisition dataset is not complete")
    if reference.frames_written != settings.frames:
        raise ValueError("dataset reference frame count does not match acquisition settings")
    if reference.shape[-2:] != image_shape_yx:
        raise ValueError("dataset reference image shape does not match acquisition result")
    if len(reference.axes) == 2:
        if reference.axes != "YX" or settings.frames != 1:
            raise ValueError("2D datasets can represent only one YX frame")
    elif (len(reference.axes) != 3 or reference.axes[0] not in {"Q", "T"}
          or reference.shape[0] != settings.frames):
        raise ValueError("datasets require YX or a matching QYX/TYX frame axis")
    return reference
