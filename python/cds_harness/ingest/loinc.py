"""LOINC ↔ canonical-vital mapping (Phase 1, ADR-025 §4).

The mapping is the Phase 1 boundary contract for FHIR R5 ingestion:
each Phase 0 canonical vital (`CANONICAL_VITALS`) projects to a single
LOINC code + UCUM unit. Tasks 10.2 (FHIR Subscriptions) and 10.3
(FHIRcast) consume this dict; the parity test
`python/tests/test_fhir_fixtures.py` enforces the
`set(LOINC_BY_VITAL) == set(CANONICAL_VITALS)` invariant.

Adding a canonical vital is a coordinated edit across:
  * `cds_harness.ingest.canonical.CANONICAL_VITALS`
  * `cds_kernel::canonical::CANONICAL_VITALS` (Rust)
  * this dict
  * `data/fhir/README.md` table
  * ADR-025 §4 table
"""

from __future__ import annotations

from typing import Final

from cds_harness.ingest.canonical import CANONICAL_VITALS

LOINC_SYSTEM: Final[str] = "http://loinc.org"
UCUM_SYSTEM: Final[str] = "http://unitsofmeasure.org"

LOINC_BY_VITAL: Final[dict[str, tuple[str, str]]] = {
    "diastolic_mmhg":       ("8462-4", "mm[Hg]"),
    "heart_rate_bpm":       ("8867-4", "/min"),
    "respiratory_rate_bpm": ("9279-1", "/min"),
    "spo2_percent":         ("2708-6", "%"),
    "systolic_mmhg":        ("8480-6", "mm[Hg]"),
    "temp_celsius":         ("8310-5", "Cel"),
}

VITAL_BY_LOINC: Final[dict[str, str]] = {
    code: vital for vital, (code, _unit) in LOINC_BY_VITAL.items()
}


def _assert_parity() -> None:
    missing = set(CANONICAL_VITALS) - set(LOINC_BY_VITAL)
    extra = set(LOINC_BY_VITAL) - set(CANONICAL_VITALS)
    if missing or extra:
        raise AssertionError(
            f"LOINC_BY_VITAL parity drift — missing: {sorted(missing)}, extra: {sorted(extra)}"
        )


_assert_parity()


__all__ = ["LOINC_BY_VITAL", "LOINC_SYSTEM", "UCUM_SYSTEM", "VITAL_BY_LOINC"]
