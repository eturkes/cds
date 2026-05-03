"""FHIR axis close-out helpers (Task 10.4 — ADR-027).

Composes the three Phase 1 FHIR sub-task contracts into a single end-to-
end smoke gate:

* **10.1** canonical R5 ``Observation`` ``Bundle`` collection fixture
  (``data/fhir/icu-monitor-02.observations.json``).
* **10.2** harness ``/v1/fhir/notification`` projection (subscription-
  notification → :class:`ClinicalTelemetryPayload`).
* **10.3** harness ``/v1/fhircast/patient-{open,close}`` projection +
  in-process :class:`FHIRcastSessionRegistry` transitions.

The close-out runner (``cds_harness.workflow run-fhir-pipeline``) drives
the projected envelope through the existing Phase 0 Workflow
(ingest → translate → deduce → solve → recheck) and verifies that the
contradictory-bound MUC entries topologically map back to the recorded
:class:`Atom` spans (constraint **C4**).

The helpers exposed here are pure data transforms — they do not touch
the network. The orchestrator (``cds_harness.workflow.__main__``) owns
all daprd HTTP / WorkflowRuntime side-effects.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any, Final, Literal

_FHIRCAST_HUB_TOPIC_KEY: Final[str] = "hub.topic"
_FHIRCAST_HUB_EVENT_KEY: Final[str] = "hub.event"
_PATIENT_RESOURCE_TYPE: Final[str] = "Patient"
_LITERAL_PREDICATE: Final[str] = "literal"

_MUC_ENTRY_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^atom:(?P<doc>[^:]+):(?P<start>\d+)-(?P<end>\d+)$"
)


def build_subscription_notification(
    collection_bundle: Mapping[str, Any],
    *,
    notification_id: str,
    subscription_reference: str,
    topic_url: str,
) -> dict[str, Any]:
    """Wrap a FHIR R5 ``collection`` Bundle as a ``subscription-notification``.

    The R5 Subscriptions Backport IG (v1.2.0) requires the
    ``SubscriptionStatus`` resource at ``entry[0]``; the triggered
    resources follow as the remaining entries. The harness's
    ``/v1/fhir/notification`` projection (ADR-025 §4) skips ``entry[0]``
    and projects entries[1:] as Observations.

    Raises:
        ValueError: if ``collection_bundle.type`` is not ``"collection"``
            or no entries are present (a ``subscription-notification``
            with an empty body would never be emitted by a real Hub).
    """
    bundle_type = collection_bundle.get("type")
    if bundle_type != "collection":
        raise ValueError(
            f"build_subscription_notification: source Bundle.type={bundle_type!r}, "
            "expected 'collection'"
        )
    entries = list(collection_bundle.get("entry") or [])
    if not entries:
        raise ValueError("build_subscription_notification: collection has no entries")

    status_resource = {
        "resourceType": "SubscriptionStatus",
        "status": "active",
        "type": "event-notification",
        "subscription": {"reference": subscription_reference},
        "topic": topic_url,
    }
    return {
        "resourceType": "Bundle",
        "id": notification_id,
        "type": "subscription-notification",
        "entry": [
            {
                "fullUrl": f"urn:uuid:{notification_id}-status",
                "resource": status_resource,
            },
            *entries,
        ],
    }


def build_patient_open_event(
    *,
    hub_topic: str,
    event_id: str,
    timestamp: str,
    patient_pseudo_id: str,
    identifier_system: str,
) -> dict[str, Any]:
    """Construct a FHIRcast STU3 ``patient-open`` notification.

    Mirrors the canonical envelope used by ADR-026 §4 +
    :mod:`cds_harness.ingest.fhircast`.
    """
    return _build_event(
        hub_topic=hub_topic,
        hub_event="patient-open",
        event_id=event_id,
        timestamp=timestamp,
        patient_pseudo_id=patient_pseudo_id,
        identifier_system=identifier_system,
    )


def build_patient_close_event(
    *,
    hub_topic: str,
    event_id: str,
    timestamp: str,
    patient_pseudo_id: str,
    identifier_system: str,
) -> dict[str, Any]:
    """Construct a FHIRcast STU3 ``patient-close`` notification."""
    return _build_event(
        hub_topic=hub_topic,
        hub_event="patient-close",
        event_id=event_id,
        timestamp=timestamp,
        patient_pseudo_id=patient_pseudo_id,
        identifier_system=identifier_system,
    )


def _build_event(
    *,
    hub_topic: str,
    hub_event: Literal["patient-open", "patient-close"],
    event_id: str,
    timestamp: str,
    patient_pseudo_id: str,
    identifier_system: str,
) -> dict[str, Any]:
    if not patient_pseudo_id:
        raise ValueError("_build_event: patient_pseudo_id must be non-empty")
    return {
        "timestamp": timestamp,
        "id": event_id,
        "event": {
            _FHIRCAST_HUB_TOPIC_KEY: hub_topic,
            _FHIRCAST_HUB_EVENT_KEY: hub_event,
            "context": [
                {
                    "key": "patient",
                    "resource": {
                        "resourceType": _PATIENT_RESOURCE_TYPE,
                        "id": patient_pseudo_id,
                        "identifier": [
                            {
                                "system": identifier_system,
                                "value": patient_pseudo_id,
                            },
                        ],
                    },
                },
            ],
        },
    }


def parse_muc_entry(entry: str) -> tuple[str, int, int]:
    """Parse an ``atom:<doc_id>:<start>-<end>`` MUC entry.

    Raises:
        ValueError: on any deviation from the canonical shape.
    """
    match = _MUC_ENTRY_PATTERN.match(entry)
    if match is None:
        raise ValueError(
            f"MUC entry {entry!r} does not match canonical "
            "'atom:<doc_id>:<start>-<end>' shape"
        )
    start = int(match.group("start"))
    end = int(match.group("end"))
    if end < start:
        raise ValueError(
            f"MUC entry {entry!r}: end {end} < start {start}"
        )
    return match.group("doc"), start, end


def collect_atom_spans(
    root: Mapping[str, Any],
    *,
    skip_literals: bool = True,
) -> set[tuple[str, int, int]]:
    """Walk an OnionL tree, return ``{(doc_id, start, end)}`` for every atom.

    The MUC labelling discipline (locked at
    :func:`cds_harness.translate.smt_emitter._atom_provenance`) keys
    each labelled assertion to the *first* :class:`Atom` it encloses;
    literal atoms (``predicate == "literal"``) carry constants and are
    not contradiction sources. ``skip_literals`` excludes them so the
    callers can assert MUC ⊆ predicate-atom-spans without spurious
    matches against constant operands.
    """
    spans: set[tuple[str, int, int]] = set()
    _walk_node(root, spans, skip_literals=skip_literals)
    return spans


def _walk_node(
    node: object,
    spans: set[tuple[str, int, int]],
    *,
    skip_literals: bool,
) -> None:
    if not isinstance(node, Mapping):
        return
    kind = node.get("kind")
    if kind == "atom":
        if skip_literals and node.get("predicate") == _LITERAL_PREDICATE:
            return
        source_span = node.get("source_span")
        if isinstance(source_span, Mapping):
            doc_id = source_span.get("doc_id")
            start = source_span.get("start")
            end = source_span.get("end")
            if isinstance(doc_id, str) and isinstance(start, int) and isinstance(end, int):
                spans.add((doc_id, start, end))
        return
    for child_key in ("children", "args", "body"):
        child = node.get(child_key)
        if isinstance(child, list):
            for item in child:
                _walk_node(item, spans, skip_literals=skip_literals)
        elif isinstance(child, Mapping):
            _walk_node(child, spans, skip_literals=skip_literals)
    guard = node.get("guard")
    if isinstance(guard, Mapping):
        _walk_node(guard, spans, skip_literals=skip_literals)


def assert_muc_topology(
    envelope: Mapping[str, Any],
    *,
    expected_doc_id: str,
) -> list[tuple[str, int, int]]:
    """Verify that every ``trace.muc`` entry resolves to an IR atom span.

    Phase 0 hard-constraint **C4** ("every contradiction triggers
    topological mapping back to its offending textual node") is the
    contract under test. The IR tree comes from the same workflow
    envelope (``envelope["ir"]["root"]``) so MUC ↔ source-span
    consistency is checked end-to-end.

    Returns the parsed MUC tuples (in original order) for downstream
    diagnostics.

    Raises:
        AssertionError: if any MUC entry is malformed, references a
            different doc_id, or has no matching atom span in the IR
            tree.
    """
    trace = envelope.get("trace")
    if not isinstance(trace, Mapping):
        raise AssertionError(f"envelope.trace missing or non-object: {trace!r}")
    muc_raw = trace.get("muc")
    if not isinstance(muc_raw, list) or not muc_raw:
        raise AssertionError(
            f"envelope.trace.muc must be a non-empty list (got {muc_raw!r})"
        )
    ir = envelope.get("ir")
    if not isinstance(ir, Mapping):
        raise AssertionError(f"envelope.ir missing or non-object: {ir!r}")
    root = ir.get("root")
    if not isinstance(root, Mapping):
        raise AssertionError(f"envelope.ir.root missing or non-object: {root!r}")
    atom_spans = collect_atom_spans(root)
    parsed: list[tuple[str, int, int]] = []
    for raw_entry in muc_raw:
        if not isinstance(raw_entry, str):
            raise AssertionError(f"MUC entry {raw_entry!r} is not a string")
        doc_id, start, end = parse_muc_entry(raw_entry)
        if doc_id != expected_doc_id:
            raise AssertionError(
                f"MUC entry {raw_entry!r} carries doc_id {doc_id!r}; "
                f"expected {expected_doc_id!r}"
            )
        if (doc_id, start, end) not in atom_spans:
            raise AssertionError(
                f"MUC entry {raw_entry!r} has no matching Atom span in the IR tree "
                f"(IR atoms: {sorted(atom_spans)})"
            )
        parsed.append((doc_id, start, end))
    return parsed


def iter_observation_entries(
    notification: Mapping[str, Any],
) -> Iterable[Mapping[str, Any]]:
    """Yield the Observation entries from a subscription-notification Bundle.

    Skips ``entry[0]`` (``SubscriptionStatus``). Used by the test suite
    to assert post-wrap entry counts.
    """
    entries = notification.get("entry") or []
    if not isinstance(entries, list):
        return
    for entry in entries[1:]:
        if isinstance(entry, Mapping):
            yield entry


__all__ = [
    "assert_muc_topology",
    "build_patient_close_event",
    "build_patient_open_event",
    "build_subscription_notification",
    "collect_atom_spans",
    "iter_observation_entries",
    "parse_muc_entry",
]
