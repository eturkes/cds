# Sample telemetry datasets

Tiny hand-authored datasets used by Task 3 (live genuine data ingestion) and
the ingestion test suite (`python/tests/test_ingest.py`). All files are
plain text and live entirely in this repository — no external fetches,
per constraint **C1**.

| File                              | Format     | Notes                                                                 |
| --------------------------------- | ---------- | --------------------------------------------------------------------- |
| `icu-monitor-01.csv`              | CSV stream | 10 rows of canonical vitals; required reserved columns first.         |
| `icu-monitor-01.meta.json`        | sidecar    | `source` (mandatory) + `events` (optional) for the CSV above.         |
| `icu-monitor-02.json`             | envelope   | Whole-payload form (already shaped like `ClinicalTelemetryPayload`).  |

## Adding a new sample

1. Either drop a `*.csv` + matching `<stem>.meta.json` pair, or drop a
   single `*.json` envelope. Anything else is rejected by the loader.
2. Vital column names must be members of
   `cds_harness.ingest.canonical.CANONICAL_VITALS`.
3. Wall-clock strings must be RFC 3339 UTC with a literal `Z` suffix.
4. `monotonic_ns` must be unique within a single dataset.
