"""Pure payment rules: no I/O, so they are fast to test and easy to reason about.

Everything that decides *whether* something is allowed lives here. The API
layer only moves data in and out of Postgres.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from enum import Enum


class Status(str, Enum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REFUNDED = "refunded"


# Explicit state machine. Anything not listed is rejected, which also covers
# out-of-order webhooks (e.g. "refunded" arriving before "succeeded").
TRANSITIONS: dict[Status, set[Status]] = {
    Status.PENDING: {Status.SUCCEEDED, Status.FAILED},
    Status.SUCCEEDED: {Status.REFUNDED},
    Status.FAILED: set(),
    Status.REFUNDED: set(),
}

EVENT_TO_STATUS = {
    "payment.succeeded": Status.SUCCEEDED,
    "payment.failed": Status.FAILED,
    "payment.refunded": Status.REFUNDED,
}


def can_transition(current: Status, target: Status) -> bool:
    return target in TRANSITIONS[current]


def request_fingerprint(amount_minor: int, currency: str, customer_id: str) -> str:
    """Hash of the fields that define a payment.

    Stored next to the idempotency key so a client that reuses a key with a
    *different* payload gets an error instead of silently receiving the old
    payment back.
    """
    canonical = json.dumps(
        {"amount_minor": amount_minor, "currency": currency.upper(), "customer_id": customer_id},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def sign(secret: str, body: bytes, timestamp: int | None = None) -> str:
    """Build a signature header: t=<unix>,v1=<hex hmac-sha256 of "t.body">."""
    ts = int(time.time()) if timestamp is None else timestamp
    mac = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={ts},v1={mac}"


class SignatureError(ValueError):
    pass


def verify_signature(secret: str, body: bytes, header: str | None, tolerance_s: int = 300, now: int | None = None) -> None:
    """Raise SignatureError unless the header is a valid, fresh signature of body.

    The timestamp is part of the signed payload, so an attacker can't replay an
    old webhook with a new timestamp. compare_digest avoids timing leaks.
    """
    if not header:
        raise SignatureError("missing signature")
    try:
        parts = dict(item.split("=", 1) for item in header.split(","))
        ts = int(parts["t"])
        received = parts["v1"]
    except (ValueError, KeyError) as exc:
        raise SignatureError("malformed signature") from exc

    current = int(time.time()) if now is None else now
    if abs(current - ts) > tolerance_s:
        raise SignatureError("signature timestamp outside tolerance")

    expected = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received):
        raise SignatureError("signature mismatch")
