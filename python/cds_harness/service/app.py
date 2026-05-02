"""FastAPI application factory for the Phase 0/1 Python harness service.

The app exposes the following endpoints:

* ``GET  /healthz``     — liveness probe; returns ``{"status": "ok", ...}``.
* ``POST /v1/ingest``   — accept either a JSON envelope (``format="json"``)
  or an in-memory CSV body (``format="csv"``); return the validated +
  canonicalized :class:`~cds_harness.schema.ClinicalTelemetryPayload`.
* ``POST /v1/fhir/notification`` — accept a FHIR R5 ``Bundle``
  (``type="collection"`` or ``type="subscription-notification"``) and
  project it via :func:`cds_harness.ingest.bundle_to_payload`
  (Task 10.2; ADR-025 §4).
* ``POST /v1/fhircast/patient-open`` — accept a FHIRcast STU3
  ``patient-open`` notification (raw or Dapr-CloudEvents-wrapped) and
  apply it to the in-process :class:`FHIRcastSessionRegistry`
  (Task 10.3; ADR-026).
* ``POST /v1/fhircast/patient-close`` — analogous; clears the
  session for the carried ``hub.topic``.
* ``GET  /v1/fhircast/sessions`` — read-only snapshot of currently-
  open sessions ``{hub_topic: patient_pseudo_id}``.
* ``POST /v1/translate`` — accept ``(doc_id, text, root, logic,
  smt_check)`` and return ``{"tree", "matrix", "smt_check"}``.

Internal harness errors (:class:`~cds_harness.ingest.errors.IngestError`,
:class:`~cds_harness.translate.errors.TranslateError`) lift to HTTP
``422`` so callers see a structured failure mode without leaking stack
traces. Pydantic validation errors are handled by FastAPI's default
``422`` machinery.
"""

from __future__ import annotations

import json
import os
from typing import Annotated, Any, Final, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from cds_harness import HARNESS_ID, PHASE
from cds_harness.ingest import (
    EVENT_PATIENT_CLOSE,
    EVENT_PATIENT_OPEN,
    FHIRcastSessionRegistry,
    IngestError,
    bundle_to_payload,
    load_csv_text,
    load_json_envelope,
    parse_event,
)
from cds_harness.schema import (
    SCHEMA_VERSION,
    ClinicalTelemetryPayload,
    OnionLIRTree,
    OnionLNode,
    SmtConstraintMatrix,
)
from cds_harness.translate import (
    DEFAULT_LOGIC,
    TranslateError,
    emit_smt,
    smt_sanity_check,
    translate_guideline,
)

SERVICE_APP_ID: Final[str] = "cds-harness"
HEALTHZ_PATH: Final[str] = "/healthz"
INGEST_PATH: Final[str] = "/v1/ingest"
FHIR_NOTIFICATION_PATH: Final[str] = "/v1/fhir/notification"
FHIRCAST_PATIENT_OPEN_PATH: Final[str] = "/v1/fhircast/patient-open"
FHIRCAST_PATIENT_CLOSE_PATH: Final[str] = "/v1/fhircast/patient-close"
FHIRCAST_SESSIONS_PATH: Final[str] = "/v1/fhircast/sessions"
TRANSLATE_PATH: Final[str] = "/v1/translate"
DEFAULT_HOST: Final[str] = "127.0.0.1"
DEFAULT_PORT: Final[int] = 8081

PORT_ENV: Final[str] = "CDS_HARNESS_PORT"
HOST_ENV: Final[str] = "CDS_HARNESS_HOST"


def resolve_port(default: int = DEFAULT_PORT) -> int:
    raw = os.environ.get(PORT_ENV)
    if raw is None or not raw.strip():
        return default
    try:
        port = int(raw)
    except ValueError as exc:
        raise ValueError(f"{PORT_ENV}={raw!r} is not an integer") from exc
    if not (1 <= port <= 65535):
        raise ValueError(f"{PORT_ENV}={port} is outside [1, 65535]")
    return port


def resolve_host(default: str = DEFAULT_HOST) -> str:
    return os.environ.get(HOST_ENV) or default


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _IngestJsonRequest(_StrictModel):
    format: Literal["json"]
    envelope: dict[str, Any] = Field(
        ...,
        description="Whole-envelope ClinicalTelemetryPayload JSON (matching the schema).",
    )


class _IngestCsvRequest(_StrictModel):
    format: Literal["csv"]
    csv_text: str = Field(..., description="Raw CSV body (header row required).")
    meta: dict[str, Any] = Field(
        ...,
        description="Sidecar metadata: a 'source' object plus optional 'events' list.",
    )
    file_label: str = Field(
        default="<inline.csv>",
        description="Diagnostic label surfaced in malformed-row error messages.",
    )


_IngestRequest = Annotated[
    _IngestJsonRequest | _IngestCsvRequest,
    Field(discriminator="format"),
]


