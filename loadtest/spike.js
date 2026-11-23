// Local spike test (run from your machine with a port-forward):
//   kubectl -n payments port-forward svc/payments-api 18080:80
//   k6 run loadtest/spike.js
// Finds where latency breaks, which tells you whether 4 replicas and a pool of
// 10 connections per pod are the right numbers.
import http from 'k6/http';
import { check } from 'k6';

const BASE = __ENV.BASE_URL || 'http://localhost:18080';

export const options = {
  stages: [
    { duration: '1m', target: 20 },
    { duration: '30s', target: 200 },
    { duration: '2m', target: 200 },
    { duration: '30s', target: 20 },
    { duration: '1m', target: 20 },
  ],
  thresholds: {
    http_req_failed: ['rate<0.001'],
    'http_req_duration{name:create}': ['p(95)<300'],
  },
};

export default function () {
  const key = `${__VU}-${__ITER}-${Date.now()}`;
  const res = http.post(`${BASE}/payments`,
    JSON.stringify({ amount_minor: 1000, currency: 'INR', customer_id: `cust_${__VU}` }),
    { headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key }, tags: { name: 'create' } });
  check(res, { created: (r) => r.status === 201 });
}
