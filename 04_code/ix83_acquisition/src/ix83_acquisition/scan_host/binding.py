"""Pre-command validation of declared workflow needs against a device binding."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from planner.contracts import (
    AcquisitionSettings,
    ExecutionBindingSnapshot,
    ResourceRequirement,
)


def required_settings(settings: Sequence[AcquisitionSettings]) -> frozenset[str]:
    required = {"exposure_ms"}
    for item in settings:
        if item.channel_id is not None:
            required.add("channel")
        if item.roi_origin is not None:
            required.add("roi")
        if item.binning is not None:
            required.add("binning")
    return frozenset(required)


def validate_binding(
    backend: Any,
    *,
    capabilities: Iterable[str],
    resources: Sequence[ResourceRequirement],
    settings: Sequence[AcquisitionSettings],
) -> ExecutionBindingSnapshot:
    """Reject undeclared or unsupported workflow requirements before commands."""
    required_capabilities = set(capabilities)
    available_capabilities = getattr(backend, "capabilities", None)
    if available_capabilities is None:
        raise RuntimeError("backend does not declare required capabilities")
    missing_capabilities = required_capabilities - set(available_capabilities)
    if missing_capabilities:
        raise RuntimeError(
            f"backend lacks required capabilities: {', '.join(sorted(missing_capabilities))}"
        )

    required_resources = {requirement.name for requirement in resources}
    available_resources = getattr(backend, "resources", None)
    if available_resources is None:
        raise RuntimeError("backend must declare the resources it owns")
    missing_resources = required_resources - set(available_resources)
    if missing_resources:
        raise RuntimeError(
            f"backend lacks required resources: {', '.join(sorted(missing_resources))}"
        )

    requested_settings = required_settings(settings)
    available_settings = getattr(backend, "setting_capabilities", None)
    if available_settings is None:
        raise RuntimeError("backend must declare supported acquisition settings")
    unsupported_settings = requested_settings - set(available_settings)
    if unsupported_settings:
        raise RuntimeError(
            f"backend lacks required acquisition settings: {', '.join(sorted(unsupported_settings))}"
        )
    reference = getattr(backend, "binding_reference", None)
    if reference is not None and (not isinstance(reference, str) or not reference):
        raise ValueError("backend binding_reference must be a nonempty string")
    backend_type = type(backend)
    return ExecutionBindingSnapshot(
        provider=f"{backend_type.__module__}.{backend_type.__qualname__}",
        capabilities=frozenset(available_capabilities),
        resources=frozenset(available_resources),
        settings=frozenset(available_settings),
        reference=reference,
    )