class _IngestResponse(BaseModel):
    payload: ClinicalTelemetryPayload


class _FHIRNotificationRequest(_StrictModel):
    """FHIR R5 Subscription notification (or canonical collection) Bundle.

    The harness accepts both the FHIR R5 Subscriptions Backport
    notification shape (``Bundle.type = "subscription-notification"``,
    ``entry[0]`` is a ``SubscriptionStatus``) and the 10.1 canonical
    collection shape (``Bundle.type = "collection"``); the projection
    logic in :func:`cds_harness.ingest.bundle_to_payload` dispatches on
    ``Bundle.type``. ADR-025 §4 fixes the projection contract.
    """

    bundle: dict[str, Any] = Field(
        ...,
        description=(
            "FHIR R5 Bundle JSON — type is 'collection' or 'subscription-notification'."
        ),
    )


class _FHIRcastEventEcho(BaseModel):
    """Wire-visible echo of the projected FHIRcast event (Task 10.3, ADR-026)."""

    event_id: str
    timestamp: str
    hub_topic: str
    hub_event: Literal["patient-open", "patient-close"]
    patient_pseudo_id: str


class _FHIRcastApplyResponse(BaseModel):
    applied: _FHIRcastEventEcho
    current_patient: str | None = None


class _FHIRcastSessionsResponse(BaseModel):
    active: dict[str, str]
    phase: int = PHASE
    schema_version: str = SCHEMA_VERSION


class _TranslateRequest(_StrictModel):
    doc_id: str = Field(..., min_length=1)
    text: str = Field(..., description="UTF-8 guideline body (used for source-span validation).")
    root: OnionLNode = Field(..., description="Pre-formalized OnionL root node.")
    logic: str = Field(
        default=DEFAULT_LOGIC,
        description="SMT-LIBv2 logic for the emitter preamble (default: QF_LRA).",
    )
    smt_check: bool = Field(
        default=False,
        description="If true, run the in-process Z3 sanity check and report the verdict.",
    )


class _TranslateResponse(BaseModel):
    tree: OnionLIRTree
    matrix: SmtConstraintMatrix
    smt_check: Literal["sat", "unsat", "unknown"] | None = None


class _Healthz(BaseModel):
    status: Literal["ok"] = "ok"
    harness_id: str = HARNESS_ID
    phase: int = PHASE
    schema_version: str = SCHEMA_VERSION


class _InlineAdapter:
    """:class:`AutoformalAdapter` returning a pre-supplied root unchanged.

    The translator validates source-span byte ranges against ``text`` (see
    :func:`cds_harness.translate.clover.translate_guideline`); supplying
    the root inline keeps the Phase 0 contract intact while moving the
    formalization step off the local filesystem. Structural conformance
    to :class:`AutoformalAdapter` is asserted by the test suite.
    """

    def __init__(self, root: OnionLNode) -> None:
        self._root = root

    def formalize(self, *, doc_id: str, text: str) -> OnionLNode:
        del doc_id, text  # unused; kept for protocol parity
        return self._root


async def _read_json_object(request: Request) -> dict[str, Any]:
    """Decode a request body as a JSON object.

    The FHIRcast routes accept either a raw FHIRcast notification or a
    Dapr-wrapped CloudEvent — both are JSON objects. Anything else is
    a contract violation surfaced as :class:`IngestError`.
    """
    raw = await request.body()
    if not raw:
        raise IngestError("FHIRcast request body is empty")
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise IngestError(f"FHIRcast request body is not valid JSON: {exc}") from exc
    if not isinstance(decoded, dict):
        raise IngestError(
            f"FHIRcast request body must be a JSON object; "
            f"got {type(decoded).__name__}"
        )
    return decoded


def _ingest(payload: _IngestRequest) -> _IngestResponse:
    try:
        if isinstance(payload, _IngestJsonRequest):
            canonical = load_json_envelope(payload.envelope)
        else:
            canonical = load_csv_text(
                payload.csv_text,
                payload.meta,
                file_label=payload.file_label,
            )
    except ValidationError as exc:
        raise IngestError(f"envelope failed schema validation: {exc.errors()!r}") from exc
    return _IngestResponse(payload=canonical)


def _fhir_notification(request: _FHIRNotificationRequest) -> _IngestResponse:
    payload = bundle_to_payload(request.bundle)
    return _IngestResponse(payload=payload)


def _fhircast_apply(
    raw: dict[str, Any],
    *,
    expected_event: Literal["patient-open", "patient-close"],
    registry: FHIRcastSessionRegistry,
) -> _FHIRcastApplyResponse:
    event = parse_event(raw, expected_event=expected_event)
    if expected_event == EVENT_PATIENT_OPEN:
        registry.apply_open(event)
    else:
        registry.apply_close(event)
    return _FHIRcastApplyResponse(
        applied=_FHIRcastEventEcho(
            event_id=event.event_id,
            timestamp=event.timestamp,
            hub_topic=event.hub_topic,
            hub_event=event.hub_event,
            patient_pseudo_id=event.patient_pseudo_id,
        ),
        current_patient=registry.current_patient(event.hub_topic),
    )


