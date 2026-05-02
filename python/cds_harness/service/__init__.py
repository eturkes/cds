"""FastAPI service exposing the harness ingest + translate stages.

The service binds the Phase 0 ingestion (Task 3) and CLOVER + SMT-emitter
translation (Task 4) machinery behind JSON-over-TCP endpoints so the
Dapr sidecar (Task 8) can drive them via service-invocation, plus the
Phase 1 FHIR (Task 10.2) + FHIRcast (Task 10.3) ingestion routes:

* ``POST /v1/ingest`` — validate + canonicalize a
  :class:`~cds_harness.schema.ClinicalTelemetryPayload` envelope or an
  in-memory CSV body.
* ``POST /v1/fhir/notification`` — accept a FHIR R5 ``Bundle`` (either
  ``type="collection"`` or ``type="subscription-notification"``) and
  project it into a :class:`~cds_harness.schema.ClinicalTelemetryPayload`
  via :func:`cds_harness.ingest.bundle_to_payload` (Task 10.2; ADR-025
  §4).
* ``POST /v1/fhircast/patient-open`` /
  ``POST /v1/fhircast/patient-close`` — accept FHIRcast STU3
  collaborative-session events (raw or Dapr-CloudEvents-wrapped),
  project them via :func:`cds_harness.ingest.parse_event`, and apply
  to the in-process
  :class:`~cds_harness.ingest.FHIRcastSessionRegistry` (Task 10.3;
  ADR-026).
* ``GET  /v1/fhircast/sessions`` — read-only snapshot of currently-
  open FHIRcast sessions (debug surface).
* ``POST /v1/translate`` — lift a guideline ``(doc_id, text, root)`` into
  an :class:`~cds_harness.schema.OnionLIRTree` and lower it to an
  :class:`~cds_harness.schema.SmtConstraintMatrix`.

The transport contract is JSON-over-TCP only (constraint **C6**); the
sidecar invokes the service through ``http://localhost:<dapr_port>/v1.0/
invoke/cds-harness/method/v1/...``. See ADR-016 for the sidecar
invocation contract and ADR-017 for the service contract itself; the
FHIRcast pub/sub topology is locked by ADR-026.
"""

from __future__ import annotations

from cds_harness.service.app import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    FHIR_NOTIFICATION_PATH,
    FHIRCAST_PATIENT_CLOSE_PATH,
    FHIRCAST_PATIENT_OPEN_PATH,
    FHIRCAST_SESSIONS_PATH,
    HEALTHZ_PATH,
    HOST_ENV,
    INGEST_PATH,
    PORT_ENV,
    SERVICE_APP_ID,
    TRANSLATE_PATH,
    create_app,
    resolve_host,
    resolve_port,
)

__all__ = [
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "FHIRCAST_PATIENT_CLOSE_PATH",
    "FHIRCAST_PATIENT_OPEN_PATH",
    "FHIRCAST_SESSIONS_PATH",
    "FHIR_NOTIFICATION_PATH",
    "HEALTHZ_PATH",
    "HOST_ENV",
    "INGEST_PATH",
    "PORT_ENV",
    "SERVICE_APP_ID",
    "TRANSLATE_PATH",
    "create_app",
    "resolve_host",
    "resolve_port",
]
