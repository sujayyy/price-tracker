# Performance testing

This directory measures how the Price Tracker backend behaves under load. The results, the
bottlenecks found and the fixes are in [REPORT.md](REPORT.md). This file covers how to run the tests
and how to read the numbers.

Everything here runs against an **isolated copy** of the backend:

| | Development | Performance tests |
|---|---|---|
| API | `localhost:8000` | `127.0.0.1:8100` (`perf/run.sh serve`) |
| Database | `tracker` | `tracker_perf` (also `tracker_perf_sched` and `tracker_perf_ai`) |
| Marketplace scraping | real | **never**: scripts inject fake fetchers |
| LLM (Claude) | real | **never**, except `ai_latency.py --real N` (N ≤ 30) |
| Email | Gmail SMTP | **off**: SMTP credentials and recipients are blanked |
| LangSmith tracing | per `.env` | **off** |

The safety rails are enforced in code, not left to convention:
- `perf/harness/env.py` refuses to run against the `tracker` or `tracker_test` databases. It
  replaces the model API keys with a dummy value, so a stray model call fails with a 401 instead
  of costing money.
- `perf/k6/lib.js` refuses to target the dev API on `:8000`. It also only allows an explicit list
  of paths: the read-only dashboard endpoints plus approve, which runs on seeded proposals only.

## Setup

```bash
brew install k6                       # k6 v2.3.0 was used for REPORT.md
docker compose -f infra/docker-compose.yml up -d postgres
perf/run.sh seed 100                  # create, migrate and seed tracker_perf (a few seconds)
perf/run.sh serve                     # start the perf backend on :8100 (1 uvicorn worker)
```

The seed is reproducible: a fixed random seed, 100 products, 2 listings each and 60 readings per
listing. A share of the products then gets a competitor price drop through the **real** scheduler
cycle and LangGraph workflow, using a deterministic stand-in model. Proposals are therefore created
the way production creates them, and 30 of them are left pending for the approval race tests.

## Running the tests

| Command | What it does | Time |
|---|---|---|
| `perf/run.sh measure smoke <label>` | 1 user walks every endpoint; checks everything returns 200 | 30 s |
| `perf/run.sh measure load <label>` | 5 → 10 → 25 → 50 users, 60 s at each step | 6 min |
| `perf/run.sh measure stress <label>` | 10 → 25 → 50 → 100 → 150 users, to find where it breaks | 6–7 min |
| `perf/run.sh measure spike <label>` | 10 users, jump to 100 in 5 s, then back to 10 | 4 min |
| `perf/run.sh measure soak <label>` | 10 users for 30 min (`-e DURATION=…`, `-e VUS=…`) | 30 min |
| `perf/run.sh measure approval <label>` | 10 simultaneous Approve clicks on each of 20 proposals | < 1 min |
| `perf/run.sh concurrency` | pytest approval race tests (row lock; `tracker_test` database) | 5 s |
| `perf/run.sh queries` | SQL statements and database time per endpoint (`--profile PATH` for cProfile) | 20 s |
| `perf/run.sh scheduler` | one scheduler cycle at 10/50/100/250/500 products (fake fetch, fake model) | 2–3 min |
| `perf/run.sh ai` | AI workflow latency with the deterministic model; `--real 20` adds real Claude calls | 1 min |

`measure` saves five files to `perf/results/` and prints the summary table:
- `<test>-<label>.json`: k6's summary export, with per-endpoint percentiles;
- `<test>-<label>.txt`: k6's console output, including threshold pass/fail;
- `<test>-<label>-points.json.gz`: every request, with its time, endpoint and status;
- `<test>-<label>-timeline.md`: req/s, errors and p50/p95 per 10 s window;
- `<test>-<label>-sampler.csv`: the server's CPU, memory, threads and database connections,
  sampled every 2 s.

The raw per-request files and the server log are gitignored (`perf/results/.gitignore`): they are
large and `measure` regenerates them. The per-level tables (`*-levels.md`), timelines and summaries
that REPORT.md cites are kept.

Per load level, and the HTTP status distribution:
`.venv/bin/python perf/harness/timeline.py perf/results/stress-<label>-points.json.gz --by-vus`
(or `--statuses`).

The approval test approves the seeded proposals, so run `perf/run.sh seed` again before repeating
it. The other tests only read.

To compare code versions (for example before and after an optimization), serve the other copy with
`PERF_BACKEND=/path/to/other/backend perf/run.sh serve`. Then check that both versions return
identical data:

```bash
.venv/bin/python perf/harness/parity.py capture perf/results/parity/before   # old code serving
.venv/bin/python perf/harness/parity.py capture perf/results/parity/after    # new code serving
.venv/bin/python perf/harness/parity.py diff perf/results/parity/before perf/results/parity/after
```

## Reading the numbers

**Latency** is the time from sending a request to receiving the full response, as k6 sees it
(`http_req_duration`: sending + waiting + receiving; connection setup is excluded).

