"""FHIRcast STU3 collaborative-session events → harness session registry (Task 10.3).

The contract is locked in **ADR-026**. The harness is the *subscriber*
side: a FHIRcast Hub publishes `patient-open` / `patient-close` events
to a Dapr pub/sub topic; Dapr's declarative subscription routes each
topic to an HTTP route on the harness FastAPI service.

Two on-the-wire shapes are accepted:

* **Raw FHIRcast notification** (direct webhook fallback / unit tests):
  ``{"timestamp": "<ISO-8601>", "id": "<event-id>",
  "event": {"hub.topic": "<UUID-session>",
           "hub.event": "patient-open" | "patient-close",
           "context": [{"key": "patient", "resource": <Patient>}]}}``

* **Dapr-wrapped CloudEvent 1.0** (the path Dapr pub/sub takes by
  default): ``{"specversion": "1.0", "type": ..., "source": ...,
  "id": ..., "data": <FHIRcast notification>, ...}``. Detected by the
  presence of the ``specversion`` key on the top-level envelope; the
  handler unwraps ``data`` automatically.

Patient pseudo-id extraction: the entry whose ``key == "patient"``
must carry a ``resource`` of ``resourceType == "Patient"`` with a
non-empty ``id``. The pseudo-id is that ``id`` verbatim (mirrors the
``Patient/<id>`` ↔ ``patient_pseudo_id`` discipline locked by ADR-025
§4 §C). Multi-patient context arrays raise :class:`FHIRcastError`.

Session registry: an in-process thread-safe dict keyed by
``hub.topic``. Phase 1 cloud axis (Task 11.x) migrates this to a Dapr
state store; the constructor accepts a backing-store callable to keep
the swap drop-in.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from cds_harness.ingest.errors import FHIRcastError
from cds_harness.ingest.timestamps import canonicalize_utc

TOPIC_PATIENT_OPEN: Final[str] = "fhircast.patient-open"
TOPIC_PATIENT_CLOSE: Final[str] = "fhircast.patient-close"

EVENT_PATIENT_OPEN: Final[str] = "patient-open"
EVENT_PATIENT_CLOSE: Final[str] = "patient-close"

_HUB_TOPIC_KEY: Final[str] = "hub.topic"
_HUB_EVENT_KEY: Final[str] = "hub.event"
_PATIENT_KEY: Final[str] = "patient"
_PATIENT_RESOURCE_TYPE: Final[str] = "Patient"
_CLOUDEVENTS_VERSION_KEY: Final[str] = "specversion"
_CLOUDEVENTS_DATA_KEY: Final[str] = "data"


HubEvent = Literal["patient-open", "patient-close"]


class FHIRcastEvent(BaseModel):
    """Projected FHIRcast event ready for the session registry.

    Frozen + ``extra="forbid"`` to keep the projection result a stable
    boundary contract. ``timestamp`` is canonicalized to microsecond
    UTC ``Z`` form for byte-stable equality across Hub variants;
    ``patient_pseudo_id`` is the pseudo-id stripped from
    ``Patient.id``. Both ``hub_topic`` and ``event_id`` are pass-
    through identifiers — the harness never inspects their internals.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: str = Field(..., min_length=1)
    timestamp: str = Field(..., min_length=1)
    hub_topic: str = Field(..., min_length=1)
    hub_event: HubEvent
    patient_pseudo_id: str = Field(..., min_length=1)


