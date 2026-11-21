# Performance report: Price Tracker backend

All numbers below were measured on one laptop between 20:00 and 23:00 IST on 1 Oct 2026. Every
figure comes from a file in `perf/results/`, and where a number could not be measured, the report
says so. These are results for **this workload on this machine**. They are not production capacity
claims.

## Summary

- **Baseline.** With one user, the product list (`GET /api/products`) took 724 ms median and 1.4 s
  at p95. Under a 5 → 50 user load test, p95 for all requests was 6.4 s. On this workload and
  machine, degradation began between 10 and 25 virtual users: throughput stopped growing at about
  9–10 req/s.
- **Bottleneck 1: N+1 queries.** One `/api/products` call ran **1,802 SQL statements**. The list
  endpoints read each listing's history one listing at a time. Batching those reads brought it to
  **8 statements**. All 204 checked API responses are byte-for-byte identical before and after.
- **Bottleneck 2: a deadlock under load.** At 100+ users the server deadlocked. All 40 worker threads
  waited for a database connection, while all 15 connections belonged to requests waiting for a
  worker thread. Completions stopped for 20–30 s at a time, requests failed (up to 13.5%), and k6
  hit its 60 s timeouts. The fix is a small admission limit: at most 10 `/api` requests run at once,
  and the rest wait cheaply.
- **After both fixes.** The same load test gives p95 **282 ms** (from 6.4 s) with 0 errors. The
  stress test reaches 150 users with **0 errors in 11,068 requests** (from 13.5% errors). The spike
  test has 0 errors (from 9%) and is back to normal within 10 s of the spike ending. On this
  workload and machine, degradation now begins around **50–100 virtual users**: one CPU-bound
  worker levels off at about 49–50 req/s. An experiment with 4 workers reached 109 req/s at 150
  users.
- **Approvals.** 10 simultaneous clicks on one proposal apply the price exactly once, every time:
  in pytest and over HTTP (20 proposals × 10 clicks). With the row lock removed, the same test
  applied the price 10 times out of 10.
- **Soak.** 30 minutes at 10 users: 17,102 requests, 0 errors, p95 flat at 130–134 ms, and memory
  level at about 190 MB.
- **AI.** The application's own share of an AI decision is about 11–15 ms. A real Claude Haiku 4.5
  decision took 5.2 s p50 and 7.2 s p95 (n = 20), almost all of it inside the provider calls.

---

## 1. Objective

The backend serves an ops dashboard that polls several list endpoints. It also runs a scheduler
that scrapes competitors and asks an LLM for repricing decisions, with a human approval step. The
goals were:
- know how fast the dashboard API is and where it stops scaling;
- find and fix what limits it, with evidence;
- prove the approval path cannot apply a price twice under concurrent clicks;
- know what an AI decision costs in time and money;
- do all of this **without touching Amazon, Flipkart, the model API (beyond 20 deliberate calls),
  email, or the development database**.

## 2. Test environment

| | |
|---|---|
| Machine | Apple M5 Pro, 18 cores (performance and efficiency cores), 24 GB RAM, macOS 27.0 |
| Background load | a normal desktop session: browsers and editor, load average ≈ 3 |
| Python / Node | Python 3.12.10 · Node v22.17.1 (not used by the tests) |
| Backend | FastAPI 0.141.1 · Starlette 1.7.0 · uvicorn 0.54.0, **1 worker** (the same as `backend/Dockerfile`) · SQLAlchemy 2.1.1 · psycopg 3.3.6 · pydantic 2.13.5 · LangGraph 1.2.12 · langchain-core 1.6.5 |
| Concurrency limits | anyio worker-thread pool: 40 threads (Starlette runs sync endpoints there) · SQLAlchemy QueuePool: 5 + 10 overflow = 15 connections, 30 s checkout timeout |
| Database | PostgreSQL 16.15 in Docker 29.6.1 (VM: 18 CPUs, 7.7 GB), `max_connections` 100, `shared_buffers` 128 MB |
| Load generator | k6 v2.3.0, on the same machine |
| Dataset | `tracker_perf`: 100 products, 200 listings (Amazon.in + Flipkart), 12,200 price readings (60 per listing, 12 h apart), 40 AI decisions, 40 proposals (30 pending), 105 price changes. The database is 11 MB, so it sits entirely in Postgres's cache. |
| Network | everything on localhost, except the real-model AI benchmark (§10) |

**Variance on this machine.** In repeated runs of the same micro-benchmark, timings varied up to 2–3×
from one run to the next. The likely cause is the OS moving the process between performance and
efficiency cores, alongside the desktop load. The HTTP tests run for minutes, which averages much of
this out. Small differences, roughly under 15–20%, should be treated as noise.

## 3. Test methodology

**Isolation.** See [README.md](README.md) for the full table. The perf backend runs on port 8100
against its own database (`tracker_perf`). `perf/harness/env.py` refuses the dev and test databases.
It blanks the email settings, switches off LangSmith, and replaces the model API keys with a dummy
value, so a stray model call fails instead of being billed. The k6 scripts refuse the dev port and
only allow an explicit list of paths.

**Data.** `perf/harness/seed.py` builds the dataset from a fixed random seed (prices follow a
random walk). It then creates decisions and proposals through the **real** scheduler cycle
(`run_once`) and the real LangGraph workflow, with a deterministic stand-in model (`fake_model.py`)
and a fake fetcher. It was re-seeded twice (before the second before-run and before the soak). The
counts were identical each time.

**Workload.** Each k6 virtual user (VU) loops: draw one request from the dashboard mix, then wait
1 s. The mix is weighted by how often the dashboard polls each endpoint:

| Weight | Request |
|---:|---|
| 25% | pending proposals |
| 20% | product list |
| 12% | product detail |
| 12% | 7-day history |
| 10% | activity |
| 8% | monitoring |
| 5% | decisions |
| 5% | health |
| 3% | price audit |

Everything is read-only except the approval test. One VU sends about a request per second, which is
far busier than a person: a dashboard polls every 20–60 s.

**Tests.** All scripts are in `perf/k6/`:

