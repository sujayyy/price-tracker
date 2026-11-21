// Load test: the dashboard's read mix at increasing, then sustained, concurrency.
//
// A VU here is a request loop with 1 s of think time, NOT one person: the real dashboard polls
// every 20–60 s, so one VU generates roughly the traffic of 20–60 open dashboards.
// Stages step 5 → 10 → 25 → 50 VUs and hold each for 60 s, so each level can be read separately
// in the time series (see perf/REPORT.md for the per-stage numbers).
//
// Thresholds are regression tripwires for THIS environment (one laptop, one uvicorn worker, the
// seeded 100-product dataset), not production SLOs. Measured on the final code (REPORT.md §5):
// all requests p95 282 ms and p99 440 ms; the list endpoints p95 238–415 ms; the single-product
// endpoints and /health p95 59–170 ms. The limits allow about 2× that, because repeated runs on this machine vary.
// The code before the fixes (p95 6.4 s, /api/products p95 8.0 s) fails every one of them.
import { sleep } from "k6";
import { SUMMARY_STATS, discover, endpointThresholds, mixed } from "./lib.js";

const LIGHT = ["/api/products/:id", "/api/products/:id/history", "/api/products/:id/decisions", "/health"];
const LISTS = ["/api/products", "/api/proposals", "/api/monitoring"];

export const options = {
  scenarios: {
    load: {
      executor: "ramping-vus",
      startVUs: 0,
      stages: [
        { duration: "20s", target: 5 },
        { duration: "60s", target: 5 },
        { duration: "20s", target: 10 },
        { duration: "60s", target: 10 },
        { duration: "20s", target: 25 },
        { duration: "60s", target: 25 },
        { duration: "20s", target: 50 },
        { duration: "60s", target: 50 },
        { duration: "20s", target: 0 },
      ],
      gracefulRampDown: "30s",
    },
  },
  summaryTrendStats: SUMMARY_STATS,
  thresholds: endpointThresholds({
    http_req_failed: ["rate<0.01"],
    http_req_duration: ["p(95)<1000", "p(99)<1500"],
    ...Object.fromEntries(LISTS.map((n) => [`http_req_duration{name:${n}}`, ["p(95)<1000"]])),
    ...Object.fromEntries(LIGHT.map((n) => [`http_req_duration{name:${n}}`, ["p(95)<300"]])),
  }),
};

export function setup() {
  return discover();
}

export default function ({ ids }) {
  mixed(ids);
  sleep(1);
}
