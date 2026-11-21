// Shared k6 helpers: the target, a safety allow-list, the dashboard's request mix, and summaries.
import http from "k6/http";
import { check, fail } from "k6";

export const BASE_URL = __ENV.BASE_URL || "http://localhost:8100";

// The perf backend runs on :8100 against tracker_perf. Refuse the dev backend (:8000) unless asked.
if (/:8000\b/.test(BASE_URL) && __ENV.ALLOW_DEV !== "1") {
  fail(`Refusing to load-test ${BASE_URL} (the dev backend). Use the perf backend (perf/run.sh serve).`);
}

// Only these paths may be called. They read the database only (no scraping, no model calls, no
// email). The approval endpoint is allowed for the race test, against seeded proposals only.
const ALLOWED = [
  /^\/health$/,
  /^\/api\/products(\/\d+)?$/,
  /^\/api\/products\/\d+\/(history|decisions|our-price-history|proposals)$/,
  /^\/api\/proposals$/,
  /^\/api\/proposals\/\d+\/approve$/,
  /^\/api\/activity$/,
  /^\/api\/monitoring$/,
];

export function guard(path) {
  const p = path.split("?")[0];
  if (!ALLOWED.some((re) => re.test(p))) fail(`Path not on the perf allow-list: ${path}`);
}

export function get(path, name) {
  guard(path);
  return http.get(`${BASE_URL}${path}`, { tags: { name: name || path.split("?")[0].replace(/\/\d+/g, "/:id") } });
}

export function post(path, body, name) {
  guard(path);
  return http.post(`${BASE_URL}${path}`, JSON.stringify(body), {
    headers: { "Content-Type": "application/json" },
    tags: { name: name || path.replace(/\/\d+/g, "/:id") },
  });
}

/** Called once per test: discover real product ids so requests use existing rows. */
export function discover() {
  const r = http.get(`${BASE_URL}/api/products`);
  if (r.status !== 200) fail(`GET /api/products returned ${r.status}; is the perf backend running and seeded?`);
  const ids = r.json().map((p) => p.id);
  if (!ids.length) fail("No products in the perf database; run perf/run.sh seed first.");
  return { ids };
}

// What one dashboard "user loop" requests, weighted by how often the UI polls each endpoint:
// the Overview (products + proposals + activity every 30 s), the pending badge (every 20 s),
// monitoring / the market tape (every 60 s), and opening a product page (detail + chart + feeds).
export const MIX = [
  { w: 20, req: () => "/api/products" },
  { w: 25, req: () => "/api/proposals?status=pending" },
  { w: 10, req: () => "/api/activity?days=14" },
  { w: 8, req: () => "/api/monitoring" },
  { w: 12, req: (id) => `/api/products/${id}` },
  { w: 12, req: (id) => `/api/products/${id}/history?days=7` },
  { w: 5, req: (id) => `/api/products/${id}/decisions` },
  { w: 3, req: (id) => `/api/products/${id}/our-price-history` },
  { w: 5, req: () => "/health" },
];
const TOTAL = MIX.reduce((n, m) => n + m.w, 0);

/** One weighted request from the mix. */
export function mixed(ids) {
  let r = Math.random() * TOTAL;
  const id = ids[Math.floor(Math.random() * ids.length)];
  for (const m of MIX) {
    if ((r -= m.w) <= 0) {
      const res = get(m.req(id));
      check(res, { "status is 200": (x) => x.status === 200 });
      return res;
    }
  }
}

/** Per-endpoint latency submetrics. k6 only reports a tagged submetric if a threshold names it, so
 *  each endpoint gets an always-true threshold; `extra` adds the real pass/fail thresholds. */
export function endpointThresholds(extra = {}) {
  const out = { ...extra };
  for (const m of MIX) {
    const name = m.req(1).split("?")[0].replace(/\/\d+/g, "/:id");
    out[`http_req_duration{name:${name}}`] = out[`http_req_duration{name:${name}}`] || ["max>=0"];
  }
  return out;
}

// Report the percentiles we care about (k6's default omits p50 and p99).
export const SUMMARY_STATS = ["avg", "min", "med", "p(90)", "p(95)", "p(99)", "max", "count"];
