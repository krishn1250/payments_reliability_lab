"""End-to-end tests against a real Postgres. CI provides one as a service
container; locally: docker run -e POSTGRES_PASSWORD=payments -e POSTGRES_USER=payments
-e POSTGRES_DB=payments -p 5432:5432 postgres:16 and set DATABASE_URL."""

import concurrent.futures
import json
import os
import uuid

import pytest

if not os.getenv("DATABASE_URL"):
    pytest.skip("DATABASE_URL not set; integration tests need Postgres", allow_module_level=True)

os.environ.setdefault("WEBHOOK_SECRET", "whsec_test")

from fastapi.testclient import TestClient  # noqa: E402

from app.domain import sign  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def new_payment(client, key=None, amount=1000):
    key = key or str(uuid.uuid4())
    return client.post(
        "/payments",
        json={"amount_minor": amount, "currency": "INR", "customer_id": "cust_1"},
        headers={"Idempotency-Key": key},
    )


def send_event(client, payment_id, event_type, event_id=None):
    body = json.dumps({"event_id": event_id or f"evt_{uuid.uuid4()}", "type": event_type, "payment_id": payment_id}).encode()
    return client.post("/webhooks/provider", content=body, headers={"X-Signature": sign("whsec_test", body), "Content-Type": "application/json"})


def test_missing_key_rejected(client):
    assert client.post("/payments", json={"amount_minor": 1, "currency": "INR", "customer_id": "c"}).status_code == 400


def test_same_key_returns_same_payment(client):
    key = str(uuid.uuid4())
    first, second = new_payment(client, key), new_payment(client, key)
    assert first.status_code == 201 and second.status_code == 200
    assert second.headers["Idempotent-Replayed"] == "true"
    assert first.json()["id"] == second.json()["id"]


def test_same_key_different_body_rejected(client):
    key = str(uuid.uuid4())
    new_payment(client, key, amount=1000)
    assert new_payment(client, key, amount=2000).status_code == 422


def test_concurrent_requests_create_one_payment(client):
    key = str(uuid.uuid4())
    with concurrent.futures.ThreadPoolExecutor(20) as pool:
        results = list(pool.map(lambda _: new_payment(client, key), range(40)))
    ids = {r.json()["id"] for r in results}
    assert len(ids) == 1
    assert sum(r.status_code == 201 for r in results) == 1


def test_webhook_applied_once(client):
    pid = new_payment(client).json()["id"]
    evt = f"evt_{uuid.uuid4()}"
    assert send_event(client, pid, "payment.succeeded", evt).json()["outcome"] == "applied"
    assert send_event(client, pid, "payment.succeeded", evt).json()["outcome"] == "duplicate"
    assert client.get(f"/payments/{pid}").json()["status"] == "succeeded"


def test_out_of_order_refund_ignored(client):
    pid = new_payment(client).json()["id"]
    assert send_event(client, pid, "payment.refunded").json()["outcome"] == "ignored"
    assert client.get(f"/payments/{pid}").json()["status"] == "pending"


def test_bad_signature_rejected(client):
    body = b'{"event_id":"x","type":"payment.failed","payment_id":"00000000-0000-0000-0000-000000000000"}'
    r = client.post("/webhooks/provider", content=body, headers={"X-Signature": sign("wrong", body)})
    assert r.status_code == 401
