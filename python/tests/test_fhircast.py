"""Tests for ``cds_harness.ingest.fhircast`` (Task 10.3, ADR-026).

Covers:

* Raw FHIRcast STU3 notification projection (patient-open + patient-close).
* CloudEvents 1.0-wrapped variant (Dapr pub/sub delivery shape).
* Envelope-violation paths (missing id / timestamp / event,
  hub.event mismatch, unsupported hub.event).
* Patient-context-projection violations (multi-patient, missing
  patient entry, wrong resourceType, missing/empty Patient.id).
* :class:`FHIRcastSessionRegistry` semantics (open replaces, close
  is idempotent, multi-topic isolation, snapshot stability,
  thread-safety smoke).
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from typing import Any

import pytest

from cds_harness.ingest import (
    EVENT_PATIENT_CLOSE,
    EVENT_PATIENT_OPEN,
    TOPIC_PATIENT_CLOSE,
    TOPIC_PATIENT_OPEN,
    FHIRcastError,
    FHIRcastEvent,
    FHIRcastSessionRegistry,
    parse_event,
)

_SESSION_TOPIC = "https://hub.example.org/topic/abcd-1234"
_PATIENT_ID = "pseudo-7f3"


def _patient_open_raw() -> dict[str, Any]:
    return {
        "timestamp": "2026-05-02T08:00:00.000000Z",
        "id": "evt-open-001",
        "event": {
            "hub.topic": _SESSION_TOPIC,
            "hub.event": "patient-open",
            "context": [
                {
                    "key": "patient",
                    "resource": {
                        "resourceType": "Patient",
                        "id": _PATIENT_ID,
                        "identifier": [
                            {
                                "system": "urn:cds:test",
                                "value": _PATIENT_ID,
                            },
                        ],
                    },
                },
            ],
        },
    }


def _patient_close_raw() -> dict[str, Any]:
    return {
        "timestamp": "2026-05-02T09:30:00.000000Z",
        "id": "evt-close-001",
        "event": {
            "hub.topic": _SESSION_TOPIC,
            "hub.event": "patient-close",
            "context": [
                {
                    "key": "patient",
                    "resource": {
                        "resourceType": "Patient",
                        "id": _PATIENT_ID,
                    },
                },
            ],
        },
    }


def _wrap_cloudevent(notification: Mapping[str, Any]) -> dict[str, Any]:
    """Wrap ``notification`` as Dapr would when delivering via pub/sub."""
    return {
        "specversion": "1.0",
        "type": "com.dapr.event.sent",
        "source": "fhircast-hub",
        "id": "ce-evt-1",
        "datacontenttype": "application/json",
        "data": dict(notification),
    }


# ---------------------------------------------------------------------------
# Topic constants


def test_topic_constants_match_adr_026() -> None:
    assert TOPIC_PATIENT_OPEN == "fhircast.patient-open"
    assert TOPIC_PATIENT_CLOSE == "fhircast.patient-close"
    assert EVENT_PATIENT_OPEN == "patient-open"
    assert EVENT_PATIENT_CLOSE == "patient-close"


# ---------------------------------------------------------------------------
# Raw notification projection


def test_parse_raw_patient_open_projects_to_event() -> None:
    event = parse_event(
        _patient_open_raw(), expected_event=EVENT_PATIENT_OPEN
    )
    assert isinstance(event, FHIRcastEvent)
    assert event.event_id == "evt-open-001"
    assert event.timestamp == "2026-05-02T08:00:00.000000Z"
    assert event.hub_topic == _SESSION_TOPIC
    assert event.hub_event == "patient-open"
    assert event.patient_pseudo_id == _PATIENT_ID


def test_parse_raw_patient_close_projects_to_event() -> None:
    event = parse_event(
        _patient_close_raw(), expected_event=EVENT_PATIENT_CLOSE
    )
    assert event.hub_event == "patient-close"
    assert event.patient_pseudo_id == _PATIENT_ID
    assert event.timestamp.endswith("Z")


def test_parse_canonicalizes_timestamp_with_offsetless_seconds() -> None:
    raw = _patient_open_raw()
    raw["timestamp"] = "2026-05-02T08:00:00Z"  # no fractional component
    event = parse_event(raw, expected_event=EVENT_PATIENT_OPEN)
    assert event.timestamp == "2026-05-02T08:00:00.000000Z"


# ---------------------------------------------------------------------------
# CloudEvents-wrapped variant


def test_parse_cloudevents_wrapped_unwraps_data() -> None:
    wrapped = _wrap_cloudevent(_patient_open_raw())
    event = parse_event(wrapped, expected_event=EVENT_PATIENT_OPEN)
    assert event.hub_event == "patient-open"
    assert event.patient_pseudo_id == _PATIENT_ID


def test_parse_cloudevents_with_non_dict_data_raises() -> None:
    wrapped = {
        "specversion": "1.0",
        "type": "x",
        "source": "y",
        "id": "z",
        "data": "not-a-json-object",
    }
    with pytest.raises(FHIRcastError, match="not a JSON"):
        parse_event(wrapped, expected_event=EVENT_PATIENT_OPEN)


# ---------------------------------------------------------------------------
# Envelope violations


def test_parse_rejects_non_mapping_input() -> None:
    with pytest.raises(FHIRcastError, match="dict-like"):
        parse_event(["not", "a", "dict"], expected_event=EVENT_PATIENT_OPEN)  # type: ignore[arg-type]


def test_parse_rejects_missing_id() -> None:
    raw = _patient_open_raw()
    del raw["id"]
    with pytest.raises(FHIRcastError, match="missing/invalid 'id'"):
        parse_event(raw, expected_event=EVENT_PATIENT_OPEN)


def test_parse_rejects_missing_timestamp() -> None:
    raw = _patient_open_raw()
    del raw["timestamp"]
    with pytest.raises(FHIRcastError, match="missing/invalid 'timestamp'"):
        parse_event(raw, expected_event=EVENT_PATIENT_OPEN)


def test_parse_rejects_missing_event() -> None:
    raw = _patient_open_raw()
    del raw["event"]
    with pytest.raises(FHIRcastError, match="missing/invalid 'event'"):
        parse_event(raw, expected_event=EVENT_PATIENT_OPEN)


def test_parse_rejects_missing_hub_topic() -> None:
    raw = _patient_open_raw()
    del raw["event"]["hub.topic"]
    with pytest.raises(FHIRcastError, match=r"hub\.topic"):
        parse_event(raw, expected_event=EVENT_PATIENT_OPEN)


def test_parse_rejects_unsupported_hub_event() -> None:
    raw = _patient_open_raw()
    raw["event"]["hub.event"] = "imagingstudy-open"
    with pytest.raises(FHIRcastError, match="unsupported"):
        parse_event(raw, expected_event=EVENT_PATIENT_OPEN)


def test_parse_rejects_route_event_mismatch() -> None:
    raw = _patient_open_raw()
    with pytest.raises(FHIRcastError, match="does not match route contract"):
        parse_event(raw, expected_event=EVENT_PATIENT_CLOSE)


def test_parse_rejects_invalid_timestamp() -> None:
    raw = _patient_open_raw()
    raw["timestamp"] = "2026-05-02 08:00:00"  # missing 'T' / 'Z'
    with pytest.raises(FHIRcastError, match="not canonicalizable"):
        parse_event(raw, expected_event=EVENT_PATIENT_OPEN)


# ---------------------------------------------------------------------------
# Patient-context-projection violations


def test_parse_rejects_empty_context() -> None:
    raw = _patient_open_raw()
    raw["event"]["context"] = []
    with pytest.raises(FHIRcastError, match="non-empty list"):
        parse_event(raw, expected_event=EVENT_PATIENT_OPEN)


def test_parse_rejects_missing_patient_entry() -> None:
    raw = _patient_open_raw()
    raw["event"]["context"] = [
        {
            "key": "encounter",
            "resource": {"resourceType": "Encounter", "id": "enc-1"},
        },
    ]
    with pytest.raises(FHIRcastError, match="missing required patient"):
        parse_event(raw, expected_event=EVENT_PATIENT_OPEN)


def test_parse_rejects_multi_patient_context() -> None:
    raw = _patient_open_raw()
    raw["event"]["context"].append(
        {
            "key": "patient",
            "resource": {"resourceType": "Patient", "id": "pseudo-other"},
        }
    )
    with pytest.raises(FHIRcastError, match="multiple patient context"):
        parse_event(raw, expected_event=EVENT_PATIENT_OPEN)


def test_parse_rejects_wrong_resource_type() -> None:
    raw = _patient_open_raw()
    raw["event"]["context"][0]["resource"]["resourceType"] = "Encounter"
    with pytest.raises(FHIRcastError, match="resourceType"):
        parse_event(raw, expected_event=EVENT_PATIENT_OPEN)


def test_parse_rejects_missing_patient_id() -> None:
    raw = _patient_open_raw()
    del raw["event"]["context"][0]["resource"]["id"]
    with pytest.raises(FHIRcastError, match="Patient resource missing"):
        parse_event(raw, expected_event=EVENT_PATIENT_OPEN)


def test_parse_rejects_empty_patient_id() -> None:
    raw = _patient_open_raw()
    raw["event"]["context"][0]["resource"]["id"] = ""
    with pytest.raises(FHIRcastError, match="Patient resource missing"):
        parse_event(raw, expected_event=EVENT_PATIENT_OPEN)


def test_parse_rejects_non_dict_context_entry() -> None:
    raw = _patient_open_raw()
    raw["event"]["context"] = ["not-a-dict"]
    with pytest.raises(FHIRcastError, match="must be a JSON object"):
        parse_event(raw, expected_event=EVENT_PATIENT_OPEN)


# ---------------------------------------------------------------------------
# Session registry semantics


def test_registry_open_then_close_is_complete_cycle() -> None:
    registry = FHIRcastSessionRegistry()
    open_event = parse_event(
        _patient_open_raw(), expected_event=EVENT_PATIENT_OPEN
    )
    close_event = parse_event(
        _patient_close_raw(), expected_event=EVENT_PATIENT_CLOSE
    )

    assert registry.current_patient(_SESSION_TOPIC) is None
    registry.apply_open(open_event)
    assert registry.current_patient(_SESSION_TOPIC) == _PATIENT_ID
    assert registry.active_topics() == {_SESSION_TOPIC: _PATIENT_ID}

    registry.apply_close(close_event)
    assert registry.current_patient(_SESSION_TOPIC) is None
    assert registry.active_topics() == {}


def test_registry_open_replaces_existing_patient_on_same_topic() -> None:
    registry = FHIRcastSessionRegistry()
    first = parse_event(_patient_open_raw(), expected_event=EVENT_PATIENT_OPEN)
    second_raw = _patient_open_raw()
    second_raw["event"]["context"][0]["resource"]["id"] = "pseudo-replacement"
    second_raw["id"] = "evt-open-002"
    second = parse_event(second_raw, expected_event=EVENT_PATIENT_OPEN)

    registry.apply_open(first)
    registry.apply_open(second)
    assert registry.current_patient(_SESSION_TOPIC) == "pseudo-replacement"


def test_registry_close_without_open_is_idempotent_noop() -> None:
    registry = FHIRcastSessionRegistry()
    close_event = parse_event(
        _patient_close_raw(), expected_event=EVENT_PATIENT_CLOSE
    )
    registry.apply_close(close_event)  # no error raised
    assert registry.current_patient(_SESSION_TOPIC) is None
    assert registry.active_topics() == {}


def test_registry_close_after_close_stays_clean() -> None:
    registry = FHIRcastSessionRegistry()
    open_event = parse_event(
        _patient_open_raw(), expected_event=EVENT_PATIENT_OPEN
    )
    close_event = parse_event(
        _patient_close_raw(), expected_event=EVENT_PATIENT_CLOSE
    )
    registry.apply_open(open_event)
    registry.apply_close(close_event)
    registry.apply_close(close_event)  # second close, still a no-op
    assert registry.current_patient(_SESSION_TOPIC) is None


def test_registry_isolates_distinct_topics() -> None:
    registry = FHIRcastSessionRegistry()
    a_raw = _patient_open_raw()
    a_raw["event"]["hub.topic"] = "topic-a"
    b_raw = _patient_open_raw()
    b_raw["event"]["hub.topic"] = "topic-b"
    b_raw["event"]["context"][0]["resource"]["id"] = "pseudo-b"
    b_raw["id"] = "evt-open-b"

    a = parse_event(a_raw, expected_event=EVENT_PATIENT_OPEN)
    b = parse_event(b_raw, expected_event=EVENT_PATIENT_OPEN)
    registry.apply_open(a)
    registry.apply_open(b)
    assert registry.active_topics() == {
        "topic-a": _PATIENT_ID,
        "topic-b": "pseudo-b",
    }


def test_registry_active_topics_returns_a_copy() -> None:
    registry = FHIRcastSessionRegistry()
    registry.apply_open(
        parse_event(_patient_open_raw(), expected_event=EVENT_PATIENT_OPEN)
    )
    snapshot = registry.active_topics()
    snapshot["mutated"] = "should-not-leak"
    assert "mutated" not in registry.active_topics()


def test_registry_apply_open_rejects_close_event() -> None:
    registry = FHIRcastSessionRegistry()
    close_event = parse_event(
        _patient_close_raw(), expected_event=EVENT_PATIENT_CLOSE
    )
    with pytest.raises(FHIRcastError, match="apply_open"):
        registry.apply_open(close_event)


def test_registry_apply_close_rejects_open_event() -> None:
    registry = FHIRcastSessionRegistry()
    open_event = parse_event(
        _patient_open_raw(), expected_event=EVENT_PATIENT_OPEN
    )
    with pytest.raises(FHIRcastError, match="apply_close"):
        registry.apply_close(open_event)


def test_registry_clear_wipes_state() -> None:
    registry = FHIRcastSessionRegistry()
    registry.apply_open(
        parse_event(_patient_open_raw(), expected_event=EVENT_PATIENT_OPEN)
    )
    registry.clear()
    assert registry.current_patient(_SESSION_TOPIC) is None
    assert registry.active_topics() == {}


def test_registry_concurrent_opens_are_thread_safe() -> None:
    """A coarse concurrency smoke — N threads each open a distinct topic."""
    registry = FHIRcastSessionRegistry()
    n = 32

    def _open(i: int) -> None:
        raw = _patient_open_raw()
        raw["event"]["hub.topic"] = f"topic-{i}"
        raw["event"]["context"][0]["resource"]["id"] = f"pseudo-{i}"
        raw["id"] = f"evt-{i}"
        registry.apply_open(parse_event(raw, expected_event=EVENT_PATIENT_OPEN))

    threads = [threading.Thread(target=_open, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10.0)
        assert not t.is_alive()

    snapshot = registry.active_topics()
    assert len(snapshot) == n
    assert snapshot[f"topic-{0}"] == "pseudo-0"
    assert snapshot[f"topic-{n - 1}"] == f"pseudo-{n - 1}"
