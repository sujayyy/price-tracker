// Soak test: modest, steady load for a long time (default 30 min) to catch slow problems that a
// short test can't: latency drift, rising errors, memory growth, leaked DB connections.
// Run perf/harness/sampler.py alongside to record server RSS, CPU and Postgres connections.
import { sleep } from "k6";
import { SUMMARY_STATS, discover, endpointThresholds, mixed } from "./lib.js";

export const options = {
  scenarios: {
    soak: {
      executor: "constant-vus",
      vus: Number(__ENV.VUS || 10),
      duration: __ENV.DURATION || "30m",
    },
  },
  summaryTrendStats: SUMMARY_STATS,
  // Same tripwires as the load test (see api_load.js); the soak's real output is the drift over time.
  thresholds: endpointThresholds({ http_req_failed: ["rate<0.01"], http_req_duration: ["p(95)<1000", "p(99)<1500"] }),
};

export function setup() {
  return discover();
}

export default function ({ ids }) {
  mixed(ids);
  sleep(1);
}
