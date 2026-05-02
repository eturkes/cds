"""Standalone runner for the `fhircast-smoke` Justfile recipe.

POSTs a synthetic FHIRcast STU3 ``patient-open`` notification followed
by a ``patient-close`` to a running harness service's
``/v1/fhircast/patient-open`` + ``/v1/fhircast/patient-close`` routes,
and asserts that ``GET /v1/fhircast/sessions`` reflects the registry
transitions correctly. Locked by ADR-026 §11.

Used only by the ``fhircast-smoke`` recipe — extracted to a file
because just shebang recipes don't tolerate column-zero embedded
multi-line Python heredocs cleanly. Mirrors the
``fhir_pipeline_smoke.py`` precedent (Task 10.2).

The smoke is harness-side end-to-end and does **not** require a live
FHIRcast Hub or a running Dapr cluster; live Hub → Dapr → harness
delivery is Task 10.4 / 11.4 close-out scope (ADR-026 §11).
"""

from __future__ import annotations

import json
import sys
import urllib.request

_SESSION_TOPIC = "https://hub.example.org/topic/cds-fhircast-smoke"
_PATIENT_PSEUDO_ID = "pseudo-fhircast-001"


def _patient_open_payload() -> dict[str, object]:
    return {
        "timestamp": "2026-05-02T12:00:00.000000Z",
        "id": "evt-smoke-open-001",
        "event": {
            "hub.topic": _SESSION_TOPIC,
            "hub.event": "patient-open",
            "context": [
                {
                    "key": "patient",
                    "resource": {
                        "resourceType": "Patient",
                        "id": _PATIENT_PSEUDO_ID,
                        "identifier": [
                            {
                                "system": "urn:cds:smoke",
                                "value": _PATIENT_PSEUDO_ID,
                            },
                        ],
                    },
                },
            ],
        },
    }


def _patient_close_payload() -> dict[str, object]:
    return {
        "timestamp": "2026-05-02T12:30:00.000000Z",
        "id": "evt-smoke-close-001",
        "event": {
            "hub.topic": _SESSION_TOPIC,
            "hub.event": "patient-close",
            "context": [
                {
                    "key": "patient",
                    "resource": {
                        "resourceType": "Patient",
                        "id": _PATIENT_PSEUDO_ID,
                    },
                },
            ],
        },
    }


def _post_json(url: str, body: dict[str, object]) -> dict[str, object]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10.0) as resp:
        body_bytes = resp.read()
    parsed = json.loads(body_bytes.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise SystemExit(f"unexpected non-dict response: {parsed!r}")
    return parsed


def _get_json(url: str) -> dict[str, object]:
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/json"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=10.0) as resp:
        body_bytes = resp.read()
    parsed = json.loads(body_bytes.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise SystemExit(f"unexpected non-dict sessions response: {parsed!r}")
    return parsed


def _assert_open_response(response: dict[str, object]) -> None:
    applied = response.get("applied")
    assert isinstance(applied, dict), applied
    assert applied["hub_event"] == "patient-open", applied
    assert applied["hub_topic"] == _SESSION_TOPIC, applied
    assert applied["patient_pseudo_id"] == _PATIENT_PSEUDO_ID, applied
    assert response["current_patient"] == _PATIENT_PSEUDO_ID, response


def _assert_close_response(response: dict[str, object]) -> None:
    applied = response.get("applied")
    assert isinstance(applied, dict), applied
    assert applied["hub_event"] == "patient-close", applied
    assert applied["hub_topic"] == _SESSION_TOPIC, applied
    assert applied["patient_pseudo_id"] == _PATIENT_PSEUDO_ID, applied
    assert response["current_patient"] is None, response


def _assert_sessions_after_open(response: dict[str, object]) -> None:
    active = response.get("active")
    assert isinstance(active, dict), active
    assert active.get(_SESSION_TOPIC) == _PATIENT_PSEUDO_ID, active


def _assert_sessions_after_close(response: dict[str, object]) -> None:
    active = response.get("active")
    assert isinstance(active, dict), active
    assert _SESSION_TOPIC not in active, active


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {argv[0]} <harness-base-url>", file=sys.stderr)
        return 2
    base = argv[1].rstrip("/")
    open_url = f"{base}/v1/fhircast/patient-open"
    close_url = f"{base}/v1/fhircast/patient-close"
    sessions_url = f"{base}/v1/fhircast/sessions"

    open_response = _post_json(open_url, _patient_open_payload())
    _assert_open_response(open_response)
    _assert_sessions_after_open(_get_json(sessions_url))

    close_response = _post_json(close_url, _patient_close_payload())
    _assert_close_response(close_response)
    _assert_sessions_after_close(_get_json(sessions_url))

    print("✓ fhircast-smoke: patient-open → patient-close → registry OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
