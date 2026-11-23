"""Postgres access: connection pool, schema, and retry for transient failures."""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Awaitable, Callable, TypeVar

import psycopg
from opentelemetry import trace
from psycopg_pool import AsyncConnectionPool, PoolTimeout

from .metrics import DB_ERRORS, DB_RETRIES

log = logging.getLogger("payments.db")
T = TypeVar("T")

SCHEMA = """
CREATE TABLE IF NOT EXISTS payments (
    id               uuid PRIMARY KEY,
    idempotency_key  text        NOT NULL UNIQUE,
    request_hash     text        NOT NULL,
    amount_minor     bigint      NOT NULL CHECK (amount_minor > 0),
    currency         char(3)     NOT NULL,
    customer_id      text        NOT NULL,
    status           text        NOT NULL CHECK (status IN ('pending','succeeded','failed','refunded')),
    provider_ref     text,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now()
);

-- One row per provider event. The primary key is what makes webhook
-- processing idempotent: a redelivered event can never be applied twice.
CREATE TABLE IF NOT EXISTS webhook_events (
    event_id     text PRIMARY KEY,
    payment_id   uuid NOT NULL REFERENCES payments(id),
    type         text NOT NULL,
    outcome      text NOT NULL,
    received_at  timestamptz NOT NULL DEFAULT now()
);

-- Append-only audit trail of every status change.
CREATE TABLE IF NOT EXISTS payment_transitions (
    id           bigserial PRIMARY KEY,
    payment_id   uuid NOT NULL REFERENCES payments(id),
    from_status  text NOT NULL,
    to_status    text NOT NULL,
    event_id     text NOT NULL REFERENCES webhook_events(event_id),
    at           timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS payment_transitions_payment_id ON payment_transitions(payment_id);
"""

# Postgres SQLSTATE classes that are worth retrying: connection problems,
# failover ("cannot execute in a read-only transaction" while a replica is
# being promoted), serialization conflicts and deadlocks.
RETRYABLE_SQLSTATES = {"08000", "08003", "08006", "08001", "08004", "57P01", "57P02", "57P03", "25006", "40001", "40P01"}

TRANSIENT = (psycopg.OperationalError, PoolTimeout)


def is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, TRANSIENT):
        return True
    return isinstance(exc, psycopg.Error) and getattr(exc, "sqlstate", None) in RETRYABLE_SQLSTATES


async def with_retry(fn: Callable[[], Awaitable[T]], attempts: int = 6, base_delay: float = 0.1, max_delay: float = 3.0) -> T:
    """Run fn, retrying transient DB errors with exponential backoff + jitter.

    Retrying a whole transaction is only safe because every write in this
    service is idempotent (unique idempotency key, unique webhook event id).
    If a commit succeeded but the connection dropped before we saw it, the
    retry finds the existing row instead of creating a second one.
    """
    for attempt in range(1, attempts + 1):
        try:
            return await fn()
        except Exception as exc:  # noqa: BLE001 - filtered below
            if not is_retryable(exc) or attempt == attempts:
                DB_ERRORS.labels(type(exc).__name__).inc()
                raise
            DB_RETRIES.inc()
            delay = min(max_delay, base_delay * 2 ** (attempt - 1)) + random.uniform(0, base_delay)
            # Shows up on the request's trace: during a failover you can see
            # exactly how many retries one request needed and how long each took.
            trace.get_current_span().add_event(
                "db.retry",
                {"attempt": attempt, "error.type": type(exc).__name__, "delay_s": round(delay, 3)},
            )
            log.warning("transient db error (attempt %d/%d): %s; retrying in %.2fs", attempt, attempts, exc, delay)
            await asyncio.sleep(delay)
    raise RuntimeError("unreachable")


def make_pool(dsn: str, min_size: int, max_size: int) -> AsyncConnectionPool:
    # check_connection runs before a connection is handed out, so after a
    # failover the pool discards connections to the old primary instead of
    # failing the next request on them.
    return AsyncConnectionPool(
        conninfo=dsn,
        min_size=min_size,
        max_size=max_size,
        timeout=5.0,
        max_lifetime=600,
        open=False,
        check=AsyncConnectionPool.check_connection,
        kwargs={"connect_timeout": 3, "application_name": "payments-api"},
    )


async def init_schema(pool: AsyncConnectionPool) -> None:
    async def _run():
        async with pool.connection() as conn:
            # Advisory lock so several replicas starting together don't race on DDL.
            await conn.execute("SELECT pg_advisory_lock(42)")
            try:
                await conn.execute(SCHEMA)
            finally:
                await conn.execute("SELECT pg_advisory_unlock(42)")

    await with_retry(_run, attempts=20, base_delay=0.5)