| Test | Shape | Duration |
|---|---|---|
| smoke | 1 VU walks every endpoint | 30 s |
| load | 5 → 10 → 25 → 50 VUs, each step held 60 s | 6 min |
| stress | 10 → 25 → 50 → 100 → 150 VUs, each step held 45 s | 6.5 min |
| spike | 10 VUs → 100 VUs within 5 s, held 60 s → back to 10 | 4 min |
| soak | 10 VUs | 30 min |
| approval | 10 simultaneous approve clicks on each of 20 proposals | under 1 min |

**Measurements.**
- k6 records every request (`--out json`).
- `summarize.py` reports p50, p90, p95, p99 and max per endpoint.
- `timeline.py` reports per 10 s windows and per steady VU level, plus the HTTP status distribution.
- `sampler.py` reads the server's CPU, RSS and thread count every 2 s, plus its Postgres
  connections by state.
- `query_profile.py` counts SQL statements and time inside Postgres per endpoint (SQLAlchemy
  events), plus cProfile.

**Before and after comparisons.**
- Each change was measured with the same script, the same dataset shape and the same
  configuration. The server was restarted before each stress and spike run.
- The "before" code was served from a copy of `backend/` with the changes reverted
  (`PERF_BACKEND=…`). The changes themselves are in `perf/optimizations/*.patch`.
- `parity.py` captured 204 API responses (every product, its proposals, the queue, monitoring) from
  the old and the new code against the same data. They were byte-for-byte identical, for both
  versions of fix 1 (`results/parity-summary.txt`).
- Raw files: the per-level tables are in `results/*-levels.md` and the per-10 s timelines in
  `results/*-timeline.md`.

## 4. Baseline

**Single user, 30 s** (`smoke`). These are the latencies with no queueing at all.

| Endpoint | Before p50 | Before p95 | After p50 | After p95 |
|---|---:|---:|---:|---:|
| all requests | 3.8 ms | 744 ms | 4.5 ms | 114 ms |
| `GET /api/products` | 724 ms | 1,383 ms | 109 ms | 136 ms |
| `GET /api/proposals?status=pending` | 153 ms | 265 ms | 28 ms | 56 ms |
| `GET /api/monitoring` | 153 ms | 165 ms | 60 ms | 77 ms |
| `GET /api/products/:id` | 6.6 ms | 7.5 ms | 4.6 ms | 5.8 ms |
| `GET /api/activity` | 3.8 ms | 5.5 ms | 5.3 ms | 6.3 ms |
| history / decisions / audit / health | 1.0–2.1 ms | 1.1–2.3 ms | 1.2–2.5 ms | 1.3–3.0 ms |

| | Before | After |
|---|---:|---:|
| Requests in 30 s | 199 | 649 |
| Throughput | 6.5 req/s | 21.5 req/s |
| Error rate | 0% | 0% |
| p99 / max (all requests) | 1,250 / 1,574 ms | 134 / 139 ms |

Every request returned HTTP 200 in both runs. The "before" figures are the second (warm) run. The
first smoke run came straight after seeding and was slower (`/api/products` p50 1,178 ms), so it
isn't used for comparison.

**Where the time goes, per request** (`query_profile.py`, in-process, median of 5):

| Endpoint | SQL statements before → after | Total ms before → after | In Postgres ms before → after |
|---|---:|---:|---:|
| `/api/products` | 1,802 → 8 | 448 → 76 | 236 → 22 |
| `/api/proposals?status=pending` | 631 → 10 | 157 → 27 | 89 → 14 |
| `/api/monitoring` | 604 → 9 | 156 → 59 | 85 → 21 |
| `/api/products/{id}` | 20 → 8 | 7.6 → 4.6 | 3.5 → 1.9 |
| `/api/activity`, history, decisions, health | unchanged (5 / 4 / 4 / 1) | 1.3–4.4 → 1.4–4.5 | |

## 5. Load test

The same script, 5 → 50 VUs, 1 s think time.

| | Before | After (final code) | Change |
|---|---:|---:|---:|
| p50 | 869 ms | 64 ms | −93% |
| p90 | 5,204 ms | 206 ms | −96% |
| p95 | 6,401 ms | 282 ms | −96% |
| p99 | 7,972 ms | 440 ms | −94% |
| max | 10,652 ms | 719 ms | −93% |
| Throughput | 7.5 req/s | 19.4 req/s | +158% |
| Requests | 2,565 | 6,598 | |
| Error rate | 0.00% | 0.00% | |
| HTTP statuses | all 200 | all 200 | |
| Server CPU, median / max | 126% / 162% | 33% / 110% | |
| DB connections held by requests, max | 15 of 15 | 10 | |

The throughput gain is a consequence of the closed model: the users spend less time waiting, so they
send more requests. A rerun of the "before" code on the re-seeded data gave 2,639 requests, 7.7 req/s
and p95 5.9 s (within 3–9% of the first run).

**Per load level.** Steady windows only; "before" is that rerun, the one with a time series:

| VUs | Before req/s | Before p50 | Before p95 | Before p99 | After req/s | After p50 | After p95 | After p99 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 5 | 3.9 | 219 ms | 898 ms | 1.0 s | 4.8 | 35 ms | 127 ms | 143 ms |
| 10 | 7.8 | 168 ms | 1.0 s | 1.7 s | 9.5 | 40 ms | 131 ms | 166 ms |
| 25 | 9.4 | 1.5 s | 4.8 s | 5.1 s | 23.6 | 45 ms | 151 ms | 199 ms |
| 50 | 10.3 | 3.5 s | 7.3 s | 8.2 s | 44.2 | 99 ms | 354 ms | 523 ms |

Before: under this workload and environment, degradation began between **10 and 25 VUs**. Going
from 10 to 25 users added only 1.6 req/s, and p95 went from 1.0 s to 4.8 s. After: throughput tracks
the user count all the way to 50 (44.2 req/s is about the most 50 users with a 1 s think time can
send), and p95 stays under 0.4 s.

## 6. Stress test

10 → 25 → 50 → 100 → 150 VUs, each held 45 s. Per steady level:

