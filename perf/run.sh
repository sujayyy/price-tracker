#!/usr/bin/env bash
# Performance test runner. Everything targets the isolated perf backend (port 8100, database
# tracker_perf); nothing here touches the dev database, marketplaces, the model API or email.
#
#   perf/run.sh seed [products]        create/reset tracker_perf and seed it (default 100 products)
#   perf/run.sh serve [workers]        start the perf backend on :8100 (background, logs in perf/results)
#   perf/run.sh stop                   stop it
#   perf/run.sh smoke|load|stress|spike|soak|approval   run a k6 test (JSON summary → perf/results)
#   perf/run.sh measure <test> <label> k6 test + resource sampler, saved as <test>-<label>.*
#   perf/run.sh concurrency            pytest approval race tests (tracker_test database)
#   perf/run.sh scheduler [--sizes N…] scheduler cycle benchmark (separate tracker_perf_sched database)
#   perf/run.sh queries [--profile P]  SQL statements per request, per endpoint (+ cProfile of path P)
#   perf/run.sh ai                     AI workflow latency with the fake model (add --real N for Claude)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/.venv/bin/python"
RESULTS="$ROOT/perf/results"
PORT="${PERF_PORT:-8100}"
mkdir -p "$RESULTS"
stamp() { date +%Y%m%d-%H%M%S; }

case "${1:-}" in
  seed)
    "$PY" "$ROOT/perf/harness/seed.py" --products "${2:-100}" ;;
  serve)
    WORKERS="${2:-1}"
    echo "===== $(date '+%F %T') serve: ${PERF_BACKEND:-$ROOT/backend}, $WORKERS worker(s)" >> "$RESULTS/server-$PORT.log"
    # Same isolation as perf/harness/env.py: own database, no email, no model key, no tracing, no demo.
    # PERF_BACKEND serves another copy of backend/ (e.g. the code before an optimization).
    cd "${PERF_BACKEND:-$ROOT/backend}"
    DATABASE_URL="postgresql+psycopg://tracker:tracker@localhost:5432/${PERF_DB:-tracker_perf}" \
    DEMO_ENDPOINTS_ENABLED=false SMTP_USER= SMTP_APP_PASSWORD= OPS_ALERT_EMAILS= \
    LANGSMITH_TRACING=false LANGCHAIN_TRACING_V2=false INTERNAL_RUN_SECRET=perf-secret \
    ANTHROPIC_API_KEY=perf-disabled GOOGLE_API_KEY=perf-disabled OPENAI_API_KEY=perf-disabled \
    CORS_ORIGINS=http://localhost:5173 \
      nohup "$ROOT/.venv/bin/uvicorn" app.main:app --host 127.0.0.1 --port "$PORT" --workers "$WORKERS" \
      --no-access-log --log-level warning >> "$RESULTS/server-$PORT.log" 2>&1 &
    echo $! > "$RESULTS/server-$PORT.pid"
    for _ in $(seq 1 40); do curl -sf "localhost:$PORT/health" >/dev/null && break; sleep 0.5; done
    curl -s "localhost:$PORT/health"; echo " (pid $(cat "$RESULTS/server-$PORT.pid"), workers $WORKERS)" ;;
  stop)
    # Wait for the process to exit: a server stuck on requests keeps its database connections while it
    # shuts down, which would leak into the next test's numbers. SIGKILL after 15 s.
    pattern="uvicorn app.main:app --host 127.0.0.1 --port $PORT"
    pkill -f "$pattern" 2>/dev/null || true
    for _ in $(seq 1 30); do pgrep -f "$pattern" >/dev/null || break; sleep 0.5; done
    pkill -9 -f "$pattern" 2>/dev/null || true
    rm -f "$RESULTS/server-$PORT.pid"; echo stopped ;;
  smoke|load|stress|spike|soak|approval)
    case "$1" in load) f=api_load ;; stress) f=api_stress ;; spike) f=api_spike ;; approval) f=approval_concurrency ;; *) f="$1" ;; esac
    out="$RESULTS/$1-$(stamp)"
    BASE_URL="http://localhost:$PORT" k6 run --summary-export "$out.json" "${@:2}" "$ROOT/perf/k6/$f.js" | tee "$out.txt" ;;
  measure)
    # perf/run.sh measure <test> <label> [k6 args]: the k6 test plus the resource sampler, saved as
    # <test>-<label>.{json,txt}, -sampler.csv, -points.json.gz (every request), -timeline.md (per 10 s)
    # and -levels.md (per steady VU level + HTTP statuses), so before/after runs pair up by name.
    t="$2"; label="$3"
    case "$t" in load) f=api_load ;; stress) f=api_stress ;; spike) f=api_spike ;; approval) f=approval_concurrency ;; *) f="$t" ;; esac
    "$PY" "$ROOT/perf/harness/sampler.py" --pid "$(cat "$RESULTS/server-$PORT.pid")" \
      --out "$RESULTS/$t-$label-sampler.csv" --every 2 & sp=$!
    BASE_URL="http://localhost:$PORT" k6 run --summary-export "$RESULTS/$t-$label.json" \
      --out "json=$RESULTS/$t-$label-points.json.gz" "${@:4}" "$ROOT/perf/k6/$f.js" > "$RESULTS/$t-$label.txt" 2>&1 || true
    kill "$sp" 2>/dev/null || true
    "$PY" "$ROOT/perf/harness/summarize.py" "$RESULTS/$t-$label.json" --sampler "$RESULTS/$t-$label-sampler.csv"
    pts="$RESULTS/$t-$label-points.json.gz"
    "$PY" "$ROOT/perf/harness/timeline.py" "$pts" > "$RESULTS/$t-$label-timeline.md"
    { "$PY" "$ROOT/perf/harness/timeline.py" "$pts" --by-vus; echo
      echo "HTTP statuses: $("$PY" "$ROOT/perf/harness/timeline.py" "$pts" --statuses)"; } > "$RESULTS/$t-$label-levels.md" ;;
  concurrency)
    cd "$ROOT/backend" && "$PY" -m pytest -q tests/test_approval_concurrency.py "${@:2}" ;;
  scheduler)
    "$PY" "$ROOT/perf/harness/scheduler_bench.py" "${@:2}" ;;
  queries)
    "$PY" "$ROOT/perf/harness/query_profile.py" "${@:2}" ;;
  ai)
    "$PY" "$ROOT/perf/harness/ai_latency.py" "${@:2}" ;;
  *)
    sed -n '2,13p' "$0"; exit 1 ;;
esac
