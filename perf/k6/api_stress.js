// Stress test: keep adding concurrency past the load test until the service degrades, to find
// where p95 climbs, errors appear and throughput stops growing. Same mix and think time as the
// load test, so the two are comparable; steps 10 → 25 → 50 → 100 → 150 VUs, 45 s each.
import { sleep } from "k6";
import { SUMMARY_STATS, discover, endpointThresholds, mixed } from "./lib.js";

export const options = {
  scenarios: {
    stress: {
      executor: "ramping-vus",
      startVUs: 0,
      stages: [
        { duration: "15s", target: 10 },
        { duration: "45s", target: 10 },
        { duration: "15s", target: 25 },
        { duration: "45s", target: 25 },
        { duration: "15s", target: 50 },
        { duration: "45s", target: 50 },
        { duration: "15s", target: 100 },
        { duration: "45s", target: 100 },
        { duration: "15s", target: 150 },
        { duration: "45s", target: 150 },
        { duration: "20s", target: 0 },
      ],
      gracefulRampDown: "60s",
    },
  },
  summaryTrendStats: SUMMARY_STATS,
  // Recorded, not gating: a stress test is expected to cross them.
  thresholds: endpointThresholds({ http_req_failed: ["rate<0.01"], http_req_duration: ["p(95)<1500"] }),
};

export function setup() {
  return discover();
}

export default function ({ ids }) {
  mixed(ids);
  sleep(1);
}
