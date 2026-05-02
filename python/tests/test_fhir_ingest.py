"""Phase 1, Task 10.2 — FHIR R5 Bundle → :class:`ClinicalTelemetryPayload` projection.

Exercises :func:`cds_harness.ingest.bundle_to_payload` against:

* the canonical 10.1 ``data/fhir/*.observations.json`` fixtures
  (Bundle.type = ``"collection"``);
* a synthetic FHIR R5 Subscriptions Backport notification Bundle
  (Bundle.type = ``"subscription-notification"`` — entry[0] is a
  ``SubscriptionStatus``, subsequent entries are Observations);
* a battery of negative cases covering every rejection path on the
  ADR-025 §4 projection contract.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from cds_harness.ingest import (
    FHIRBundleError,
    InvalidTimestampError,
    bundle_to_payload,
)
from cds_harness.schema import (
    SCHEMA_VERSION,
    ClinicalTelemetryPayload,
    TelemetrySource,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FHIR_DIR = REPO_ROOT / "data" / "fhir"
FIXTURE_01 = FHIR_DIR / "icu-monitor-01.observations.json"
FIXTURE_02 = FHIR_DIR / "icu-monitor-02.observations.json"


def _load(fixture: Path) -> dict[str, Any]:
    return json.loads(fixture.read_text(encoding="utf-8"))


def _wrap_as_subscription_notification(
    collection_bundle: Mapping[str, Any],
    *,
    bundle_id: str = "ntfn-test",
    subscription_ref: str = "Subscription/sub-icu-01",
    topic: str = "http://example.org/SubscriptionTopic/icu-vitals",
) -> dict[str, Any]:
    """Wrap a collection Bundle's entries into a notification Bundle.

    The result has ``type = "subscription-notification"`` and prepends a
    ``SubscriptionStatus`` resource at ``entry[0]``, mirroring the FHIR
    R5 Subscriptions Backport notification shape.
    """
    status_entry = {
        "fullUrl": "urn:uuid:status",
        "resource": {
            "resourceType": "SubscriptionStatus",
            "status": "active",
            "type": "event-notification",
            "subscription": {"reference": subscription_ref},
            "topic": topic,
        },
    }
    return {
        "resourceType": "Bundle",
        "id": bundle_id,
        "type": "subscription-notification",
        "entry": [status_entry, *copy.deepcopy(list(collection_bundle["entry"]))],
    }


# ---------------------------------------------------------------------------
# Happy path — collection Bundles


def test_collection_bundle_icu02_round_trips() -> None:
    payload = bundle_to_payload(_load(FIXTURE_02))
    assert isinstance(payload, ClinicalTelemetryPayload)
    assert payload.schema_version == SCHEMA_VERSION
    assert payload.source.device_id == "fhir:icu-monitor-02"
    assert payload.source.patient_pseudo_id == "pseudo-def456"
    assert len(payload.samples) == 2
    s0, s1 = payload.samples
    assert s0.wall_clock_utc == "2026-04-29T13:00:00.000000Z"
    assert s0.monotonic_ns < s1.monotonic_ns
    assert s0.vitals == {"heart_rate_bpm": 88.0, "spo2_percent": 94.0}
    assert s1.vitals == {"heart_rate_bpm": 90.0, "spo2_percent": 93.5}
    # Wire-stable: vitals serialize lexicographically (matches Rust BTreeMap).
    for sample in payload.samples:
        assert list(sample.vitals.keys()) == sorted(sample.vitals.keys())
        assert sample.events == []


def test_collection_bundle_icu01_buckets_six_vitals_per_timestamp() -> None:
    payload = bundle_to_payload(_load(FIXTURE_01))
    assert payload.source.device_id == "fhir:icu-monitor-01"
    assert payload.source.patient_pseudo_id == "pseudo-abc123"
    assert len(payload.samples) == 2
    for sample in payload.samples:
        assert set(sample.vitals.keys()) == {
            "diastolic_mmhg",
            "heart_rate_bpm",
            "respiratory_rate_bpm",
            "spo2_percent",
            "systolic_mmhg",
            "temp_celsius",
        }


def test_payload_round_trips_through_pydantic() -> None:
    """The projected payload must round-trip via :func:`model_dump_json`."""
    payload = bundle_to_payload(_load(FIXTURE_02))
    serialized = payload.model_dump_json()
    restored = ClinicalTelemetryPayload.model_validate_json(serialized)
    assert restored == payload


def test_source_override_replaces_default_device_id() -> None:
    override = TelemetrySource(
        device_id="custom-rig", patient_pseudo_id="pseudo-def456"
    )
    payload = bundle_to_payload(_load(FIXTURE_02), source_override=override)
    assert payload.source.device_id == "custom-rig"


def test_source_override_with_disagreeing_patient_rejected() -> None:
    override = TelemetrySource(
        device_id="custom-rig", patient_pseudo_id="pseudo-WRONG"
    )
    with pytest.raises(FHIRBundleError, match="disagrees with Bundle subject"):
        bundle_to_payload(_load(FIXTURE_02), source_override=override)


# ---------------------------------------------------------------------------
# Happy path — subscription-notification Bundles


def test_subscription_notification_skips_status_and_projects_observations() -> None:
    collection = _load(FIXTURE_02)
    notification = _wrap_as_subscription_notification(collection)
    payload = bundle_to_payload(notification)
    # Same shape as the collection round-trip — entry[0] (SubscriptionStatus) skipped.
    assert payload.source.patient_pseudo_id == "pseudo-def456"
    assert len(payload.samples) == 2
    assert payload.samples[0].vitals == {
        "heart_rate_bpm": 88.0,
        "spo2_percent": 94.0,
    }
    # device_id derives from the notification Bundle.id, not the wrapped collection.
    assert payload.source.device_id == "fhir:ntfn-test"


def test_subscription_notification_rejects_empty_entry_list() -> None:
    bundle = {
        "resourceType": "Bundle",
        "id": "empty-ntfn",
        "type": "subscription-notification",
        "entry": [],
    }
    with pytest.raises(FHIRBundleError, match="SubscriptionStatus at entry\\[0\\]"):
        bundle_to_payload(bundle)


def test_subscription_notification_rejects_status_only_bundle() -> None:
    """Notification with only a SubscriptionStatus and no Observations is empty."""
    bundle = _wrap_as_subscription_notification({"entry": []})
    with pytest.raises(FHIRBundleError, match="no Observation entries"):
        bundle_to_payload(bundle)


# ---------------------------------------------------------------------------
# Negative paths — Bundle structure


def test_non_dict_input_rejected() -> None:
    with pytest.raises(FHIRBundleError, match="dict-like Bundle JSON"):
        bundle_to_payload("not-a-mapping")  # type: ignore[arg-type]


def test_unsupported_bundle_type_rejected() -> None:
    bundle = _load(FIXTURE_02)
    bundle["type"] = "transaction"
    with pytest.raises(FHIRBundleError, match=r"unsupported Bundle\.type"):
        bundle_to_payload(bundle)


def test_collection_bundle_with_no_entries_rejected() -> None:
    bundle = {
        "resourceType": "Bundle",
        "id": "empty-coll",
        "type": "collection",
        "entry": [],
    }
    with pytest.raises(FHIRBundleError, match="no Observation entries"):
        bundle_to_payload(bundle)


def test_non_observation_entry_rejected() -> None:
    bundle = _load(FIXTURE_02)
    bundle["entry"][0]["resource"] = {
        "resourceType": "Patient",
        "id": "patient-X",
    }
    with pytest.raises(FHIRBundleError, match="non-Observation entry"):
        bundle_to_payload(bundle)


def test_multi_patient_bundle_rejected() -> None:
    bundle = _load(FIXTURE_02)
    bundle["entry"][0]["resource"]["subject"]["reference"] = "Patient/pseudo-OTHER"
    with pytest.raises(FHIRBundleError, match="multi-patient Bundle"):
        bundle_to_payload(bundle)


def test_non_patient_subject_reference_rejected() -> None:
    bundle = _load(FIXTURE_02)
    for entry in bundle["entry"]:
        entry["resource"]["subject"]["reference"] = "Group/cohort-1"
    with pytest.raises(FHIRBundleError, match="not 'Patient/<id>' form"):
        bundle_to_payload(bundle)


# ---------------------------------------------------------------------------
# Negative paths — Observation projection


def test_off_loinc_system_rejected() -> None:
    bundle = _load(FIXTURE_02)
    bundle["entry"][0]["resource"]["code"]["coding"][0]["system"] = "http://snomed.info/sct"
    with pytest.raises(FHIRBundleError, match=r"coding\.system="):
        bundle_to_payload(bundle)


def test_off_table_loinc_rejected() -> None:
    bundle = _load(FIXTURE_02)
    bundle["entry"][0]["resource"]["code"]["coding"][0]["code"] = "99999-9"
    with pytest.raises(FHIRBundleError, match="LOINC '99999-9' not in locked"):
        bundle_to_payload(bundle)


def test_off_ucum_unit_rejected() -> None:
    bundle = _load(FIXTURE_02)
    bundle["entry"][0]["resource"]["valueQuantity"]["code"] = "wrong-unit"
    with pytest.raises(FHIRBundleError, match="unit='wrong-unit'"):
        bundle_to_payload(bundle)


def test_off_ucum_system_rejected() -> None:
    bundle = _load(FIXTURE_02)
    bundle["entry"][0]["resource"]["valueQuantity"]["system"] = "http://example.org/units"
    with pytest.raises(FHIRBundleError, match="UCUM system="):
        bundle_to_payload(bundle)


def test_invalid_effective_datetime_rejected() -> None:
    bundle = _load(FIXTURE_02)
    bundle["entry"][0]["resource"]["effectiveDateTime"] = "2026-04-29T13:00:00+02:00"
    with pytest.raises(InvalidTimestampError):
        bundle_to_payload(bundle)


def test_duplicate_vital_at_same_timestamp_rejected() -> None:
    bundle = _load(FIXTURE_02)
    # entry[0] = HR @ t0; entry[1] = SpO2 @ t0 → duplicate the SpO2 entry's
    # LOINC into HR so that two HR Observations land at the same timestamp.
    bundle["entry"][1]["resource"]["code"]["coding"][0] = {
        "system": "http://loinc.org",
        "code": "8867-4",
        "display": "Heart rate",
    }
    bundle["entry"][1]["resource"]["valueQuantity"] = {
        "value": 99.0,
        "unit": "/min",
        "system": "http://unitsofmeasure.org",
        "code": "/min",
    }
    with pytest.raises(FHIRBundleError, match="duplicate vital"):
        bundle_to_payload(bundle)