| VUs | Before (original) | After fix 1 only | Final (both fixes) |
|---:|---|---|---|
| 10 | not separable (no time series in this run) | 9.5 req/s · p95 136 ms · 0% | 9.5 req/s · p95 135 ms · 0% |
| 25 | pool exhausted (15/15 connections held) | 23.6 req/s · p95 157 ms · 0% | 23.6 req/s · p95 146 ms · 0% |
| 50 | | 43.4 req/s · p95 472 ms · 0% | 44.5 req/s · p95 370 ms · 0% |
| 100 | deadlocked (see §12) | **1.1 req/s · p50 30.5 s · 45% errors** | 49.8 req/s · p95 1.5 s · 0% |
| 150 | deadlocked | **1.1 req/s · p50 59 s · 91% errors** | 48.7 req/s · p95 2.7 s · 0% |

| Whole run | Before | After fix 1 only | Final |
|---|---:|---:|---:|
| Requests | 1,851 | 5,219 | 11,068 |
| Throughput | 1.9 req/s | 14.9 req/s | 34.5 req/s |
| Error rate | 13.5% | 4.8% | 0.00% |
| p50 / p95 / p99 | 1.9 s / 60.0 s / 680 s | 89 ms / 30.6 s / 60.0 s | 657 ms / 2.4 s / 2.7 s |
| HTTP statuses | (no time series) | 200: 4,967 · 500: 75 · no response: 177 | 200: 11,068 |
| Server CPU median | 45% | 16% | 92% |

Notes on the "before" run:
- k6 needed **16 minutes** for a 7.5-minute script, because requests hung. 63 iterations were still
  stuck at the end.
- Its 680 s maximum is a request that never got its 60 s timeout. k6 recorded it when the run was
  force-stopped, so treat that tail as "never answered", not as a precise number.
- The sampler shows server CPU falling to about 1% from 300 s onwards, while all 15 connections sat
  "idle in transaction". The server log has `QueuePool limit of size 5 overflow 10 reached,
  connection timed out, timeout 30.00`.

**Degradation point, final code.** Under this workload and environment, degradation began around
**50–100 virtual users**. Throughput stopped scaling at about 49–50 req/s (44.5 at 50 VUs, 49.8 at
100, 48.7 at 150), and p95 rose from 370 ms to 1.5 s and then 2.7 s. The server process sat at
≈ 100% CPU, one core, with connections at most 12 of 15: **the limit is now one CPU-bound Python
worker**, not the database. Overload now means requests wait longer, not that they fail or hang.

**Experiment: 4 uvicorn workers** (a configuration flag, not a code change; not adopted as the
default):

| VUs | 1 worker | 4 workers |
|---:|---|---|
| 50 | 44.5 req/s · p95 370 ms | 46.4 req/s · p95 251 ms |
| 100 | 49.8 req/s · p95 1.5 s | 86.0 req/s · p95 511 ms |
| 150 | 48.7 req/s · p95 2.7 s | 109.3 req/s · p95 1.0 s |

With 4 workers: 17,010 requests, 0 errors, peak 34 Postgres connections, and server memory of
581–900 MB in total, against about 230 MB for one worker. The 1-worker column is the final run; the
4-worker run used fix 1's first version plus fix 2 (see §13). This confirms CPU is the remaining
limit. Choosing the worker count is a deployment decision. It has to respect Postgres's 100
connections (each worker has its own pool of 15) and the host's memory.

## 7. Spike test

10 VUs for 60 s, 100 VUs within 5 s and held 60 s, then 10 VUs for 120 s. Per 10 s window
(requests are counted when they finish):

| Window | Before: req/s · p95 · errors | Final: req/s · p95 · errors |
|---|---|---|
| 0–60 s, 10 VUs | 7.3–8.2 · 0.8–1.5 s · 0 | 9.3–10.1 · 119–143 ms · 0 |
| 60–70 s, spike starts | 2.5 · 2.6 s · 0 | 43.9 · 1.4 s · 0 |
| 70–90 s | **0 requests completed** | 49.7–50.0 · 1.4–1.5 s · 0 |
| 90–100 s | 4.0 · 32.0 s · 20 errors (HTTP 500 after the 30 s pool timeout) | 48.7 · 1.4 s · 0 |
| 100–120 s | **0 requests completed** | 45.6–49.7 · 1.3–1.6 s · 0 |
| 120–130 s | 6.0 · 60.0 s · 39 errors (k6 60 s timeouts) | 40.3 · 1.7 s · 0 |
| 130–190 s, back to 10 VUs | 0–8.6 req/s · stuck requests time out · 36 + 15 errors | 9.2–9.9 · 105–135 ms · 0 |
| 190–250 s | 7.9–8.6 · 0.6–1.0 s · 0 (recovered) | 9.2–9.8 · 119–150 ms · 0 |

| Whole run | Before | Final |
|---|---:|---:|
| Requests | 1,222 | 4,995 |
| Error rate | 9.0% (no response 4.4% + HTTP 500 4.6%) | 0.00% |
| p50 / p95 / p99 | 218 ms / 59.8 s / 60.0 s | 869 ms / 1.47 s / 1.64 s |
| Recovery after the spike | ≈ 60 s: back to normal about 190 s in, while the stuck requests time out | within the first 10 s window |

The before run was repeated from a fresh server: 1,223 requests, 13.0% errors, p95 60 s. A third run,
started while the server was still stuck from the stress test, gave 11.3% errors. That run is how we
learned the server **does not recover until the stuck requests time out**. The intermediate code
(fix 1 only) served 47.8 req/s for the first 10 s of the spike, then deadlocked the same way (2.97%
errors over the run).

## 8. Concurrency test (approval race)

**What is at stake.** Approving a proposal resumes a paused LangGraph run, re-checks the market and
writes our new price with an audit row. Two reviewers clicking at once must not apply it twice, or
resume the workflow twice. `services/proposals.review` takes `SELECT … FOR UPDATE` on the proposal
row before checking that it is still `pending`.

**pytest** (`backend/tests/test_approval_concurrency.py`, 4 tests, 1.4 s). Threads are released by
a barrier, and the resume step is wrapped in a 0.2 s sleep so the race window is wide:

