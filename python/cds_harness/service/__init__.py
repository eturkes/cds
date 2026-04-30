"""FastAPI service exposing the harness ingest + translate stages.

The service binds the Phase 0 ingestion (Task 3) and CLOVER + SMT-emitter
translation (Task 4) machinery behind two JSON-over-TCP endpoints so the
Dapr sidecar (Task 8) can drive them via service-invocation:

* ``POST /v1/ingest`` — validate + canonicalize a
  :class:`~cds_harness.schema.ClinicalTelemetryPayload` envelope or an
  in-memory CSV body.
* ``POST /v1/translate`` — lift a guideline ``(doc_id, text, root)`` into
  an :class:`~cds_harness.schema.OnionLIRTree` and lower it to an
  :class:`~cds_harness.schema.SmtConstraintMatrix`.

The transport contract is JSON-over-TCP only (constraint **C6**); the
sidecar invokes the service through ``http://localhost:<dapr_port>/v1.0/
invoke/cds-harness/method/v1/...``. See ADR-016 for the sidecar
invocation contract and ADR-017 for the service contract itself.
"""

from __future__ import annotations

from cds_harness.service.app import (
    DEFAULT_HOST,
    DEFAULT_PORT,
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
