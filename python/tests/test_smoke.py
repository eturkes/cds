"""Phase 0 smoke tests for the Python harness.

Schema-bound tests for the four conceptual data schemas
(`ClinicalTelemetryPayload`, `OnionL_IR_Tree`, `SMT_Constraint_Matrix`,
`Formal_Verification_Trace`) land in Task 2.
"""

from __future__ import annotations

from cds_harness import HARNESS_ID, PHASE, __version__


def test_harness_id_is_stable() -> None:
    assert HARNESS_ID == "cds-harness"


def test_phase_zero_is_active() -> None:
    assert PHASE == 0, "phase marker must remain 0 until Task 5 lands"


def test_version_string_shape() -> None:
    parts = __version__.split(".")
    assert len(parts) == 3, f"semver shape required, got {__version__!r}"
    assert all(p.isdigit() for p in parts), f"all components must be numeric: {__version__!r}"
