// Approval race over HTTP. For each of PROPOSALS seeded pending proposals, CLICKS reviewers press
// Approve at the same instant (http.batch sends them in parallel), with VUS proposals raced at a
// time. Exactly one click may win (200); the rest must be refused (409); the audit log must show at
// most one price change for the proposal (exactly one if the winner's outcome was "approved").
// This approves seeded proposals in tracker_perf, so re-seed (perf/run.sh seed) before re-running.
import http from "k6/http";
import { check, fail } from "k6";
import exec from "k6/execution";
import { Counter } from "k6/metrics";
import { BASE_URL, SUMMARY_STATS, get, guard } from "./lib.js";

const CLICKS = Number(__ENV.CLICKS || 10);
const PROPOSALS = Number(__ENV.PROPOSALS || 20);
const NAME = "/api/proposals/:id/approve";

const winners = new Counter("approval_winners");
const conflicts = new Counter("approval_conflicts");
const unexpected = new Counter("approval_unexpected_status");
const doubleApplied = new Counter("approval_double_applied");

export const options = {
  batchPerHost: CLICKS,
  scenarios: {
    race: { executor: "shared-iterations", vus: Number(__ENV.VUS || 4), iterations: PROPOSALS, maxDuration: "5m" },
  },
  summaryTrendStats: SUMMARY_STATS,
  thresholds: {
    approval_unexpected_status: ["count==0"],
    approval_double_applied: ["count==0"],
    checks: ["rate==1"],
    [`http_req_duration{name:${NAME}}`]: ["max>=0"],
    [`http_req_duration{name:${NAME},status:200}`]: ["max>=0"],
    [`http_req_duration{name:${NAME},status:409}`]: ["max>=0"],
  },
};

export function setup() {
  const r = get("/api/proposals?status=pending");
  if (r.status !== 200) fail(`GET /api/proposals returned ${r.status}`);
  const pending = r.json().map((p) => ({ id: p.id, product_id: p.product_id }));
  if (pending.length < PROPOSALS) fail(`Need ${PROPOSALS} pending proposals, found ${pending.length}: run perf/run.sh seed`);
  return { pending: pending.slice(0, PROPOSALS) };
}

export default function ({ pending }) {
  const p = pending[exec.scenario.iterationInTest];
  const path = `/api/proposals/${p.id}/approve`;
  guard(path);
  const clicks = Array.from({ length: CLICKS }, (_, i) => ({
    method: "POST",
    url: `${BASE_URL}${path}`,
    body: JSON.stringify({ by: `perf-reviewer-${i}`, note: "perf race test" }),
    // 409 is the expected answer for every click but one, so it doesn't count as a failed request.
    params: {
      headers: { "Content-Type": "application/json" },
      tags: { name: NAME },
      responseCallback: http.expectedStatuses(200, 409),
    },
  }));
  const res = http.batch(clicks);
  const won = res.filter((r) => r.status === 200);
  const refused = res.filter((r) => r.status === 409).length;
  winners.add(won.length);
  conflicts.add(refused);
  unexpected.add(CLICKS - won.length - refused);

  const audit = get(`/api/products/${p.product_id}/our-price-history`).json().filter((c) => c.proposal_id === p.id);
  const outcome = won.length === 1 ? won[0].json() : null;
  const expected = outcome && outcome.status === "approved" && outcome.final_price_inr !== null ? 1 : 0;
  if (audit.length > 1) doubleApplied.add(audit.length - 1);
  check(null, {
    "exactly one click wins": () => won.length === 1,
    "every other click gets 409": () => refused === CLICKS - 1,
    "audit log has one change per approval": () => audit.length === expected,
  });
}
