// Realistic-ish traffic: clients that retry with the same Idempotency-Key,
// and a "provider" that sends signed webhooks, sometimes twice.
import http from 'k6/http';
import crypto from 'k6/crypto';
import { check, sleep } from 'k6';

const BASE = __ENV.BASE_URL || 'http://payments-api';
const SECRET = __ENV.WEBHOOK_SECRET;

export const options = {
  scenarios: {
    steady: { executor: 'constant-arrival-rate', rate: 10, timeUnit: '1s', duration: '720h', preAllocatedVUs: 20, maxVUs: 50 },
  },
};

function uuid() {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
  });
}

function webhook(paymentId, type, eventId) {
  const body = JSON.stringify({ event_id: eventId, type, payment_id: paymentId, provider_ref: `pr_${eventId}` });
  const t = Math.floor(Date.now() / 1000);
  const sig = crypto.hmac('sha256', SECRET, `${t}.${body}`, 'hex');
  return http.post(`${BASE}/webhooks/provider`, body, {
    headers: { 'Content-Type': 'application/json', 'X-Signature': `t=${t},v1=${sig}` },
    tags: { name: 'webhook' },
  });
}

export default function () {
  const key = uuid();
  const payload = JSON.stringify({ amount_minor: 100 + Math.floor(Math.random() * 99900), currency: 'INR', customer_id: `cust_${Math.floor(Math.random() * 500)}` });
  const params = { headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key }, tags: { name: 'create' } };

  let res = http.post(`${BASE}/payments`, payload, params);
  // 10% of clients "time out" and retry with the same key; 5xx always retried.
  if (res.status >= 500 || Math.random() < 0.1) {
    sleep(0.2);
    res = http.post(`${BASE}/payments`, payload, params);
  }
  if (!check(res, { 'payment created or replayed': (r) => r.status === 201 || r.status === 200 })) return;

  const id = res.json('id');
  const eventId = `evt_${uuid()}`;
  const type = Math.random() < 0.9 ? 'payment.succeeded' : 'payment.failed';
  webhook(id, type, eventId);
  if (Math.random() < 0.15) webhook(id, type, eventId);                   // provider redelivery
  if (type === 'payment.succeeded' && Math.random() < 0.05) webhook(id, 'payment.refunded', `evt_${uuid()}`);
}
