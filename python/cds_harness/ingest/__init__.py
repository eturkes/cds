"""Local CSV/JSON telemetry ingestion → :class:`ClinicalTelemetryPayload`.

Phase 0 ingestion (Task 3) reads only **local** files in ``data/`` (constraint
C1; no HTTP fetch, no FHIR live streaming). Two file shapes are supported:

* ``*.csv`` paired with a sidecar ``<stem>.meta.json`` carrying the
  :class:`TelemetrySource` and any :class:`DiscreteEvent` annotations.
* ``*.json`` whole-envelope payloads (already shaped like
  :class:`ClinicalTelemetryPayload`).

Every loader normalizes wall-clock timestamps to canonical microsecond UTC
(``YYYY-MM-DDTHH:MM:SS.ffffffZ``), enforces a strict canonical vital-key
namespace (:data:`CANONICAL_VITALS`), and rejects duplicate
``monotonic_ns`` values within a single payload as a hard error.
"""

from __future__ import annotations

from cds_harness.ingest.canonical import CANONICAL_VITALS
from cds_harness.ingest.csv_loader import load_csv, load_csv_text
from cds_harness.ingest.errors import (
    DuplicateMonotonicError,
    FHIRBundleError,
    IngestError,
    InvalidTimestampError,
    MalformedCsvError,
    MissingMetadataError,
    UnknownVitalError,
)
from cds_harness.ingest.fhir_observation import bundle_to_payload
from cds_harness.ingest.json_loader import load_json, load_json_envelope
from cds_harness.ingest.loader import discover_payloads
from cds_harness.ingest.timestamps import canonicalize_utc, parse_utc_timestamp

__all__ = [
    "CANONICAL_VITALS",
    "DuplicateMonotonicError",
    "FHIRBundleError",
    "IngestError",
    "InvalidTimestampError",
    "MalformedCsvError",
    "MissingMetadataError",
    "UnknownVitalError",
    "bundle_to_payload",
    "canonicalize_utc",
    "discover_payloads",
    "load_csv",
    "load_csv_text",
    "load_json",
    "load_json_envelope",
    "parse_utc_timestamp",
]