| Test | Asserted, against the database |
|---|---|
| 10 concurrent approvals, real workflow (scripted model) | exactly 1 approved; 9 `ProposalClosed` (HTTP 409); the workflow resumed once; exactly 1 `our_price_changes` row; price 979 → 889 |
| 5 approve + 5 reject at once | exactly one winner; final status = the winner's; the price changed only if approve won |
| counterfactual: same race with the row lock removed (stub resume step) | the price **is** applied more than once, so the test can detect the bug |
| 5 approvals on 5 *different* proposals (stub resume step) | all succeed in parallel, in under 0.6 s against ≥ 1 s if serialised: the lock is per row, not global |

Counterfactual, 5 runs each way (`perf/results/concurrency-counterfactual.txt`):
- **with the lock:** 1 resume, 1 price change and 9 refusals, every time;
- **without it:** 10 resumes and 10 price changes, every time.

**HTTP** (`perf/k6/approval_concurrency.js`, final code). 20 seeded proposals, each hit by 10
parallel `POST /api/proposals/:id/approve`, 4 proposals at a time:

| Result | Count |
|---|---:|
| winners (200) | 20 |
| refused (409) | 180 |
| unexpected statuses | 0 |
| proposals with more than one audit row | 0 |
| checks passed | 60 / 60 |

Approve latency was p50 36 ms. The first wave (the first 4 proposals × 10 clicks, 40 requests)
took 440–466 ms, because the workflow and its Postgres checkpointer are built on the first approve.
After that, all 160 requests finished in 86 ms or less.

## 9. Scheduler test

`perf/harness/scheduler_bench.py` runs one real `run_once` cycle per catalogue size, each in a
fresh process and a freshly seeded `tracker_perf_sched` database. It covers the due-listing query,
the observation writes, the gate, the real LangGraph workflow with Postgres checkpoints, and the
proposal rows. Fetching, the model and email are fakes. 20% of products get an 8% competitor drop,
so 20% of products trigger a decision.

| Products | Listings | AI runs | Cycle, before | Cycle, final | SQL per listing (before → final) | Listings/s, final | Workflow avg, final | Peak RSS |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 10 | 20 | 2 | 0.14 s | 0.15 s | 14.0 → 12.4 | 135 | 17.4 ms | 132 MB |
| 50 | 100 | 10 | 0.65 s | 0.55 s | 13.8 → 12.2 | 183 | 12.1 ms | 132 MB |
| 100 | 200 | 20 | 1.15 s | 1.06 s | 13.8 → 12.2 | 189 | 12.6 ms | 133 MB |
| 250 | 500 | 50 | 2.88 s | 2.51 s | 13.8 → 12.2 | 199 | 11.5 ms | 133 MB |
| 500 | 1,000 | 100 | 5.27 s | 5.12 s | 13.8 → 12.2 | 196 | 11.4 ms | 136 MB |

- The work scales linearly, at about 5 ms per listing. 0 errors, 0 emails (none configured).
- At 500 products the due-listing query takes 9 ms, and the time inside Postgres is 2.3 s.
- The first version of fix 1 made this cycle **20% slower** (500 products: 6.31 s; see §12, B3).
  The final version is level with the original, within this machine's noise.

**What a real cycle adds (calculated, not measured).** The cycle is sequential.
- **Scraping.** The rate limiter allows one request per domain every 5 s
  (`SOURCE_MIN_INTERVAL_SECONDS`). Listings alternate Amazon and Flipkart, so the ceiling is 2
  fetches per 5 s = 0.4 listings/s, before any fetch latency. 200 listings therefore take at least
  about 8.3 min, and 1,000 listings about 42 min. With the default 6 h check interval, one worker
  can keep up with at most about 8,600 listings (6 h × 0.4/s), ignoring fetch time, retries and
  blocks.
- **AI.** Decisions also run one after another. With the measured real-model p50 of 5.2 s (§10),
  100 triggered products add about 9 minutes.

Scraping was not measured because the tests must not contact the marketplaces.

## 10. AI latency

**Application side, no provider** (`ai_latency.py`, `tracker_perf_ai`). The production workflow
runs with the deterministic model, which makes 2 model calls per run, like the real analyst
usually does.

| 100 runs | p50 | p90 | p95 | max |
|---|---:|---:|---:|---:|
| workflow run, end to end | 11.3 ms | 11.8 ms | 12.3 ms | 31.2 ms |
| inside model calls | 0.0 ms | 0.1 ms | 0.1 ms | 0.2 ms |
| **application**: graph, tools, DB, guardrails, checkpoint writes | 11.2 ms | 11.8 ms | 12.3 ms | 31.1 ms |

Outcomes: 96 pending review, 4 no change. A second pass with a fixed 1.0 s delay per model call
(10 runs) took 2,052 ms p50, of which 2,007 ms was inside the model. Two sequential calls add up
linearly. In that pass the non-model part rose to about 45 ms, against 11 ms without the delay. I
did not isolate why; it is about 2% of the run either way.

**Real model, small and controlled** (`ai_latency.py --real 20`). 20 decisions with Claude Haiku
4.5 over the 13 offline eval scenarios: an in-memory data provider, so there is no database,
scraping or email. LangSmith was off.

| n = 20 | p50 | p90 | p95 | max | mean |
|---|---:|---:|---:|---:|---:|
| decision, end to end | 5.21 s | 7.02 s | 7.23 s | 7.61 s | 5.48 s |
| inside provider calls (network + model) | 5.19 s | 7.00 s | 7.21 s | 7.59 s | 5.46 s |
| **application** (agent loop, tools, parsing) | 14.6 ms | 15.6 ms | 16.0 ms | 19.7 ms | 14.6 ms |
| per provider call (n = 58) | 1.14 s | 3.36 s | 3.64 s | 4.77 s | 1.88 s |
| network round trip to the API host (n = 3) | 257 ms | | | 290 ms | |

- **Success.** 0 failures, and the action was acceptable in **20/20** by the existing eval
  (`evals.evaluators.action_acceptable`). That also shows the eval harness still works.
- **Calls and tokens.** 2.9 provider calls per decision; 9,837 input and 402 output tokens per
  decision.
- **Cost.** About **$0.012 per decision**, $0.24 for the run, at Haiku 4.5's published $1 / $5 per
  million input / output tokens. This is an estimate from the token counts the API reported.
