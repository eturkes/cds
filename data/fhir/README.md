# Canonical FHIR R5 Observation fixtures (Phase 1, Task 10.1)

This directory carries the canonical FHIR R5 `Observation` Bundles
that mirror the Phase 0 `data/sample/icu-monitor-*.{csv,json}`
telemetry samples. Tasks 10.2 (FHIR Subscriptions) and 10.3
(FHIRcast) consume them through the harness ingestion adapter
defined by **ADR-025** §4.

The Phase 0 local CSV/JSON ingestion path under `data/sample/`
remains authoritative for regression — these fixtures are
**parallel**, not replacing (per ADR-024 §3 C1 refinement).

## Files

| File                                        | Mirrors Phase 0 sample                                                | Bundle entries           |
| ------------------------------------------- | --------------------------------------------------------------------- | ------------------------ |
| `icu-monitor-01.observations.json`          | `data/sample/icu-monitor-01.csv` (+ `.meta.json` sidecar)             | 12 (2 timestamps × 6 vitals) |
| `icu-monitor-02.observations.json`          | `data/sample/icu-monitor-02.json`                                     | 4 (2 timestamps × 2 vitals — HR + SpO2) |

Each file is a FHIR R5 `Bundle` with `type = "collection"`. Each
`entry.resource` is a single-vital `Observation` carrying the LOINC
code, UCUM unit, decimal value, RFC 3339 `effectiveDateTime`, and a
`subject.reference` to the patient pseudo-ID.

## Locked LOINC mapping (`vital_key` ↔ LOINC ↔ UCUM)

The mapping is the Phase 1 boundary contract — adding a canonical
vital is a coordinated edit across `CANONICAL_VITALS` (Python +
Rust), `LOINC_BY_VITAL` (Python harness — `cds_harness.ingest.loinc`),
**ADR-025 §4**, and any new fixtures.

| `vital_key`            | LOINC code | Display                            | UCUM unit |
| ---------------------- | ---------- | ---------------------------------- | --------- |
| `diastolic_mmhg`       | 8462-4     | Diastolic blood pressure           | `mm[Hg]`  |
| `heart_rate_bpm`       | 8867-4     | Heart rate                         | `/min`    |
| `respiratory_rate_bpm` | 9279-1     | Respiratory rate                   | `/min`    |
| `spo2_percent`         | 2708-6     | Oxygen saturation in Arterial blood | `%`       |
| `systolic_mmhg`        | 8480-6     | Systolic blood pressure            | `mm[Hg]`  |
| `temp_celsius`         | 8310-5     | Body temperature                   | `Cel`     |

System URI for LOINC codes is `http://loinc.org`; system URI for UCUM
units is `http://unitsofmeasure.org`. Both are the FHIR R5 canonical
choices.

## Events deferral

Phase 0's `events` sidecar (e.g. `manual_bp_cuff_inflate` in
`data/sample/icu-monitor-01.meta.json`) is **not** carried by these
Observation Bundles. FHIRcast (Task 10.3) is the standard FHIR
carrier for collaborative-session events; the Phase 0 events path
remains authoritative for the local CSV/JSON ingestion route. ADR-025
§4 documents the deferral.

## Adding a fixture

1. Build the FHIR R5 `Bundle` JSON with `type = "collection"` and one
   `Observation` per vital sample. Cross-reference the locked LOINC
   table above for `code`/`unit`.
2. Validate the Bundle via the parity test:
   `uv run pytest python/tests/test_fhir_fixtures.py -q`.
3. Document the new fixture in the **Files** table above.
4. If the fixture introduces a new canonical vital, follow the
   coordinated-edit checklist in ADR-011 + ADR-025 §4.

## Relationship to the Phase 0 sample data

The Phase 0 `data/sample/icu-monitor-01.csv` has 10 timestamps × 6
vitals = 60 rows; this Phase 1 fixture trims to 2 timestamps × 6
vitals = 12 entries to keep the JSON compact while exercising every
canonical vital. The full 10-timestamp fidelity is exercised by
end-to-end smoke recipes in 10.4 (close-out), where the harness
re-ingests `data/sample/icu-monitor-01.csv` through the FHIR
boundary as a streaming subscription.

`data/sample/icu-monitor-02.json` has 2 timestamps × 2 vitals = 4
samples; this Phase 1 fixture is a 1:1 mirror.