def parse_event(
    raw: Mapping[str, Any],
    *,
    expected_event: HubEvent,
) -> FHIRcastEvent:
    """Project a FHIRcast notification (raw or CloudEvents-wrapped) to :class:`FHIRcastEvent`.

    Args:
        raw: Either a raw FHIRcast notification dict (top-level
            ``timestamp`` / ``id`` / ``event``) or a CloudEvents 1.0
            envelope wrapping the notification under ``data``.
        expected_event: The route's contract — ``"patient-open"`` for
            ``/v1/fhircast/patient-open``, ``"patient-close"`` for
            ``/v1/fhircast/patient-close``. Mismatched ``hub.event``
            values raise :class:`FHIRcastError` (catches Hub-side
            topic misrouting at the boundary).

    Raises:
        FHIRcastError: on any deviation from the ADR-026 projection
            contract — missing envelope fields, wrong ``hub.event``,
            multi-patient context, missing/invalid Patient resource.
    """
    if not isinstance(raw, Mapping):
        raise FHIRcastError(
            f"expected dict-like FHIRcast envelope; got {type(raw).__name__}"
        )

    notification = _unwrap_cloudevent(raw)
    event_id, timestamp_raw, event_obj = _split_envelope(notification)
    hub_topic, hub_event = _read_event_object(event_obj)

    if hub_event != expected_event:
        raise FHIRcastError(
            f"hub.event {hub_event!r} does not match route contract "
            f"{expected_event!r}"
        )

    patient_pseudo_id = _extract_patient_pseudo_id(event_obj)

    try:
        timestamp = canonicalize_utc(timestamp_raw)
    except Exception as exc:  # InvalidTimestampError or anything else
        raise FHIRcastError(
            f"timestamp {timestamp_raw!r} not canonicalizable: {exc}"
        ) from exc

    return FHIRcastEvent(
        event_id=event_id,
        timestamp=timestamp,
        hub_topic=hub_topic,
        hub_event=hub_event,
        patient_pseudo_id=patient_pseudo_id,
    )


def _unwrap_cloudevent(raw: Mapping[str, Any]) -> Mapping[str, Any]:
    """If ``raw`` is a CloudEvents 1.0 envelope, return its ``data`` payload.

    Detected by the presence of ``specversion`` (CloudEvents 1.0
    requires it). When unwrapped, ``data`` must itself be a Mapping —
    Dapr posts JSON CloudEvents with the FHIRcast notification inline
    as a JSON object, not a base64 string.
    """
    if _CLOUDEVENTS_VERSION_KEY not in raw:
        return raw
    data = raw.get(_CLOUDEVENTS_DATA_KEY)
    if not isinstance(data, Mapping):
        raise FHIRcastError(
            f"CloudEvents envelope ({_CLOUDEVENTS_DATA_KEY!r}) is not a JSON "
            f"object: type={type(data).__name__}"
        )
    return data


def _split_envelope(
    notification: Mapping[str, Any],
) -> tuple[str, str, Mapping[str, Any]]:
    event_id = notification.get("id")
    timestamp = notification.get("timestamp")
    event_obj = notification.get("event")
    if not isinstance(event_id, str) or not event_id:
        raise FHIRcastError(
            f"FHIRcast envelope missing/invalid 'id': {event_id!r}"
        )
    if not isinstance(timestamp, str) or not timestamp:
        raise FHIRcastError(
            f"FHIRcast envelope missing/invalid 'timestamp': {timestamp!r}"
        )
    if not isinstance(event_obj, Mapping):
        raise FHIRcastError(
            f"FHIRcast envelope missing/invalid 'event' object: "
            f"{type(event_obj).__name__}"
        )
    return event_id, timestamp, event_obj


def _read_event_object(event_obj: Mapping[str, Any]) -> tuple[str, HubEvent]:
    hub_topic = event_obj.get(_HUB_TOPIC_KEY)
    hub_event = event_obj.get(_HUB_EVENT_KEY)
    if not isinstance(hub_topic, str) or not hub_topic:
        raise FHIRcastError(
            f"FHIRcast event missing/invalid {_HUB_TOPIC_KEY!r}: "
            f"{hub_topic!r}"
        )
    if hub_event not in (EVENT_PATIENT_OPEN, EVENT_PATIENT_CLOSE):
        raise FHIRcastError(
            f"FHIRcast event has unsupported {_HUB_EVENT_KEY!r}={hub_event!r}; "
            f"expected one of "
            f"{(EVENT_PATIENT_OPEN, EVENT_PATIENT_CLOSE)!r}"
        )
    return hub_topic, hub_event  # type: ignore[return-value]