**Percentiles.** Sort every request's latency:
- **p50** (median): half of all requests were faster than this. It is the typical experience.
- **p90 / p95**: 90% / 95% of requests were faster. One user in 10 or 20 waits at least this long.
  p95 is the usual number for a latency target, because averages hide the slow tail.
- **p99**: the slowest 1%. Noisy in short tests: with 2,000 requests it is set by about 20 of them.
- **max**: a single request, so it is anecdotal. It is useful for spotting timeouts (60 s is k6's
  request timeout).

A dashboard that fires 5 requests per page view hits p95 on roughly 1 page in 4 (1 − 0.95⁵). That is
why the tail matters more than the median.

**Throughput** (req/s) is completed requests per second over the whole test. In these tests every
virtual user waits 1 s between requests. When the server keeps up, throughput grows with users.
When throughput stops growing while users keep increasing, the server is saturated. That
"throughput plateau while latency climbs" is the clearest signal in a stress test.

**Virtual users (VUs)** are k6's simulated clients, each running a loop: pick a request from the
dashboard mix, wait for the answer, think for 1 s, repeat. This is a *closed* model. A slow server
slows the users down, so offered load drops as latency rises. VUs are therefore not "requests per
second". One VU sends a request about every second, which is far busier than one person: an open
dashboard polls every 20–60 s, so one VU is roughly the polling traffic of 20–60 open dashboards.

**Concurrency** is how many requests are in progress at the same moment. By Little's law,
concurrency ≈ throughput × average latency. In the load test before the fixes, 7.5 req/s × 1.83 s
average ≈ 14 requests were in flight at any moment. After the fixes, the same test ran 19.4 req/s ×
0.09 s ≈ 1.7 in flight. That is the same users, but far fewer requests sitting in queues.

**Error rate** is the share of requests that failed: an unexpected status, a connection error, or a
timeout. The approval test expects 409 for every click but the winning one, so it declares 409 as
an expected status.

**Server resources** come from `sampler.py`. CPU% is for the server process (100% = one full core;
`ps` reports a decaying average). RSS is resident memory. "DB connections" are the server's
connections to `tracker_perf`, split into *active* (running a query), *idle* (in the pool) and
*idle in transaction* (checked out by a request that is not currently running a query).

**The mix.** Each request is drawn from what the dashboard actually polls, weighted by how often:

| Weight | Request | Why the dashboard calls it |
|---:|---|---|
| 25% | `/api/proposals?status=pending` | the pending-approvals badge (every 20 s) and the Approvals page |
| 20% | `/api/products` | Overview and Products |
| 12% | `/api/products/:id` | Product page |
| 12% | `/api/products/:id/history?days=7` | product price chart |
| 10% | `/api/activity?days=14` | Overview feed |
| 8% | `/api/monitoring` | Monitoring page and the market tape |
| 5% | `/api/products/:id/decisions` | product decision log |
| 5% | `/health` | |
| 3% | `/api/products/:id/our-price-history` | our price audit |

## Thresholds

`api_load.js` and `soak.js` fail the run if:

| Metric | Limit | Measured on the final code |
|---|---|---|
| error rate | < 1% | 0% |
| all requests p95 / p99 | < 1000 ms / < 1500 ms | 282 ms / 440 ms |
| `/api/products`, `/api/proposals`, `/api/monitoring` p95 | < 1000 ms | 415 / 238 / 329 ms |
| single-product endpoints and `/health` p95 | < 300 ms | 59–170 ms |

The limits leave about 2× headroom, because repeated runs on this machine vary. The code as it was
before this work (p95 6.4 s) fails every one of them, which is what a tripwire is for.

These thresholds are **for this environment only**: one laptop, one uvicorn worker, Postgres in
Docker, a 100-product catalogue. They are not production SLOs. A production target would need
production hardware, a real traffic shape and a business decision on how slow is too slow.

## Files

```
perf/
  run.sh                     entry point for everything above
  k6/lib.js                  target, path allow-list, request mix, per-endpoint metrics
  k6/{smoke,api_load,api_stress,api_spike,soak,approval_concurrency}.js
  harness/env.py             isolated environment (database, keys, email, tracing)
  harness/seed.py            reproducible dataset via the real scheduler and workflow
  harness/fake_model.py      deterministic stand-in for the LLM
  harness/sampler.py         server CPU / RSS / DB connections while a test runs
  harness/summarize.py       k6 JSON → the tables in REPORT.md
  harness/query_profile.py   SQL statements and DB time per endpoint, plus cProfile
  harness/timeline.py        per-10 s and per-load-level tables, HTTP status distribution
  harness/parity.py          proves an optimization returns identical JSON
  harness/scheduler_bench.py scheduler cycle time vs catalogue size
  harness/ai_latency.py      AI workflow latency (fake model; --real N for the provider)
  optimizations/*.patch      each optimization as a diff against the code it replaced
  results/                   raw outputs referenced by REPORT.md
backend/tests/test_approval_concurrency.py   approval race tests (pytest)
backend/tests/test_admission.py              admission limit (optimization 2)
backend/tests/test_repo.py                   batched reads = one-at-a-time reads (optimization 1)
```