- **p99** is not reported, because with 20 samples it would just be the maximum.
- **Where the time goes.**
  - The application's own work is 0.3% of a decision.
  - Network: an unauthenticated GET to the API host takes about 257 ms on a warm connection. At
    2.9 calls per decision, that is roughly 0.75 s (about 14%) of a decision. This is an estimate:
    a model call's round trip is not exactly a GET's.
  - The provider, generating the response: the remaining ~85%.
  - Per-call times are bimodal: about 1.1 s for the tool-calling turns, and about 3 s or more for
    the final structured answer, which carries most of the output tokens.

## 11. Soak test

10 VUs for 30 minutes on the final code (1 worker), a freshly seeded database, the full dashboard
mix. Per 5-minute window (`results/soak-final-drift.md`):

| Minutes | Requests | req/s | Errors | p50 | p95 | p99 | max |
|---|---:|---:|---:|---:|---:|---:|---:|
| 0–5 | 2,855 | 9.5 | 0 | 40 ms | 131 ms | 159 ms | 284 ms |
| 5–10 | 2,849 | 9.5 | 0 | 43 ms | 131 ms | 159 ms | 192 ms |
| 10–15 | 2,852 | 9.5 | 0 | 40 ms | 131 ms | 165 ms | 294 ms |
| 15–20 | 2,847 | 9.5 | 0 | 43 ms | 133 ms | 163 ms | 206 ms |
| 20–25 | 2,850 | 9.5 | 0 | 39 ms | 134 ms | 167 ms | 222 ms |
| 25–30 | 2,848 | 9.5 | 0 | 40 ms | 130 ms | 163 ms | 198 ms |

| Minutes | Server RSS, mean / max | CPU median | Threads, max | DB connections, max | Held by a request, max |
|---|---:|---:|---:|---:|---:|
| 0–5 | 183 / 193 MB | 23% | 17 | 5 | 3 |
| 5–10 | 191 / 194 MB | 23% | 14 | 5 | 4 |
| 10–15 | 184 / 190 MB | 23% | 14 | 5 | 3 |
| 15–20 | 186 / 194 MB | 23% | 13 | 5 | 3 |
| 20–25 | 191 / 198 MB | 24% | 13 | 5 | 4 |
| 25–30 | 190 / 201 MB | 22% | 12 | 5 | 5 |

Whole run: 17,102 requests, all HTTP 200, 0 errors. p50 41 ms, p95 132 ms, p99 163 ms, max 294 ms.
The thresholds passed.

What it shows:
- **No latency drift.** p95 stayed at 130–134 ms in every window.
- **No rising errors.**
- **No connection leak.** Never more than the pool's 5 base connections; 886 samples.
- **No thread growth.** 12–17 threads.
- **Memory levels off.** RSS went from 151 MB at start to about 183–191 MB within the first 5
  minutes, then stayed there. The highest sample was 201 MB, and the last was 180 MB. That is the
  allocator warming up to the working set, not a leak, over this duration.

Not measured:
- **Longer runs.** Leaks that need hours, or growing data, would not show in 30 minutes.
- **Postgres-side resources over time.** The table and index sizes don't change, because the soak
  only reads.
- **Python heap internals.** No tracemalloc; RSS only.

While the soak ran I post-processed earlier result files for a few seconds at a time, on other
cores. No blip is visible in the windows above.

## 12. Bottlenecks

### B1: N+1 queries in the list endpoints

- **Observation.**
  - In the load test, `/api/products` had p95 8.0 s.
  - `/api/proposals` and `/api/monitoring` had p95 5.3–5.7 s.
  - The single-product endpoints queued behind them, at p95 3.2–3.5 s.
- **Evidence.**
  - `query_profile.py` shows 1,802 SQL statements per `/api/products` call (631 for proposals, 604
    for monitoring), and 236 of its 448 ms spent waiting on Postgres round trips.
  - cProfile puts 46% of the request in `repo.history_stats`, called 600 times for 3 requests.
  - The sampler showed Postgres "executing a query" on at most 1 connection. The database wasn't
    busy. The time went into the number of round trips and the Python work around each one.
- **Root cause.**
  - `to_out` → `pricing_context` → `listing_snapshot` → `history_stats` ran about 9 queries per
    listing.
  - `listing_out` and `price_series` added more per listing.
  - The proposal queue rebuilt a pricing context per pending proposal, and monitoring ran 3 queries
    per listing.
- **Change.** See §13.1.
- **Re-test.** Same smoke and load scripts, same data shape, plus a parity check on 204 responses.
- **Result.**
  - 1,802 → 8 statements.
  - Load p95 6.4 s → 0.28 s, with byte-identical responses.

### B2: worker-thread / connection-pool deadlock under bursts

- **Observation.**
  - In the stress test, CPU dropped to about 1% while requests hung, and completions stopped for
    20–30 s at a time.
  - Failures arrived in batches about 30 s apart, then at 60 s.
  - After the test, `/health` didn't answer within 10 s.
- **Evidence.**
  - `pg_stat_activity` during the stall showed all 15 connections `idle in transaction`, 19–23 s
    old.
  - Their last statements were *end-of-request* queries (`price_series`, the `runs` sum,
    `our_price_changes`), or only the `ProductDep` lookup.
  - The server log has `QueuePool limit … connection timed out, timeout 30.00`.
  - The batches at ≈ 30 s are the pool timeout, returned as HTTP 500. The ones at 60 s are k6's
    timeout, with no response.
  - Fix 1 alone moved the breaking point (fine at 50 VUs) but reproduced the same pattern at 100
    VUs. So the slow queries were not the root cause.
- **Root cause.** The endpoints are sync, so a request hops between the event loop and Starlette's
  40-thread pool:
  - once for a sync dependency such as `ProductDep`;
  - once for the endpoint;
  - once more for **response validation**. FastAPI runs `serialize_response` through
    `run_in_threadpool` for sync endpoints (checked in `fastapi/routing.py`).

  The request's SQLAlchemy session holds its pooled connection across all those hops, until the
  dependency exits. With more than 40 requests in flight, every thread can be blocked waiting for
  a connection (up to 30 s), while every connection belongs to a request waiting for a thread to
  validate its response. Nothing moves until the 30 s pool timeout fails some requests.
  - FastAPI already runs yield-dependency teardown with its own limiter (`concurrency.py` comments
    on exactly this deadlock), but the response-validation hop is not covered.
  - Client disconnects do not cancel sync work, so requests k6 has abandoned keep the queue full.
    That is why the server stayed stuck after the stress test ended.
