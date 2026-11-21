// Spike test: normal load, a sudden 10× jump, then back to normal for long enough to see whether
// the service recovers (latency back to the pre-spike level, no lingering errors).
//   10 VUs for 60 s → 100 VUs within 5 s, held 60 s → back to 10 VUs within 5 s, held 120 s.
import { sleep } from "k6";
import { SUMMARY_STATS, discover, endpointThresholds, mixed } from "./lib.js";

export const options = {
  scenarios: {
    spike: {
      executor: "ramping-vus",
      startVUs: 10,
      stages: [
        { duration: "60s", target: 10 },
        { duration: "5s", target: 100 },
        { duration: "60s", target: 100 },
        { duration: "5s", target: 10 },
        { duration: "120s", target: 10 },
      ],
      gracefulRampDown: "60s",
    },
  },
  summaryTrendStats: SUMMARY_STATS,
  thresholds: endpointThresholds({ http_req_failed: ["rate<0.01"], http_req_duration: ["p(95)<1500"] }),
};

export function setup() {
  return discover();
}

export default function ({ ids }) {
  mixed(ids);
  sleep(1);
}
