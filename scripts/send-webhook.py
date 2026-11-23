#!/usr/bin/env python3
"""Send a signed provider webhook, by hand. Stdlib only.

  kubectl -n payments port-forward svc/payments-api 18080:80 &
  export WEBHOOK_SECRET=$(kubectl -n payments get secret payments-webhook -o jsonpath='{.data.secret}' | base64 -d)
  ./scripts/send-webhook.py <payment_id> payment.succeeded --repeat 3      # redelivery -> 1 applied, 2 duplicate
  ./scripts/send-webhook.py <payment_id> payment.refunded                  # before success -> ignored
  ./scripts/send-webhook.py <payment_id> payment.succeeded --bad-signature # -> 401
"""

import argparse
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.request
import uuid


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("payment_id")
    p.add_argument("type", choices=["payment.succeeded", "payment.failed", "payment.refunded"])
    p.add_argument("--url", default="http://localhost:18080/webhooks/provider")
    p.add_argument("--event-id", default=None)
    p.add_argument("--repeat", type=int, default=1, help="send the same event N times")
    p.add_argument("--bad-signature", action="store_true")
    a = p.parse_args()

    secret = os.environ.get("WEBHOOK_SECRET") or exit("set WEBHOOK_SECRET")
    body = json.dumps({"event_id": a.event_id or f"evt_{uuid.uuid4()}", "type": a.type, "payment_id": a.payment_id}).encode()

    for i in range(a.repeat):
        ts = int(time.time())
        key = "wrong" if a.bad_signature else secret
        sig = hmac.new(key.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
        req = urllib.request.Request(a.url, data=body, method="POST",
                                     headers={"Content-Type": "application/json", "X-Signature": f"t={ts},v1={sig}"})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                print(i + 1, r.status, r.read().decode())
        except urllib.error.HTTPError as e:
            print(i + 1, e.code, e.read().decode())


if __name__ == "__main__":
    main()
