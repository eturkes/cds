"""Offline unit tests for the FHIR axis close-out helpers (Task 10.4 — ADR-027).

Live cluster + Workflow round-trip is exercised by the
``fhir-axis-smoke`` Justfile recipe (gated on ``.bin/dapr`` + slim
runtime + ``.bin/{z3,cvc5}`` + ``CDS_KIMINA_URL``); these tests cover
the pure data transforms so the pure-Python boundary contract is
deterministic across CI environments.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cds_harness.workflow.fhir_axis import (
    assert_muc_topology,
    build_patient_close_event,
    build_patient_open_event,
    build_subscription_notification,
    collect_atom_spans,
    iter_observation_entries,
    parse_muc_entry,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FHIR_FIXTURE = REPO_ROOT / "data" / "fhir" / "icu-monitor-02.observations.json"
RECORDED_FIXTURE = (
    REPO_ROOT / "data" / "guidelines" / "contradictory-bound.recorded.json"
)


def _load_fhir_fixture() -> dict:
    return json.loads(FHIR_FIXTURE.read_text(encoding="utf-8"))


def _load_recorded_root() -> dict:
    return json.loads(RECORDED_FIXTURE.read_text(encoding="utf-8"))["root"]


# ---------------------------------------------------------------------------
# build_subscription_notification


def test_subscription_notification_wraps_collection() -> None:
    fhir = _load_fhir_fixture()
    notification = build_subscription_notification(
        fhir,
        notification_id="ntfn-test",
        subscription_reference="Subscription/sub-test",
        topic_url="http://example.org/SubscriptionTopic/icu-vitals",
    )
    assert notification["resourceType"] == "Bundle"
    assert notification["id"] == "ntfn-test"
    assert notification["type"] == "subscription-notification"
    entries = notification["entry"]
    assert len(entries) == len(fhir["entry"]) + 1
    status = entries[0]["resource"]
    assert status["resourceType"] == "SubscriptionStatus"
    assert status["status"] == "active"
    assert status["type"] == "event-notification"
    assert status["subscription"] == {"reference": "Subscription/sub-test"}
    assert status["topic"] == "http://example.org/SubscriptionTopic/icu-vitals"
    # Original entries follow verbatim.
    assert entries[1:] == fhir["entry"]


def test_subscription_notification_rejects_non_collection() -> None:
    with pytest.raises(ValueError, match="expected 'collection'"):
        build_subscription_notification(
            {"resourceType": "Bundle", "type": "history", "entry": []},
            notification_id="x",
            subscription_reference="Subscription/x",
            topic_url="http://example.org/x",
        )


def test_subscription_notification_rejects_empty_collection() -> None:
    with pytest.raises(ValueError, match="no entries"):
        build_subscription_notification(
            {"resourceType": "Bundle", "type": "collection", "entry": []},
            notification_id="x",
            subscription_reference="Subscription/x",
            topic_url="http://example.org/x",
        )


def test_iter_observation_entries_skips_status() -> None:
    fhir = _load_fhir_fixture()
    notification = build_subscription_notification(
        fhir,
        notification_id="ntfn-iter",
        subscription_reference="Subscription/iter",
        topic_url="http://example.org/iter",
    )
    observation_entries = list(iter_observation_entries(notification))
    assert len(observation_entries) == len(fhir["entry"])
    for original, projected in zip(fhir["entry"], observation_entries, strict=True):
        assert original == projected


# ---------------------------------------------------------------------------
# build_patient_open_event / build_patient_close_event


def test_patient_open_event_has_canonical_envelope() -> None:
    event = build_patient_open_event(
        hub_topic="https://hub.example.org/topic/cds-test",
        event_id="evt-001",
        timestamp="2026-05-03T00:00:00.000000Z",
        patient_pseudo_id="pseudo-def456",
        identifier_system="urn:cds:test",
    )
    assert event["timestamp"] == "2026-05-03T00:00:00.000000Z"
    assert event["id"] == "evt-001"
    inner = event["event"]
    assert inner["hub.topic"] == "https://hub.example.org/topic/cds-test"
    assert inner["hub.event"] == "patient-open"
    context = inner["context"]
    assert len(context) == 1
    patient_entry = context[0]
    assert patient_entry["key"] == "patient"
    resource = patient_entry["resource"]
    assert resource["resourceType"] == "Patient"
    assert resource["id"] == "pseudo-def456"
    assert resource["identifier"][0] == {
        "system": "urn:cds:test",
        "value": "pseudo-def456",
    }


def test_patient_close_event_marks_close() -> None:
    event = build_patient_close_event(
        hub_topic="https://hub.example.org/topic/cds-test",
        event_id="evt-002",
        timestamp="2026-05-03T01:00:00.000000Z",
        patient_pseudo_id="pseudo-def456",
        identifier_system="urn:cds:test",
    )
    assert event["event"]["hub.event"] == "patient-close"


def test_patient_event_rejects_empty_pseudo_id() -> None:
    with pytest.raises(ValueError, match="patient_pseudo_id must be non-empty"):
        build_patient_open_event(
            hub_topic="x",
            event_id="x",
            timestamp="2026-05-03T00:00:00.000000Z",
            patient_pseudo_id="",
            identifier_system="x",
        )


# ---------------------------------------------------------------------------
# parse_muc_entry / collect_atom_spans / assert_muc_topology


def test_parse_muc_entry_canonical() -> None:
    assert parse_muc_entry("atom:contradictory-bound:0-4") == (
        "contradictory-bound",
        0,
        4,
    )
    assert parse_muc_entry("atom:doc-with-dashes:11-13") == (
        "doc-with-dashes",
        11,
        13,
    )


def test_parse_muc_entry_rejects_malformed() -> None:
    with pytest.raises(ValueError, match="canonical"):
        parse_muc_entry("relation:doc:0-4")
    with pytest.raises(ValueError, match="canonical"):
        parse_muc_entry("atom:doc:abc-4")
    with pytest.raises(ValueError, match="canonical"):
        parse_muc_entry("atom:doc:0_4")


def test_parse_muc_entry_rejects_inverted_span() -> None:
    with pytest.raises(ValueError, match=r"end .* < start"):
        parse_muc_entry("atom:doc:10-3")


def test_collect_atom_spans_skips_literals_by_default() -> None:
    root = _load_recorded_root()
    spans = collect_atom_spans(root)
    # Two spo2 atoms; literals are excluded by default.
    assert spans == {
        ("contradictory-bound", 0, 4),
        ("contradictory-bound", 15, 19),
    }


def test_collect_atom_spans_includes_literals_when_requested() -> None:
    root = _load_recorded_root()
    spans = collect_atom_spans(root, skip_literals=False)
    assert spans == {
        ("contradictory-bound", 0, 4),
        ("contradictory-bound", 11, 13),
        ("contradictory-bound", 15, 19),
        ("contradictory-bound", 26, 28),
    }


def _envelope_with_muc(muc: list[str]) -> dict:
    return {
        "ir": {"root": _load_recorded_root()},
        "trace": {"sat": False, "muc": muc},
    }


def test_assert_muc_topology_canonical() -> None:
    parsed = assert_muc_topology(
        _envelope_with_muc(
            [
                "atom:contradictory-bound:0-4",
                "atom:contradictory-bound:15-19",
            ]
        ),
        expected_doc_id="contradictory-bound",
    )
    assert parsed == [
        ("contradictory-bound", 0, 4),
        ("contradictory-bound", 15, 19),
    ]


def test_assert_muc_topology_rejects_unknown_span() -> None:
    with pytest.raises(AssertionError, match="no matching Atom span"):
        assert_muc_topology(
            _envelope_with_muc(["atom:contradictory-bound:99-101"]),
            expected_doc_id="contradictory-bound",
        )


def test_assert_muc_topology_rejects_doc_mismatch() -> None:
    with pytest.raises(AssertionError, match="doc_id"):
        assert_muc_topology(
            _envelope_with_muc(["atom:other-doc:0-4"]),
            expected_doc_id="contradictory-bound",
        )


def test_assert_muc_topology_rejects_empty_muc() -> None:
    with pytest.raises(AssertionError, match="non-empty list"):
        assert_muc_topology(
            _envelope_with_muc([]),
            expected_doc_id="contradictory-bound",
        )


def test_assert_muc_topology_rejects_missing_ir() -> None:
    envelope = {"trace": {"sat": False, "muc": ["atom:contradictory-bound:0-4"]}}
    with pytest.raises(AssertionError, match=r"envelope\.ir missing"):
        assert_muc_topology(envelope, expected_doc_id="contradictory-bound")


def test_assert_muc_topology_rejects_non_string_entry() -> None:
    with pytest.raises(AssertionError, match="not a string"):
        assert_muc_topology(
            _envelope_with_muc([42]),  # type: ignore[list-item]
            expected_doc_id="contradictory-bound",
        )