def _translate(request: _TranslateRequest) -> _TranslateResponse:
    adapter = _InlineAdapter(root=request.root)
    tree = translate_guideline(
        doc_id=request.doc_id,
        text=request.text,
        adapter=adapter,
    )
    matrix = emit_smt(tree, logic=request.logic)
    verdict = smt_sanity_check(matrix) if request.smt_check else None
    return _TranslateResponse(tree=tree, matrix=matrix, smt_check=verdict)


def create_app() -> FastAPI:
    """Construct the FastAPI app. One instance per process; no globals beyond env."""
    app = FastAPI(
        title="CDS Phase 0 Python harness",
        version=SCHEMA_VERSION,
        description=(
            "JSON-over-TCP service for the CDS Phase 0 ingest + translate "
            "stages. Bound under Dapr as app-id 'cds-harness'."
        ),
    )
    fhircast_registry = FHIRcastSessionRegistry()
    app.state.fhircast_registry = fhircast_registry

    @app.exception_handler(IngestError)
    async def _ingest_error_handler(_request: Request, exc: IngestError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"error": "ingest_error", "detail": str(exc)},
        )

    @app.exception_handler(TranslateError)
    async def _translate_error_handler(
        _request: Request, exc: TranslateError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"error": "translate_error", "detail": str(exc)},
        )

    @app.get(HEALTHZ_PATH, response_model=_Healthz)
    async def healthz() -> _Healthz:
        return _Healthz()

    @app.post(INGEST_PATH, response_model=_IngestResponse)
    async def ingest(request: _IngestRequest) -> _IngestResponse:
        try:
            return _ingest(request)
        except IngestError:
            raise
        except Exception as exc:  # pragma: no cover — defensive boundary
            raise HTTPException(status_code=500, detail=f"unexpected: {exc}") from exc

    @app.post(FHIR_NOTIFICATION_PATH, response_model=_IngestResponse)
    async def fhir_notification(
        request: _FHIRNotificationRequest,
    ) -> _IngestResponse:
        try:
            return _fhir_notification(request)
        except IngestError:
            raise
        except Exception as exc:  # pragma: no cover — defensive boundary
            raise HTTPException(status_code=500, detail=f"unexpected: {exc}") from exc

    @app.post(FHIRCAST_PATIENT_OPEN_PATH, response_model=_FHIRcastApplyResponse)
    async def fhircast_patient_open(request: Request) -> _FHIRcastApplyResponse:
        body = await _read_json_object(request)
        try:
            return _fhircast_apply(
                body,
                expected_event=EVENT_PATIENT_OPEN,
                registry=fhircast_registry,
            )
        except IngestError:
            raise
        except Exception as exc:  # pragma: no cover — defensive boundary
            raise HTTPException(status_code=500, detail=f"unexpected: {exc}") from exc

    @app.post(FHIRCAST_PATIENT_CLOSE_PATH, response_model=_FHIRcastApplyResponse)
    async def fhircast_patient_close(request: Request) -> _FHIRcastApplyResponse:
        body = await _read_json_object(request)
        try:
            return _fhircast_apply(
                body,
                expected_event=EVENT_PATIENT_CLOSE,
                registry=fhircast_registry,
            )
        except IngestError:
            raise
        except Exception as exc:  # pragma: no cover — defensive boundary
            raise HTTPException(status_code=500, detail=f"unexpected: {exc}") from exc

    @app.get(FHIRCAST_SESSIONS_PATH, response_model=_FHIRcastSessionsResponse)
    async def fhircast_sessions() -> _FHIRcastSessionsResponse:
        return _FHIRcastSessionsResponse(active=fhircast_registry.active_topics())

    @app.post(TRANSLATE_PATH, response_model=_TranslateResponse)
    async def translate(request: _TranslateRequest) -> _TranslateResponse:
        try:
            return _translate(request)
        except TranslateError:
            raise
        except Exception as exc:  # pragma: no cover — defensive boundary
            raise HTTPException(status_code=500, detail=f"unexpected: {exc}") from exc

    return app


__all__ = [
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "FHIRCAST_PATIENT_CLOSE_PATH",
    "FHIRCAST_PATIENT_OPEN_PATH",
    "FHIRCAST_SESSIONS_PATH",
    "FHIR_NOTIFICATION_PATH",
    "HEALTHZ_PATH",
    "INGEST_PATH",
    "SERVICE_APP_ID",
    "TRANSLATE_PATH",
    "create_app",
]
