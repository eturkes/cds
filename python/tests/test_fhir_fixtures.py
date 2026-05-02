"""Phase 1, Task 10.1 parity gate — FHIR R5 Observation fixtures.

Validates `data/fhir/*.observations.json` round-trip cleanly through
`fhir.resources.bundle.Bundle` and that every Observation honours the
locked LOINC + UCUM mapping in `cds_harness.ingest.loinc.LOINC_BY_VITAL`
(ADR-025 §4).

The Phase 0 sample CSV/JSON ingestion path under `data/sample/` is
*not* exercised here — it has its own gate in `test_ingest.py`. This
test only enforces the FHIR fixture contract.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fhir.resources.bundle import Bundle
from fhir.resources.observation import Observation

from cds_harness.ingest.canonical import CANONICAL_VITALS
from cds_harness.ingest.loinc import (
    LOINC_BY_VITAL,
    LOINC_SYSTEM,
    UCUM_SYSTEM,
    VITAL_BY_LOINC,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FHIR_DIR = REPO_ROOT / "data" / "fhir"

RFC3339_Z = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$"
)

FIXTURES = [
    "icu-monitor-01.observations.json",
    "icu-monitor-02.observations.json",
]


def _load_bundle(name: str) -> Bundle:
    raw = json.loads((FHIR_DIR / name).read_text(encoding="utf-8"))
    return Bundle.model_validate(raw)


def test_loinc_table_matches_canonical_vitals() -> None:
    assert set(LOINC_BY_VITAL) == set(CANONICAL_VITALS), (
        "LOINC_BY_VITAL parity drift versus CANONICAL_VITALS — coordinated edit required"
    )
    assert set(VITAL_BY_LOINC.values()) == set(CANONICAL_VITALS)


def test_loinc_codes_are_unique() -> None:
    codes = [code for code, _unit in LOINC_BY_VITAL.values()]
    assert len(codes) == len(set(codes)), "duplicate LOINC code in LOINC_BY_VITAL"


@pytest.mark.parametrize("fixture", FIXTURES)
def test_bundle_is_collection(fixture: str) -> None:
    bundle = _load_bundle(fixture)
    assert bundle.get_resource_type() == "Bundle"
    assert bundle.type == "collection"
    assert bundle.entry, f"empty bundle {fixture} — Phase 1 invariant: at least one Observation"


@pytest.mark.parametrize("fixture", FIXTURES)
def test_every_entry_is_observation(fixture: str) -> None:
    bundle = _load_bundle(fixture)
    for entry in bundle.entry:
        resource = entry.resource
        assert isinstance(resource, Observation), (
            f"{fixture}: entry {entry.fullUrl!r} is {type(resource).__name__}, expected Observation"
        )


@pytest.mark.parametrize("fixture", FIXTURES)
def test_observation_loinc_and_ucum_locked(fixture: str) -> None:
    bundle = _load_bundle(fixture)
    for entry in bundle.entry:
        obs: Observation = entry.resource  # type: ignore[assignment]
        codings = obs.code.coding or []
        assert codings, f"{fixture}: Observation {obs.id} has no Coding"
        coding = codings[0]
        assert coding.system == LOINC_SYSTEM, (
            f"{fixture}: Observation {obs.id} system={coding.system}, expected {LOINC_SYSTEM}"
        )
        loinc = coding.code
        assert loinc in VITAL_BY_LOINC, (
            f"{fixture}: Observation {obs.id} LOINC {loinc} not in locked LOINC_BY_VITAL table"
        )
        vital = VITAL_BY_LOINC[loinc]
        _expected_loinc, expected_unit = LOINC_BY_VITAL[vital]
        quantity = obs.valueQuantity
        assert quantity is not None, f"{fixture}: Observation {obs.id} missing valueQuantity"
        assert quantity.system == UCUM_SYSTEM, (
            f"{fixture}: Observation {obs.id} UCUM system={quantity.system}, expected {UCUM_SYSTEM}"
        )
        assert quantity.code == expected_unit, (
            f"{fixture}: Observation {obs.id} unit={quantity.code}, "
            f"expected {expected_unit} for {vital}"
        )
        assert quantity.value is not None
        value = float(quantity.value)
        assert value == value, f"{fixture}: Observation {obs.id} NaN value"
        assert value not in (float("inf"), float("-inf")), (
            f"{fixture}: Observation {obs.id} infinite value {quantity.value}"
        )


@pytest.mark.parametrize("fixture", FIXTURES)
def test_observation_effective_datetime_is_rfc3339_z(fixture: str) -> None:
    bundle = _load_bundle(fixture)
    raw = json.loads((FHIR_DIR / fixture).read_text(encoding="utf-8"))
    raw_entries = raw["entry"]
    assert len(raw_entries) == len(bundle.entry)
    for raw_entry, parsed_entry in zip(raw_entries, bundle.entry, strict=True):
        raw_dt = raw_entry["resource"]["effectiveDateTime"]
        assert RFC3339_Z.match(raw_dt), (
            f"{fixture}: effectiveDateTime {raw_dt!r} is not RFC 3339 with Z suffix"
        )
        obs: Observation = parsed_entry.resource  # type: ignore[assignment]
        assert obs.effectiveDateTime is not None


@pytest.mark.parametrize("fixture", FIXTURES)
def test_bundle_has_single_subject(fixture: str) -> None:
    bundle = _load_bundle(fixture)
    refs = {entry.resource.subject.reference for entry in bundle.entry}  # type: ignore[union-attr]
    assert len(refs) == 1, (
        f"{fixture}: multi-patient bundle ({sorted(refs)}) — "
        f"Phase 1 invariant: one payload per patient"
    )


@pytest.mark.parametrize("fixture", FIXTURES)
def test_observation_status_is_final(fixture: str) -> None:
    bundle = _load_bundle(fixture)
    for entry in bundle.entry:
        obs: Observation = entry.resource  # type: ignore[assignment]
        assert obs.status == "final", (
            f"{fixture}: Observation {obs.id} status={obs.status}, expected 'final'"
        )


@pytest.mark.parametrize("fixture", FIXTURES)
def test_observation_category_is_vital_signs(fixture: str) -> None:
    bundle = _load_bundle(fixture)
    for entry in bundle.entry:
        obs: Observation = entry.resource  # type: ignore[assignment]
        categories = obs.category or []
        assert categories, f"{fixture}: Observation {obs.id} has no category"
        codings = categories[0].coding or []
        assert codings, f"{fixture}: Observation {obs.id} category has no coding"
        assert codings[0].code == "vital-signs", (
            f"{fixture}: Observation {obs.id} category={codings[0].code}, expected 'vital-signs'"
        )