- **Change.** See §13.2.
- **Re-test.** The same stress and spike scripts.
- **Result.** 0 errors in both. The pool never runs dry (at most 10–12 connections), and the spike
  recovers within 10 s.

### B3: my own first version of fix 1 slowed the scheduler (found and fixed)

- **Observation.** The scheduler benchmark after fix 1 (first version) was 20% slower at every size
  (500 products: 5.27 → 6.31 s).
- **Evidence.**
  - Micro-benchmarks, alternating old and new code 6 times: `history_stats` for one listing went
    from 1.02 ms to 1.9–4.4 ms per call, and `pricing_context` for one product from 3.6 ms to
    7.1 ms (medians).
  - Postgres-side planning and execution were sub-millisecond for both. cProfile showed the time in
    SQLAlchemy **building** the aliased LATERAL query on every call, about 1 ms per statement.
  - It also showed an extra query that `history_stats` didn't need.
- **Change.**
  - Build each query shape once (cached, with the ids as a bound array parameter).
  - Use the plain indexed query when there is only one listing.
  - Use `unnest(ids)` + LATERAL instead of `id IN (… LATERAL …)`, which is 5× cheaper in Postgres
    at 200 listings: 0.96 ms against 4.85 ms of execution.
  - Skip the price-series query for stats-only reads.
- **Result.**
  - `history_stats` 1.02 → 0.92 ms.
  - `pricing_context` 3.36 → 1.98 ms (medians of 18).
  - Scheduler 5.27 → 5.12 s at 500 products.
  - All load, stress and spike numbers in this report are from this final version, apart from the
    "after fix 1 only" columns and the 4-worker experiment.

### B4: one CPU-bound worker (identified, not changed)

After both fixes, the stress test levels off at about 49–50 req/s with the server at ≈ 100% of one
core, and Postgres connections are not the limit. Four workers reached 109 req/s (§6). That is a
deployment setting, so it is documented, not changed.

### Looked at and not a bottleneck here

- **Indexes.** The hot queries use `ix_price_obs_item_time (item_id, fetched_at DESC)` index scans
  (checked with `EXPLAIN ANALYZE`), so no schema change was made.
- **The due-listing query** (an aggregate over every observation) took 9 ms with 1,000 listings and
  60,000 readings.
- **Lock contention.** The approval row lock is per proposal (pytest proves parallel approvals of
  different proposals).
- **Memory.** Under load the server's RSS rose from about 135 MB to about 230 MB and stayed there.
  In the 30-minute soak (§11) it leveled off at 183–191 MB.

## 13. Optimizations

Only these two code changes were made. Each is a patch in `perf/optimizations/`.

### 13.1 Batch the per-listing reads (`01-batch-listing-reads.patch`)

- **`repo.listing_reads(ids)`** fetches, for any number of listings, in at most five queries:
  - the newest 20 readings;
  - the latest successful reading;
  - the newest 24 priced readings;
  - the all-time low and high;
  - the stats window.
- The **calculations** live in `stats_from` / `snapshot_from` / `series_from` and are shared:
  `history_stats`, `listing_snapshot` and `pricing_context` keep their signatures and call the same
  code with one id. So the AI tools, the scheduler and the endpoints all compute the numbers the
  same way.
- **New bulk entry points:**
  - `repo.listings_by_product`;
  - `repo.pricing_contexts`;
  - `services.products.to_out_many`;
  - the proposals route's `_outs`, which batches products, listings, decisions and freshness;
  - monitoring uses `listing_reads` plus `failure_streak`, which falls back to the old per-listing
    query only when the 20 newest readings all failed.
- **Tests added:**
  - batched results equal reading each listing alone;
  - a failure streak longer than the read window.
- **Safety net:** the 119 existing tests pass unchanged, and the 204 parity responses are identical.

### 13.2 Admission limit for `/api` (`02-admission-limit.patch`)

`app/core/admission.py` is a 47-line ASGI middleware. At most `API_MAX_CONCURRENCY` (default 10)
`/api` requests run at once. The others wait on the event loop, holding no thread and no
connection, for up to `API_QUEUE_TIMEOUT_SECONDS` (10 s), and then get `503` with `Retry-After: 1`.
- **Why 10.** It keeps worker threads (40) and connections (15) out of reach, leaving room for
  `/health`, `/internal` and nested sessions. For example, an approval briefly uses 2 connections.
  It is also plenty to keep one CPU busy: the stress test ran the CPU at about 100% with at most 10
  requests admitted.
- `/health` and `/internal` are not limited.
- It sits inside CORS, so a 503 still carries CORS headers.
- **Tests added** (`test_admission.py`): requests beyond the limit queue rather than run; an
  over-long wait gets 503 with `Retry-After`; non-`/api` paths are not limited.

No 503 was returned in any test. Even at 150 VUs, no request waited 10 s.

Also changed, in the tests only: `api_load.js` and `soak.js` thresholds were set from the measured
baseline (§16, README "Thresholds").

## 14. Before / after

Same scripts, same dataset shape, 1 uvicorn worker. "Before" is the original code; "after" is the
final code.

**Load test (5 → 50 VUs)**

| Test | Before | After | Change |
|---|---:|---:|---:|
| p50 | 869 ms | 64 ms | −93% |
| p95 | 6,401 ms | 282 ms | −96% |
| p99 | 7,972 ms | 440 ms | −94% |
| Throughput | 7.5 req/s | 19.4 req/s | +158% |
| Error rate | 0.00% | 0.00% | – |

**Stress test (10 → 150 VUs)**

| Test | Before | After | Change |
|---|---:|---:|---:|
| p50 | 1,934 ms | 657 ms | −66% |
| p95 | 60,001 ms (timeouts) | 2,409 ms | −96% |
| p99 | 680 s (hung requests) | 2,679 ms | – |
| Throughput | 1.9 req/s | 34.5 req/s | 18× |
| Error rate | 13.5% | 0.00% | – |
| Throughput at 100 / 150 VUs | collapsed | 49.8 / 48.7 req/s | – |

