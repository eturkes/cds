"""Ingestion error hierarchy.

All ingestion errors derive from :class:`IngestError` so the CLI can convert
them uniformly to a non-zero exit code.
"""

from __future__ import annotations


class IngestError(ValueError):
    """Base class for all telemetry-ingestion failures."""


class DuplicateMonotonicError(IngestError):
    """Raised when two samples in a single payload share a ``monotonic_ns``."""


class InvalidTimestampError(IngestError):
    """Raised on non-RFC-3339-UTC wall-clock strings (missing ``Z``, offset, naive)."""


class MalformedCsvError(IngestError):
    """Raised on missing/empty headers, missing required columns, or unparseable cells."""


class MissingMetadataError(IngestError):
    """Raised when a ``*.csv`` source lacks its required ``<stem>.meta.json`` sidecar."""


class UnknownVitalError(IngestError):
    """Raised when a vital column or key is outside the canonical namespace."""


class FHIRBundleError(IngestError):
    """Raised on any malformed / out-of-contract FHIR R5 Observation Bundle.

    Phase 1 (Task 10.2). Covers structural Bundle violations (wrong type,
    empty entries, multi-patient), Observation projection failures (LOINC
    not in locked table, UCUM mismatch, missing valueQuantity), and the
    single-vital-per-timestamp uniqueness invariant. See ADR-025 §4 for
    the full projection contract.
    """


__all__ = [
    "DuplicateMonotonicError",
    "FHIRBundleError",
    "IngestError",
    "InvalidTimestampError",
    "MalformedCsvError",
    "MissingMetadataError",
    "UnknownVitalError",
]
