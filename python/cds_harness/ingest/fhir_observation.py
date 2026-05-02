"""FHIR R5 Bundle → :class:`ClinicalTelemetryPayload` projection (Task 10.2).

The mapping is locked in **ADR-025 §4**. It consumes a FHIR R5
``Bundle`` whose ``type`` is either:

* ``"collection"`` — used by the canonical fixtures under
  ``data/fhir/`` (Phase 1, Task 10.1).
* ``"subscription-notification"`` — the FHIR R5 Subscriptions Backport
  notification shape; ``entry[0]`` is the ``SubscriptionStatus``
  resource and is skipped, subsequent entries are the triggered
  ``Observation`` resources.

Each surviving ``Observation`` projects per ADR-025 §4:

* ``Observation.code.coding[0].code`` (LOINC, system
  ``http://loinc.org``) → vital key via :data:`VITAL_BY_LOINC`.
* ``Observation.valueQuantity.value`` (decimal) →
  ``samples[i].vitals[vital_key]`` (float). UCUM unit
  (``Observation.valueQuantity.code``) must match the locked unit per
  :data:`LOINC_BY_VITAL`.
* ``Observation.effectiveDateTime`` →
  ``samples[i].wall_clock_utc`` (canonicalized to microsecond UTC ``Z``
  via :func:`canonicalize_utc`). Read from the raw JSON dict because
  ``fhir.resources`` parses the field to a :class:`datetime` and drops
  the sub-second canonical form on the way out.
* Multiple Observations sharing the same canonical timestamp **bucket**
  into a single :class:`TelemetrySample` carrying multiple vitals
  (lexicographic key order — wire-stable with the Rust ``BTreeMap``).
* ``samples[i].monotonic_ns`` is derived from the parsed timestamp's
  nanoseconds-since-epoch. ADR-025 §4's ``+1ns`` tie-break is a safety
  belt; bucketing already eliminates the common collision case.
* Single-patient invariant — every Observation must share
  ``subject.reference``; multi-patient Bundles raise
  :class:`FHIRBundleError`.
* :class:`TelemetrySource` defaults to
  ``device_id = f"fhir:{Bundle.id}"`` + the patient pseudo-id stripped
  from ``Patient/<id>``. Callers may override via ``source_override``.

Events are deferred to Task 10.3 (FHIRcast) per ADR-025 §4 + ADR-024
§3 — Phase 0's local-CSV/JSON path retains events full-fidelity.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any, Final

from fhir.resources.bundle import Bundle
from fhir.resources.observation import Observation
from pydantic import ValidationError

from cds_harness.ingest.errors import FHIRBundleError
from cds_harness.ingest.loinc import (
    LOINC_BY_VITAL,
    LOINC_SYSTEM,
    UCUM_SYSTEM,
    VITAL_BY_LOINC,
)
from cds_harness.ingest.timestamps import canonicalize_utc, parse_utc_timestamp
from cds_harness.schema import (
    SCHEMA_VERSION,
    ClinicalTelemetryPayload,
    TelemetrySample,
    TelemetrySource,
)

_COLLECTION: Final[str] = "collection"
_SUBSCRIPTION_NOTIFICATION: Final[str] = "subscription-notification"
_PATIENT_PREFIX: Final[str] = "Patient/"
_DEVICE_ID_PREFIX: Final[str] = "fhir:"


def bundle_to_payload(
    raw: Mapping[str, Any],
    *,
    source_override: TelemetrySource | None = None,
) -> ClinicalTelemetryPayload:
    """Project a parsed FHIR R5 ``Bundle`` JSON dict to a canonical payload.

    ``raw`` is the dict-like JSON view (post-:func:`json.loads`) of an
    R5 Observation Bundle. It is structurally re-validated through
    :class:`fhir.resources.bundle.Bundle`; the function then walks the
    raw + parsed entries side-by-side so that ``effectiveDateTime`` can
    be read back as its canonical RFC 3339 string (the parsed
    :class:`datetime` form drops the sub-second canonical shape).

    Raises:
        FHIRBundleError: on any deviation from the ADR-025 §4 projection
            contract — invalid ``Bundle.type``, missing entries, non-
            Observation entry resources, multi-patient Bundle, missing
            LOINC / UCUM, off-table vital, duplicate vital at the same
            timestamp, or missing/invalid ``valueQuantity`` /
            ``effectiveDateTime``.
    """
    if not isinstance(raw, Mapping):
        raise FHIRBundleError(
            f"expected dict-like Bundle JSON; got {type(raw).__name__}"
        )

    try:
        bundle = Bundle.model_validate(dict(raw))
    except ValidationError as exc:
        raise FHIRBundleError(f"Bundle failed structural validation: {exc}") from exc

    raw_entries = list(raw.get("entry") or [])
    parsed_entries = list(bundle.entry or [])
    if len(raw_entries) != len(parsed_entries):
        raise FHIRBundleError(
            f"raw/parsed entry count mismatch: "
            f"raw={len(raw_entries)} parsed={len(parsed_entries)}"
        )

    bundle_type = str(bundle.type or "")
    if bundle_type == _SUBSCRIPTION_NOTIFICATION:
        if not parsed_entries:
            raise FHIRBundleError(
                "subscription-notification Bundle missing SubscriptionStatus at entry[0]"
            )
        observation_pairs = list(
            zip(raw_entries[1:], parsed_entries[1:], strict=True)
        )
    elif bundle_type == _COLLECTION:
        observation_pairs = list(zip(raw_entries, parsed_entries, strict=True))
    else:
        raise FHIRBundleError(
            f"unsupported Bundle.type {bundle_type!r}; "
            f"expected {_COLLECTION!r} or {_SUBSCRIPTION_NOTIFICATION!r}"
        )

    if not observation_pairs:
        raise FHIRBundleError("Bundle carries no Observation entries to project")

    observations = _collect_observations(observation_pairs)
    patient_pseudo_id = _resolve_single_patient(observations)

    bundle_id = bundle.id or "unknown"
    if source_override is None:
        source = TelemetrySource(
            device_id=f"{_DEVICE_ID_PREFIX}{bundle_id}",
            patient_pseudo_id=patient_pseudo_id,
        )
    else:
        if source_override.patient_pseudo_id != patient_pseudo_id:
            raise FHIRBundleError(
                f"source_override.patient_pseudo_id "
                f"{source_override.patient_pseudo_id!r} disagrees with Bundle subject "
                f"{patient_pseudo_id!r}"
            )
        source = source_override

    grouped = _project_observations(observations)
    samples = _group_to_samples(grouped)

    return ClinicalTelemetryPayload(
        schema_version=SCHEMA_VERSION,
        source=source,
        samples=samples,
    )


def _collect_observations(
    pairs: list[tuple[Mapping[str, Any], Any]],
) -> list[tuple[Mapping[str, Any], Observation]]:
    out: list[tuple[Mapping[str, Any], Observation]] = []
    for raw_entry, parsed_entry in pairs:
        resource = parsed_entry.resource
        if not isinstance(resource, Observation):
            kind = type(resource).__name__ if resource is not None else "None"
            full_url = parsed_entry.fullUrl or "<no-fullUrl>"
            raise FHIRBundleError(
                f"non-Observation entry resource {kind!r} (fullUrl={full_url})"
            )
        raw_resource = raw_entry.get("resource")
        if not isinstance(raw_resource, Mapping):
            raise FHIRBundleError(
                f"entry {parsed_entry.fullUrl!r}: missing dict-shaped raw resource"
            )
        out.append((raw_resource, resource))
    return out


def _resolve_single_patient(
    observations: list[tuple[Mapping[str, Any], Observation]],
) -> str:
    refs: set[str] = set()
    for _raw_obs, obs in observations:
        if obs.subject is None or not obs.subject.reference:
            raise FHIRBundleError(
                f"Observation {obs.id!r}: missing subject.reference"
            )
        refs.add(obs.subject.reference)
    if len(refs) != 1:
        raise FHIRBundleError(
            f"multi-patient Bundle: {sorted(refs)} — "
            "Phase 1 invariant: one payload per patient"
        )
    patient_ref = next(iter(refs))
    if not patient_ref.startswith(_PATIENT_PREFIX):
        raise FHIRBundleError(
            f"subject.reference {patient_ref!r} not 'Patient/<id>' form"
        )
    patient_pseudo_id = patient_ref[len(_PATIENT_PREFIX):]
    if not patient_pseudo_id:
        raise FHIRBundleError("subject.reference 'Patient/<id>' id is empty")
    return patient_pseudo_id


def _project_observations(
    observations: list[tuple[Mapping[str, Any], Observation]],
) -> dict[str, dict[str, float]]:
    grouped: dict[str, dict[str, float]] = {}
    for raw_obs, obs in observations:
        vital_key, value = _project_value(obs)
        wall_clock = _project_wall_clock(raw_obs, obs)
        bucket = grouped.setdefault(wall_clock, {})
        if vital_key in bucket:
            raise FHIRBundleError(
                f"Observation {obs.id!r}: duplicate vital {vital_key!r} "
                f"at {wall_clock} (existing={bucket[vital_key]}, new={value})"
            )
        bucket[vital_key] = value
    return grouped


def _project_value(obs: Observation) -> tuple[str, float]:
    codings = obs.code.coding or []
    if not codings:
        raise FHIRBundleError(f"Observation {obs.id!r}: missing code.coding")
    coding = codings[0]
    if coding.system != LOINC_SYSTEM:
        raise FHIRBundleError(
            f"Observation {obs.id!r}: coding.system={coding.system!r}, "
            f"expected {LOINC_SYSTEM!r}"
        )
    loinc = coding.code
    if loinc is None or loinc not in VITAL_BY_LOINC:
        raise FHIRBundleError(
            f"Observation {obs.id!r}: LOINC {loinc!r} not in locked LOINC_BY_VITAL"
        )
    vital_key = VITAL_BY_LOINC[loinc]
    _expected_loinc, expected_unit = LOINC_BY_VITAL[vital_key]

    quantity = obs.valueQuantity
    if quantity is None:
        raise FHIRBundleError(f"Observation {obs.id!r}: missing valueQuantity")
    if quantity.system != UCUM_SYSTEM:
        raise FHIRBundleError(
            f"Observation {obs.id!r}: UCUM system={quantity.system!r}, "
            f"expected {UCUM_SYSTEM!r}"
        )
    if quantity.code != expected_unit:
        raise FHIRBundleError(
            f"Observation {obs.id!r}: unit={quantity.code!r}, "
            f"expected {expected_unit!r} for {vital_key!r}"
        )
    if quantity.value is None:
        raise FHIRBundleError(f"Observation {obs.id!r}: valueQuantity.value is None")
    value = float(quantity.value)
    if not math.isfinite(value):
        raise FHIRBundleError(
            f"Observation {obs.id!r}: non-finite value {quantity.value!r}"
        )
    return vital_key, value


def _project_wall_clock(
    raw_obs: Mapping[str, Any], obs: Observation
) -> str:
    raw_dt = raw_obs.get("effectiveDateTime")
    if not isinstance(raw_dt, str) or not raw_dt:
        raise FHIRBundleError(
            f"Observation {obs.id!r}: effectiveDateTime missing or non-string in raw JSON"
        )
    return canonicalize_utc(raw_dt)


def _group_to_samples(
    grouped: dict[str, dict[str, float]],
) -> list[TelemetrySample]:
    samples: list[TelemetrySample] = []
    seen_monotonic: set[int] = set()
    for wall_clock in sorted(grouped):
        vitals = grouped[wall_clock]
        dt = parse_utc_timestamp(wall_clock)
        monotonic_ns = int(dt.timestamp() * 1_000_000_000)
        if monotonic_ns < 0:
            raise FHIRBundleError(
                f"computed monotonic_ns < 0 for {wall_clock!r}: {monotonic_ns}"
            )
        if monotonic_ns in seen_monotonic:
            monotonic_ns = max(seen_monotonic) + 1
        seen_monotonic.add(monotonic_ns)
        ordered = {k: vitals[k] for k in sorted(vitals)}
        samples.append(
            TelemetrySample(
                wall_clock_utc=wall_clock,
                monotonic_ns=monotonic_ns,
                vitals=ordered,
                events=[],
            )
        )
    return samples


__all__ = ["bundle_to_payload"]
