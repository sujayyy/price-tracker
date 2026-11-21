// Smoke / baseline: 1 VU walks every endpoint in the mix in turn for 30 s.
// Purpose: prove the target is the seeded perf backend, every endpoint answers 200, and record
// single-user latency per endpoint with no queueing (the floor every later test is compared to).
import { check, sleep } from "k6";
import { MIX, SUMMARY_STATS, discover, endpointThresholds, get } from "./lib.js";

export const options = {
  vus: 1,
  duration: __ENV.DURATION || "30s",
  summaryTrendStats: SUMMARY_STATS,
  thresholds: endpointThresholds({ http_req_failed: ["rate==0"], checks: ["rate==1"] }),
};

export function setup() {
  return discover();
}

export default function ({ ids }) {
  const id = ids[Math.floor(Math.random() * ids.length)];
  for (const m of MIX) {
    const res = get(m.req(id));
    check(res, { "status is 200": (r) => r.status === 200 });
  }
  sleep(0.2);
}
