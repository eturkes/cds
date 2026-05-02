"""Standalone runner for the `fhir-pipeline-smoke` Justfile recipe.

POSTs a synthetic FHIR R5 Subscriptions Backport ``subscription-
notification`` Bundle (built from ``data/fhir/icu-monitor-02.observations.json``
plus a ``SubscriptionStatus`` resource at ``entry[0]``) to a running
harness service's ``/v1/fhir/notification`` endpoint and asserts the
projected :class:`~cds_harness.schema.ClinicalTelemetryPayload` matches
the canonical icu-monitor-02 shape locked by ADR-025 §4.

Used only by the ``fhir-pipeline-smoke`` recipe — extracted to a file
because just shebang recipes don't tolerate column-zero embedded
multi-line Python heredocs cleanly.
"""

from __future__ import annotations

import json
import sys
import urllib.request


def _build_notification(fixture_path: str) -> dict[str, object]:
    with open(fixture_path, encoding="utf-8") as fh:
        coll = json.loads(fh.read())
    return {
        "resourceType": "Bundle",
        "id": "ntfn-icu02",
        "type": "subscription-notification",
        "entry": [
            {
                "fullUrl": "urn:uuid:status",
                "resource": {
                    "resourceType": "SubscriptionStatus",
                    "status": "active",
                    "type": "event-notification",
                    "subscription": {"reference": "Subscription/sub-icu-01"},
                    "topic": "http://example.org/SubscriptionTopic/icu-vitals",
                },
            },
            *coll["entry"],
        ],
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


def _assert_canonical(payload: dict[str, object]) -> None:
    source = payload["source"]
    assert isinstance(source, dict), source
    assert source["device_id"] == "fhir:ntfn-icu02", source
    assert source["patient_pseudo_id"] == "pseudo-def456", source
    samples = payload["samples"]
    assert isinstance(samples, list), samples
    assert len(samples) == 2, samples
    s0 = samples[0]
    assert isinstance(s0, dict)
    vitals = s0["vitals"]
    assert isinstance(vitals, dict)
    assert sorted(vitals.keys()) == ["heart_rate_bpm", "spo2_percent"], vitals
    assert abs(float(vitals["heart_rate_bpm"]) - 88.0) < 1e-9
    assert abs(float(vitals["spo2_percent"]) - 94.0) < 1e-9


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(f"usage: {argv[0]} <fixture> <notify-url>", file=sys.stderr)
        return 2
    _, fixture, notify_url = argv
    body = {"bundle": _build_notification(fixture)}
    response = _post_json(notify_url, body)
    payload = response.get("payload")
    if not isinstance(payload, dict):
        print(f"unexpected response: {response!r}", file=sys.stderr)
        return 1
    _assert_canonical(payload)
    print("✓ fhir-pipeline-smoke: notification → ClinicalTelemetryPayload OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
