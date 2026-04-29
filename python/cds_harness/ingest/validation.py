"""Cross-loader semantic validators.

These checks run after the schema has finished its structural validation
but before the loader hands a payload to downstream consumers. They
encode boundary policy (no duplicate monotonic markers; no off-namespace
vital keys) that the schema deliberately does not enforce.
"""

from __future__ import annotations

from collections.abc import Iterable

from cds_harness.ingest.canonical import CANONICAL_VITALS
from cds_harness.ingest.errors import DuplicateMonotonicError, UnknownVitalError
from cds_harness.schema import TelemetrySample


def assert_unique_monotonic(samples: Iterable[TelemetrySample]) -> None:
    """Reject if any two samples share a ``monotonic_ns`` value."""
    seen: set[int] = set()
    for idx, sample in enumerate(samples):
        if sample.monotonic_ns in seen:
            raise DuplicateMonotonicError(
                f"duplicate monotonic_ns={sample.monotonic_ns} at sample index {idx}"
            )
        seen.add(sample.monotonic_ns)


def assert_canonical_vitals(samples: Iterable[TelemetrySample]) -> None:
    """Reject if any sample carries a vital key outside the canonical namespace."""
    canonical_sorted = sorted(CANONICAL_VITALS)
    for idx, sample in enumerate(samples):
        for key in sample.vitals:
            if key not in CANONICAL_VITALS:
                raise UnknownVitalError(
                    f"sample {idx}: unknown vital {key!r}; canonical set={canonical_sorted}"
                )


__all__ = ["assert_canonical_vitals", "assert_unique_monotonic"]