def _extract_patient_pseudo_id(event_obj: Mapping[str, Any]) -> str:
    context = event_obj.get("context")
    if not isinstance(context, list) or not context:
        raise FHIRcastError(
            "FHIRcast event 'context' must be a non-empty list "
            f"(got {type(context).__name__})"
        )

    patient_entries: list[Mapping[str, Any]] = []
    for entry in context:
        if not isinstance(entry, Mapping):
            raise FHIRcastError(
                f"FHIRcast context entry must be a JSON object; "
                f"got {type(entry).__name__}"
            )
        if entry.get("key") == _PATIENT_KEY:
            patient_entries.append(entry)

    if not patient_entries:
        raise FHIRcastError(
            "FHIRcast event missing required patient context entry "
            f"(key={_PATIENT_KEY!r})"
        )
    if len(patient_entries) > 1:
        raise FHIRcastError(
            f"FHIRcast event has multiple patient context entries "
            f"(count={len(patient_entries)}); single-patient invariant"
        )

    resource = patient_entries[0].get("resource")
    if not isinstance(resource, Mapping):
        raise FHIRcastError(
            "FHIRcast patient context entry missing 'resource' object "
            f"(got {type(resource).__name__})"
        )
    resource_type = resource.get("resourceType")
    if resource_type != _PATIENT_RESOURCE_TYPE:
        raise FHIRcastError(
            f"FHIRcast patient context resourceType={resource_type!r}, "
            f"expected {_PATIENT_RESOURCE_TYPE!r}"
        )
    patient_id = resource.get("id")
    if not isinstance(patient_id, str) or not patient_id:
        raise FHIRcastError(
            f"FHIRcast Patient resource missing/invalid 'id': {patient_id!r}"
        )
    return patient_id


class FHIRcastSessionRegistry:
    """Thread-safe in-process FHIRcast session registry.

    State per ``hub.topic`` is either ``None`` (no patient currently
    in context — initial / post-close) or a non-empty patient pseudo-
    id string. ``apply_open`` replaces any existing patient on the
    same topic (FHIRcast STU3 §3.3.1: "the indicated patient is now
    the current patient in context"). ``apply_close`` is idempotent —
    close-without-open is a no-op (FHIRcast STU3 §3.3.2: "previously
    open ... is no longer open").

    Phase 1 cloud axis (Task 11.x) migrates this to a Dapr state
    store. The constructor remains argument-free so the migration
    can introduce a backing-store callable without breaking existing
    callers.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state: dict[str, str | None] = {}

    def apply_open(self, event: FHIRcastEvent) -> None:
        if event.hub_event != EVENT_PATIENT_OPEN:
            raise FHIRcastError(
                f"apply_open called with hub_event={event.hub_event!r}"
            )
        with self._lock:
            self._state[event.hub_topic] = event.patient_pseudo_id

    def apply_close(self, event: FHIRcastEvent) -> None:
        if event.hub_event != EVENT_PATIENT_CLOSE:
            raise FHIRcastError(
                f"apply_close called with hub_event={event.hub_event!r}"
            )
        with self._lock:
            self._state[event.hub_topic] = None

    def current_patient(self, hub_topic: str) -> str | None:
        with self._lock:
            return self._state.get(hub_topic)

    def active_topics(self) -> dict[str, str]:
        """Snapshot of currently-open ``{hub_topic: patient_pseudo_id}``."""
        with self._lock:
            return {
                topic: patient
                for topic, patient in self._state.items()
                if patient is not None
            }

    def clear(self) -> None:
        with self._lock:
            self._state.clear()


__all__ = [
    "EVENT_PATIENT_CLOSE",
    "EVENT_PATIENT_OPEN",
    "TOPIC_PATIENT_CLOSE",
    "TOPIC_PATIENT_OPEN",
    "FHIRcastEvent",
    "FHIRcastSessionRegistry",
    "HubEvent",
    "parse_event",
]