**Spike test (10 → 100 → 10 VUs)**

| Test | Before | After | Change |
|---|---:|---:|---:|
| p50 | 218 ms | 869 ms | +299% |
| p95 | 59,776 ms | 1,469 ms | −98% |
| p99 | 60,002 ms | 1,639 ms | −97% |
| Throughput | 4.9 req/s | 19.9 req/s | +306% |
| Error rate | 9.0% | 0.00% | – |
| Recovery after spike | ≈ 60 s | < 10 s | – |

The spike p50 got **worse**. That is honest queueing: after the fix, all 100 users are served (each
waits about 1 s at the peak), so many more requests land in the slow phase. Before, few requests
completed during the spike at all, and the median came from the quiet phases.

**Single user (smoke)**

| Test | Before | After | Change |
|---|---:|---:|---:|
| `/api/products` p50 | 724 ms | 109 ms | −85% |
| `/api/products` p95 | 1,383 ms | 136 ms | −90% |
| all requests p95 | 744 ms | 114 ms | −85% |
| Throughput (1 VU) | 6.5 req/s | 21.5 req/s | +231% |
| Error rate | 0% | 0% | – |

**Scheduler (500 products, fake fetch and model)**

| Test | Before | After | Change |
|---|---:|---:|---:|
| Cycle | 5.27 s | 5.12 s | −3% (within noise) |
| SQL statements per listing | 13.8 | 12.2 | −12% |

## 15. Limitations

- **One machine, one process.** The load generator, the API and Postgres share the laptop, and
  results vary run to run (§2). Nothing here is a production SLO or a capacity claim. Production
  needs its own hardware, network, data volume and traffic shape.
- **Small, hot dataset.** 12,200 readings in an 11 MB database that fits in memory. Production
  history grows by about 4 readings per listing per day. The batched queries use LIMIT per listing,
  so most cost does not grow with history length, but the stats window and the due-listing
  aggregate do. Not measured at larger volumes.
- **Synthetic workload.** The request mix is weighted by the dashboard's polling, not by real
  traffic. Think time is a fixed 1 s, and the VU model is closed (offered load drops when the server
  slows). An open-model test (fixed arrival rate) was not run.
- **Not measured:**
  - **Marketplace scraping**, so as not to contact Amazon or Flipkart. The 5 s per-domain pacing
    bound in §9 is calculated.
  - **Email sending.**
  - **Multi-host deployment.**
  - **The frontend.**
  - **Write-heavy endpoints** other than approve.
  - **Postgres-side metrics** beyond `pg_stat_activity` and `EXPLAIN` (for example `pg_stat_statements`).
- **Few samples in places.**
  - The real-model benchmark is n = 20 against one provider at one time of day. Provider latency
    varies by hour and region.
  - The scheduler benchmark is one run per size.
  - Several "before" figures come from one run each; where repeated, their spread is given.
- **Sampler gaps.** `ps` CPU is a decaying average, not instantaneous. During the "before" stress
  stall the sampler logged sparsely (its `ps` calls were slow).
- **The earlier "after fix 1" and 4-worker runs** used the first version of fix 1 (§12, B3). They
  are labelled where shown. The final before/after tables use the final code.
- **The stress test's "before" run has no per-request time series**, so its per-level breakdown
  comes from the sampler and server log, not from latency per level.

## 16. Reproduction commands

```bash
# one-time
brew install k6
docker compose -f infra/docker-compose.yml up -d postgres
perf/run.sh seed 100                      # tracker_perf, deterministic

# API tests (perf backend on :8100, 1 worker like the Dockerfile)
perf/run.sh serve
perf/run.sh measure smoke  mylabel
perf/run.sh measure load   mylabel
perf/run.sh stop; perf/run.sh serve; perf/run.sh measure stress mylabel
perf/run.sh stop; perf/run.sh serve; perf/run.sh measure spike  mylabel
perf/run.sh measure soak   mylabel -e DURATION=30m -e VUS=10
perf/run.sh measure approval mylabel     # consumes seeded proposals: run perf/run.sh seed again after
perf/run.sh stop; perf/run.sh serve 4; perf/run.sh measure stress 4workers   # worker experiment

# reading results
.venv/bin/python perf/harness/summarize.py perf/results/load-mylabel.json --sampler perf/results/load-mylabel-sampler.csv
.venv/bin/python perf/harness/timeline.py perf/results/stress-mylabel-points.json.gz --by-vus
.venv/bin/python perf/harness/timeline.py perf/results/spike-mylabel-points.json.gz      # per 10 s
.venv/bin/python perf/harness/timeline.py perf/results/spike-mylabel-points.json.gz --statuses

# application level
perf/run.sh queries --profile /api/products        # SQL statements per endpoint + cProfile
perf/run.sh concurrency                            # approval race tests (pytest, tracker_test)
perf/run.sh scheduler                              # 10/50/100/250/500 products
perf/run.sh ai                                     # fake model, 100 runs
perf/run.sh ai --real 20                           # real Claude: 20 decisions, ≈ $0.25

# before vs after: serve the old code from a copy with the patches reverted
REPO=$PWD; mkdir -p /tmp/perf-before && cp -R backend /tmp/perf-before/ && ln -sfn "$REPO/infra" /tmp/perf-before/infra
(cd /tmp/perf-before && patch -R -E -p0 < "$REPO/perf/optimizations/02-admission-limit.patch" \
                     && patch -R -E -p0 < "$REPO/perf/optimizations/01-batch-listing-reads.patch")
perf/run.sh stop; PERF_BACKEND=/tmp/perf-before/backend perf/run.sh serve
.venv/bin/python perf/harness/parity.py capture perf/results/parity/before   # then serve the new code:
.venv/bin/python perf/harness/parity.py capture perf/results/parity/after
.venv/bin/python perf/harness/parity.py diff perf/results/parity/before perf/results/parity/after

# the whole backend suite (128 tests) and lint
cd backend && ../.venv/bin/pytest -q && cd .. && .venv/bin/ruff check backend perf --config backend/pyproject.toml
```

