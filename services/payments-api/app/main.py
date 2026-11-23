"""payments-api: idempotent payment creation and webhook processing.

Reliability properties this service is built to keep, even under retries,
pod kills and database failover:
  1. One Idempotency-Key  -> at most one payment.
  2. One provider event   -> applied at most once.
  3. Status only moves along the state machine in domain.py.
  4. Every status change has an audit row, in the same transaction.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import time
import uuid
from contextlib import asynccontextmanager
from typing import Literal, Optional

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from psycopg.rows import dict_row
from pydantic import BaseModel, Field

from . import db
from .telemetry import current_trace_id, setup_tracing, tracer
from .domain import EVENT_TO_STATUS, SignatureError, Status, can_transition, request_fingerprint, verify_signature
from .metrics import (
    BUILD_INFO,
    IDEMPOTENCY_MISMATCH,
    IDEMPOTENT_REPLAYS,
    LATENCY,
    PAYMENTS_CREATED,
    REQUESTS,
    WEBHOOKS,
)

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("payments")

VERSION = os.getenv("APP_VERSION", "dev")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://payments:payments@localhost:5432/payments")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")
# Simulates a bad release so canary analysis has something to catch.
RELEASE_FAULT_RATE = float(os.getenv("RELEASE_FAULT_RATE", "0"))
RELEASE_EXTRA_LATENCY_MS = int(os.getenv("RELEASE_EXTRA_LATENCY_MS", "0"))

BUILD_INFO.labels(VERSION).set(1)


class AppState:
    pool = None
    ready = False


state = AppState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    state.pool = db.make_pool(DATABASE_URL, int(os.getenv("DB_POOL_MIN", "2")), int(os.getenv("DB_POOL_MAX", "10")))
    await state.pool.open(wait=False)
    await db.init_schema(state.pool)
    state.ready = True
    log.info("payments-api %s ready", VERSION)
    yield
    state.ready = False
    await state.pool.close()


app = FastAPI(title="payments-api", version=VERSION, lifespan=lifespan)
UNMETERED = {"/metrics", "/healthz", "/readyz"}


@app.middleware("http")
async def observe(request: Request, call_next):
    if request.url.path in UNMETERED:
        return await call_next(request)
    start = time.perf_counter()
    status = 500
    try:
        if RELEASE_EXTRA_LATENCY_MS:
            await asyncio.sleep(RELEASE_EXTRA_LATENCY_MS / 1000)
        if RELEASE_FAULT_RATE and random.random() < RELEASE_FAULT_RATE:
            response: Response = JSONResponse({"error": "simulated regression"}, status_code=500)
        else:
            response = await call_next(request)
        status = response.status_code
        trace_id = current_trace_id()
        if trace_id:
            # Lets a client or support engineer jump straight to the trace in Grafana.
            response.headers["X-Trace-Id"] = trace_id
        return response
    finally:
        route = getattr(request.scope.get("route"), "path", "unmatched")
        REQUESTS.labels(request.method, route, str(status)).inc()
        LATENCY.labels(request.method, route).observe(time.perf_counter() - start)


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    if db.is_retryable(exc):
        # Retries were exhausted (e.g. a long failover). 503 + Retry-After tells
        # the client this is safe to retry with the same Idempotency-Key.
        return JSONResponse(
            {"error": "database temporarily unavailable", "trace_id": current_trace_id()},
            status_code=503,
            headers={"Retry-After": "2"},
        )
    log.exception("unhandled error trace_id=%s", current_trace_id())
    return JSONResponse({"error": "internal error", "trace_id": current_trace_id()}, status_code=500)


# ---------- probes ----------

@app.get("/healthz")
async def healthz():
    """Liveness. Deliberately ignores the database: a DB failover must not make
    Kubernetes restart every app pod (see docs/adr/0004-probes-and-db.md)."""
    return {"status": "ok"}


@app.get("/readyz")
async def readyz():
    if not state.ready:
        return JSONResponse({"status": "starting"}, status_code=503)
    return {"status": "ready", "version": VERSION}


@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


# ---------- payments ----------

class PaymentIn(BaseModel):
    amount_minor: int = Field(..., gt=0, le=100_000_000, description="Amount in the smallest unit, e.g. paise")
    currency: str = Field(..., min_length=3, max_length=3)
    customer_id: str = Field(..., min_length=1, max_length=64)


INSERT_PAYMENT = """
INSERT INTO payments (id, idempotency_key, request_hash, amount_minor, currency, customer_id, status)
VALUES (%(id)s, %(key)s, %(hash)s, %(amount)s, %(currency)s, %(customer)s, 'pending')
ON CONFLICT (idempotency_key) DO NOTHING
RETURNING *
"""


def serialize(row: dict) -> dict:
    out = dict(row)
    out["id"] = str(out["id"])
    out.pop("request_hash", None)
    for k in ("created_at", "updated_at"):
        if out.get(k) is not None:
            out[k] = out[k].isoformat()
    return out


@app.post("/payments", status_code=201)
async def create_payment(body: PaymentIn, response: Response, idempotency_key: Optional[str] = Header(default=None)):
    if not idempotency_key or len(idempotency_key) > 128:
        raise HTTPException(400, "Idempotency-Key header is required (max 128 chars)")

    currency = body.currency.upper()
    fingerprint = request_fingerprint(body.amount_minor, currency, body.customer_id)
    params = {
        "id": uuid.uuid4(),
        "key": idempotency_key,
        "hash": fingerprint,
        "amount": body.amount_minor,
        "currency": currency,
        "customer": body.customer_id,
    }

    async def txn():
        async with state.pool.connection() as conn:
            async with conn.transaction():
                cur = conn.cursor(row_factory=dict_row)
                await cur.execute(INSERT_PAYMENT, params)
                row = await cur.fetchone()
                if row:
                    return row, True
                # Key already used: return the original payment. ON CONFLICT
                # makes this race-free even with many concurrent identical requests.
                await cur.execute("SELECT * FROM payments WHERE idempotency_key = %s", (idempotency_key,))
                return await cur.fetchone(), False

    with tracer.start_as_current_span("payment.create") as span:
        span.set_attribute("payment.currency", currency)
        span.set_attribute("payment.amount_minor", body.amount_minor)
        row, created = await db.with_retry(txn)
        span.set_attribute("payment.id", str(row["id"]))
        span.set_attribute("payment.idempotent_replay", not created)

    if created:
        PAYMENTS_CREATED.labels(currency).inc()
        return serialize(row)

    if row["request_hash"] != fingerprint:
        IDEMPOTENCY_MISMATCH.inc()
        raise HTTPException(422, "Idempotency-Key was already used with a different request body")

    IDEMPOTENT_REPLAYS.inc()
    response.status_code = 200
    response.headers["Idempotent-Replayed"] = "true"
    return serialize(row)


@app.get("/payments/{payment_id}")
async def get_payment(payment_id: uuid.UUID):
    async def q():
        async with state.pool.connection() as conn:
            cur = conn.cursor(row_factory=dict_row)
            await cur.execute("SELECT * FROM payments WHERE id = %s", (payment_id,))
            return await cur.fetchone()

    row = await db.with_retry(q)
    if not row:
        raise HTTPException(404, "payment not found")
    return serialize(row)


# ---------- webhooks ----------

class WebhookEvent(BaseModel):
    event_id: str = Field(..., min_length=1, max_length=128)
    type: Literal["payment.succeeded", "payment.failed", "payment.refunded"]
    payment_id: uuid.UUID
    provider_ref: Optional[str] = Field(default=None, max_length=128)


@app.post("/webhooks/provider")
async def provider_webhook(request: Request, x_signature: Optional[str] = Header(default=None)):
    raw = await request.body()
    try:
        verify_signature(WEBHOOK_SECRET, raw, x_signature)
    except SignatureError as exc:
        WEBHOOKS.labels("unknown", "invalid_signature").inc()
        raise HTTPException(401, str(exc)) from exc

    event = WebhookEvent.model_validate_json(raw)
    target = EVENT_TO_STATUS[event.type]

    async def txn():
        async with state.pool.connection() as conn:
            async with conn.transaction():
                cur = conn.cursor(row_factory=dict_row)
                # Lock the payment row so two different events for the same
                # payment are applied one after the other, never interleaved.
                await cur.execute("SELECT status FROM payments WHERE id = %s FOR UPDATE", (event.payment_id,))
                payment = await cur.fetchone()
                if payment is None:
                    return "unknown_payment"

                current = Status(payment["status"])
                outcome = "applied" if can_transition(current, target) else "ignored"

                await cur.execute(
                    "INSERT INTO webhook_events (event_id, payment_id, type, outcome) VALUES (%s, %s, %s, %s) "
                    "ON CONFLICT (event_id) DO NOTHING RETURNING event_id",
                    (event.event_id, event.payment_id, event.type, outcome),
                )
                if await cur.fetchone() is None:
                    return "duplicate"

                if outcome == "applied":
                    await cur.execute(
                        "UPDATE payments SET status = %s, provider_ref = COALESCE(%s, provider_ref), updated_at = now() WHERE id = %s",
                        (target.value, event.provider_ref, event.payment_id),
                    )
                    await cur.execute(
                        "INSERT INTO payment_transitions (payment_id, from_status, to_status, event_id) VALUES (%s, %s, %s, %s)",
                        (event.payment_id, current.value, target.value, event.event_id),
                    )
                return outcome

    with tracer.start_as_current_span("webhook.process") as span:
        span.set_attribute("webhook.event_id", event.event_id)
        span.set_attribute("webhook.type", event.type)
        span.set_attribute("payment.id", str(event.payment_id))
        outcome = await db.with_retry(txn)
        span.set_attribute("webhook.outcome", outcome)
    WEBHOOKS.labels(event.type, outcome).inc()

    if outcome == "unknown_payment":
        # 404 makes the provider retry later, which covers the case where the
        # webhook arrives before our own create-payment commit is visible.
        raise HTTPException(404, "unknown payment")
    # Duplicates and invalid transitions return 200 on purpose: the event was
    # handled, and a non-2xx would make the provider retry it forever.
    return {"event_id": event.event_id, "outcome": outcome}


# Instrument last so the OpenTelemetry middleware wraps everything above,
# including our own middleware (which reads the trace id for X-Trace-Id).
setup_tracing(app, VERSION)