---

## What I should be able to explain verbally

**Latency.** The time one request takes, from sending it to having the full answer. Here that is
`http_req_duration` in k6.

**Throughput.** How many requests finish per second. Our final load test did 19.4 req/s overall and
44 req/s at 50 users.

**Concurrency.** How many requests are in progress at the same instant. By Little's law it is
throughput × average latency. Before the fix: 7.5 req/s × 1.83 s ≈ 14 in flight. After: 19.4 × 0.09
≈ 1.7. The same users, far less queueing.

**p50 / p95 / p99.** Sort all latencies:
- **p50** is the middle, the typical request;
- **p95** means 95% were faster, so 1 in 20 is slower;
- **p99** is the slowest 1%.

**Why p95 and not the average.** The average hides the tail. A page that fires 5 requests hits the
p95 tail on about 1 view in 4. Our "before" load test had a p50 of 869 ms, which looks tolerable,
and a p95 of 6.4 s, which is what users actually felt.

**Load / stress / spike / soak.**
- **Load:** the expected range of traffic, stepped up so each level can be read (5–50 users).
- **Stress:** push past it to find where it breaks and how (up to 150 users).
- **Spike:** a sudden 10× jump and back, to see whether it survives and recovers.
- **Soak:** modest load for a long time (30 min), to catch leaks and drift. Ours stayed flat:
  p95 130–134 ms in every 5-minute window, memory leveled off at about 190 MB, and connections never
  went over 5.

**A virtual user in k6.** A goroutine running my script in a loop: pick a dashboard request, wait
for the answer, sleep 1 s, repeat. It's a closed model, so a slow server slows the users down too.
That's why throughput rose after the fix: the users weren't waiting as long.

**Concurrency vs requests per second.** 50 VUs is not 50 req/s. Each VU waits for its response and
then thinks for 1 s. At 50 VUs we measured 10.3 req/s before the fix (requests queued for seconds)
and 44.2 after.

**How k6 generates load.** Each VU is a lightweight goroutine with its own HTTP connection. Stages
ramp the VU count, and every request is recorded with tags (endpoint name, status), which is how I
get per-endpoint percentiles and the per-10-second timeline.

**Not hitting Amazon or Flipkart.** The perf backend runs against its own database on port 8100,
and nothing in the perf tooling calls a scraper.
- The HTTP tests only call an allow-list of read endpoints plus approve; none of them scrape.
- The scheduler benchmark passes `run_once` a fake `fetch`.
- Model keys are replaced with a dummy, so any stray model call fails with a 401.
- Email credentials are blanked.
- The k6 library refuses to target the dev port.

**Testing the scheduler safely.** The real `run_once` cycle and the real LangGraph workflow with
Postgres checkpoints run, but the three outside calls are injected fakes: a fetcher that returns an
8% drop for 20% of products, a deterministic model that picks the offered option, and a no-op
mailer. Each catalogue size gets a fresh process and database.

**Testing the approval race.** Ten threads wait on a barrier and call the approval service at the
same instant. The workflow resume is padded to 0.2 s so they all overlap. I then check the database,
not just status codes: one approved row, one audit row, one workflow resume and the right price. And
I proved the test can fail: with the row lock removed, the same test applied the price 10 times out
of 10. Over HTTP, k6 fired 10 parallel approves at each of 20 proposals: 20 × 200, 180 × 409, no
duplicate audit rows.

**Why two simultaneous approvals are dangerous.** Both read "pending", both resume the workflow and
both write a price change. You get duplicate audit entries, and if the two clicks carried different
override prices, the last writer silently wins.

**How the lock prevents it.** `SELECT … FOR UPDATE` on the proposal row: the second transaction
blocks until the first commits, then sees `approved` and gets `ProposalClosed` (409). It locks one
row, not the table, and the test shows approvals of *different* proposals still run in parallel.

**What the bottleneck was.** Two of them:
1. **N+1 queries.** The product list ran 1,802 SQL statements per request.
2. **A thread/connection deadlock.** Under bursts, all 40 worker threads waited for a DB
   connection while all 15 connections waited for a thread to finish their response. The server
   stalled for 30 s at a time and didn't recover until the stuck requests timed out.

**How I identified it.**
- **The slowness:** latency percentiles per endpoint pointed at the three list endpoints. The query
  profiler counted the statements, cProfile showed `history_stats` was 46% of the time, and the
  sampler showed Postgres itself was idle.
- **The deadlock:** the CPU dropping to ~0% while requests hung, `pg_stat_activity` showing 15
  connections "idle in transaction" whose last query was the *end* of a request, the 30-second
  rhythm of the failures matching the pool timeout, and FastAPI's source showing response
  validation runs in the threadpool.
- After fixing the queries, the deadlock still happened at 100 users. That told me it was a
  separate problem.

**What changed.**
1. **Batched reads.** The list endpoints read all listings' history in about 5 queries instead of
   9 per listing, with the same calculations shared by the single-item paths.
2. **A small admission limit.** At most 10 `/api` requests run at once, and the rest wait on the
   event loop, holding nothing, or get a quick 503 after 10 s.

**How I know it worked.**
- The same scripts, the same data shape and the same config, before and after.
- The load test's p95 went from 6.4 s to 0.28 s.
- The stress test went from 13.5% errors to 0% at 150 users.
- The spike recovers in under 10 s instead of about 60.
- 204 API responses are byte-for-byte identical.
- 128 backend tests pass.
- When my first version of the query fix made the scheduler 20% slower, the benchmark caught it,
  and I fixed that too.

**Limitations of the benchmark.** One laptop running the generator, the API and the DB; an 11 MB
dataset that fits in memory; a synthetic closed-model workload; single runs for some "before"
numbers; machine variance of up to 2–3× in micro-benchmarks; no scraping or email measured; 20
real-model calls.

**Why local numbers aren't production SLOs.** Production has different hardware, network
distance, data size, concurrency patterns and noisy neighbours. An SLO is also a business decision
about what users need, not just what one test reached. These numbers are useful as a regression
baseline (the k6 thresholds) and for finding bottlenecks, not as a promise of capacity.
