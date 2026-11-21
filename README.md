# Price Tracker: AI competitor price monitoring & repricing

An operations tool for e-commerce teams competing on **Amazon.in** and **Flipkart**. Each of
our products is compared against **the same product on every platform**. It watches those
competitor listings on a schedule, keeps the history in PostgreSQL, and **emails the
operations team whenever a competitor's price moves, up or down**, or they go out of stock.
We always price against the **lowest in-stock competitor across platforms**. Each email carries
an AI analyst's recommendation for **our** price. A recommended change becomes a
proposal that someone approves in the dashboard (or, for small confident moves, is auto-applied)
and every change to our price is recorded in an audit log.

```
competitor price moves ─► rules gate ─► LangGraph workflow ──────────────────────────► ops email
                                         analyze (LLM) → guardrails (code) → ⏸ human approval → apply + audit
```

```
frontend/          React 18 + Vite 5 + TypeScript + Tailwind 3 (ops console; see frontend/DESIGN.md)
backend/           Python 3.12 service: FastAPI + SQLAlchemy 2 + Alembic + psycopg 3
  app/api/         REST routes (products, listings, proposals, activity, monitoring, settings, internal)
  app/ai/          AI layer: LangGraph repricing workflow, LangChain v1 create_agent (analyst +
                   intake), pricing guardrails, prompts, tools, schemas, Postgres checkpointer
  app/services/    scraping, trigger rules (gate), scheduler run, pricing writes, approvals, email
  app/db/          SQLAlchemy models + queries
  evals/           labelled real-LLM scenarios for the repricing analyst
infra/             docker-compose (postgres:16, backend, frontend), .env.example, Postman
perf/              load, stress, spike and soak tests (k6), approval race tests, results report
pitch/             presentation deck (HTML, PPTX, PDF)
```

## Quickstart (local dev)

```bash
# 1. Postgres
cp infra/.env.example infra/.env          # then fill in keys (see "Configuration")
docker compose -f infra/docker-compose.yml up -d postgres

# 2. Python: one package. Pick the provider extra that matches AGENT_MODEL
#    (google, anthropic, openai or ollama).
python3.12 -m venv .venv
.venv/bin/pip install -e "./backend[anthropic,dev]"

# 3. Database: alembic upgrade head + LangGraph checkpoint tables
cd backend && ../.venv/bin/python -m app.cli init-db

# 4. API on :8000
../.venv/bin/uvicorn app.main:app --reload

# 5. Frontend on :5173 (new terminal)
cd frontend && npm install && npm run dev
```

Open http://localhost:5173 → **Add product**: search by name (the AI finds the same product on
Amazon.in and Flipkart and pre-ticks confident matches) or paste listing links, then enter our
SKU, our price and our floor price. Then trigger a check by hand:

```bash
cd backend && ../.venv/bin/python -m app.cli run-once --force
# or through the API, as the scheduler does:
curl -X POST "localhost:8000/internal/run-once?force=true" -H "X-Internal-Secret: $INTERNAL_RUN_SECRET"
```

Product photos are captured from each listing on every fetch (shown in the dashboard only). For
listings added before migration 0005, fetch their photos once without recording a price reading:
`cd backend && ../.venv/bin/python -m app.cli backfill-images`.

Full stack in Docker: `docker compose -f infra/docker-compose.yml up --build`.

## The dashboard

A B2B operations console (React 18 + Vite + TypeScript + Tailwind 3), light and dark. Built
around the decisions an ops team makes (what changed, what we recommend, what to approve),
not around AI features: the UI talks about *recommendations*, *guardrails* and *data freshness*.

- **Overview:** today's pulse (needs attention · awaiting approval · competitor moves and our
  price changes in the last 7 days), a **Needs attention** list where each row is one situation
  ("Amazon.in cut ₹72 to ₹647 · we're at ₹709") with the recommendation and a Review button, a
  **market movement** chart (cuts vs raises per day), a **price position** chart and a
  **recent activity** feed shown as *detected change → recommendation → outcome*.
- **Products:** a dense table (our price, lowest competitor + platform + change, gap,
  competitor stock, recommendation, last checked; trend and frequency columns can be switched on
  in **Columns**), search, filters, sorting, pagination, bulk pause/resume and row actions (Review
  goes straight to that approval). Stacks into a list on phones.
- **Product page:** header with SKU (copyable), live monitoring status ("Checking every 6h · last
  12h ago · next due now"), **Recheck now** and Pause. Tabs **Overview · History · Settings**
  (`?tab=`). Overview: a price-intelligence band (our price, lowest competitor, gap, competitor
  stock, repricing mode), the pending recommendation, a per-platform price chart with our price and
  the floor, the competitor listings, and the demo simulator. History: one timeline of
  recommendations, our price changes and approvals (long reasoning collapses, 20 at a time).
  Settings: pricing rules in sections with a save bar that appears only when something changed.
- **Recommendations** (`/recommendations`): every recommendation from the last 30 days with its
  trigger, suggested price and outcome; a mix bar (lower / raise / hold / investigate), filters by
  action and platform, and expandable reasoning.
- **Approvals** (`/approvals`): a split inbox (queue + decision pane, `?id=` deep links). Each
  **recommendation card** shows the price move, why (reasoning, urgency, confidence), the
  **guardrail checks** computed by the backend (floor, max move, direction), **data freshness**
  ("Data verified 12h ago", **Recheck now**, warnings when the competitor price or our price has
  changed since it was recommended), then Approve / Edit price / Reject. Approval re-validates
  against the latest data before applying.
- **Monitoring** (`/monitoring`): scheduler status, checks and errors in the last 24h,
  recommendation runs against the daily cap, **listing health** (failing first, last check, next
  due, frequency) and recent runs.
- **Add product** (`/add`): a 4-step flow (competitor listings → our product → repricing & alerts
  → review). Pasted links are fetched and previewed (title, price, stock) before anything is
  saved; a link that is already monitored links to that product.
- **Settings** (`/settings`, or click your name): Profile, Alert recipients (the ops team's
  emails, saved in the database, **Send test email**) and Appearance.
- **App shell:** collapsible sidebar (with Add product), top bar with search (**⌘K** palette),
  monitoring status, notifications (pending approvals and failing listings), and a **market tape**
  of the latest competitor move on every listing. Destructive actions use a centred confirm dialog.
  Unknown URLs show a 404 page.

Design system, "Ledger & Petrol" (full spec in `frontend/DESIGN.md`, tokens in
`frontend/src/index.css`): warm paper surfaces, petrol as the brand for primary actions, and
colour kept for **market direction and state**: vermilion = a competitor cut / rejected /
failing, jade = a competitor raise / approved / healthy, saffron = needs attention. Our own
recommended actions (lower / raise / hold) are neutral badges, never alarms. Amazon (tangerine)
and Flipkart (azure) own their colours and nothing else uses them. Type: Geist for UI, Geist Mono
for prices, Instrument Serif only for page titles and the Overview hero. Motion lives in
`src/lib/motion.ts`: short ease-out enters, springs for moving indicators, rolling digits when a
figure changes (never a count-up from zero), no animation on the ⌘K palette, and
`prefers-reduced-motion` respected. Charts are hand-built SVG (no chart library). UI libraries:
`motion`, `lucide-react`, `sonner` (toasts), `cmdk`.

## How it works

```
products (ours: SKU, our price, floor, limits) ──< tracked_items (competitor listings: Amazon.in, Flipkart…)

scheduler ─► POST /internal/run-once
               │
               ▼
      fetch every due listing (per-domain rate-limited) ─► price_observations
               │
               ▼
      gate.py per listing: deterministic rules ── nothing changed ──► done (zero LLM calls, no email)
               │ price_drop · price_increase · out_of_stock · back_in_stock · needs_attention
               ▼
      group changes by product ─► ONE workflow run, ONE email per product per cycle
               ▼
      LangGraph repricing workflow (app/ai/workflow.py, checkpointed in Postgres)
        analyze     LLM analyst, read-only tools ─► RepricingDecision (validated Pydantic)
        guardrails  code: allowed options only, floor, max move, auto-apply eligibility
        ├─ hold / investigate ─────────────────────────────────► done
        ├─ small + confident + auto-apply on ──► finalize ─────► applied (source 'auto')
        └─ otherwise ──► human_review ⏸ interrupt()  … hours later: Approve/Reject in the UI
                          └─► Command(resume=…) ─► finalize: re-check vs fresh data ─► applied
               │
               ▼
      decisions · reprice_proposals · our_price_changes (audit) · ops email · runs
```

- **One product, every platform.** `products` holds our side; each competitor listing is a
  `tracked_items` row under it. The pricing context lists every listing and picks the **lowest
  usable in-stock price** as the reference. A reading far outside a listing's own history is
  marked *suspect* and never used as the reference. If the cheapest platform goes out of stock,
  the next one becomes the reference; we step up only when **every** competitor is out of stock.
  When Amazon.in and Flipkart both move in the same cycle, the product gets one decision.
- **Every competitor change is reported.** Rules fire on *transitions* between two readings
  (a competitor sitting at ₹799 fires once, when it moves there), in either direction. Each item
  can set a minimum move (`min_change_pct`) and whether stock changes alert. Emails go to
  `OPS_ALERT_EMAILS` (plus an optional per-item recipient) and link to the product page.
- **The LLM recommends; code decides what is allowed; a person approves.**
  - `get_pricing_context` hands the model every listing, the lowest (reference) price, our
    position and gap, and a list of **pre-priced options** (hold / lower / raise), already clamped
    to the floor and the max move, each with `gap_after_inr` (where we'd land vs the lowest
    competitor). The model picks an option; it never does arithmetic.
  - `guardrails.enforce` re-checks the choice: a move that wasn't offered becomes *hold*, a
    made-up price is replaced by the allowed one, and nothing is repriced on suspect data.
  - Business rules live in code, not the prompt: never below the floor (binds humans too),
    never more than `max_change_pct` in one move, **never raise while the competitor is
    cutting** (on any platform), and step up half the max move only when every competitor is
    out of stock.
  - Auto-apply only when the item allows it, confidence ≥ 0.85, the move is within
    `auto_apply_max_pct`, it isn't at the floor, and the AI doesn't read it as a flash sale.
- **Why LangGraph.** The approval can take hours and arrive in a different process (the
  scheduler starts the run, the API resumes it). `interrupt()` pauses the graph and the state
  lives in the Postgres checkpointer; `finalize` re-validates against *current* data, so an
  approval is refused as **stale** if our price changed meanwhile. The workflow never writes;
  the backend applies the verdict (`app/services/pricing.py` is the single write path).
- **The agent never has side effects.** Tools only read: pricing context, competitor history
  stats, the latest reading, item settings, and one live refetch that is never stored.
- **Hard limits.** At most 6 model calls and 8 tool calls per run, `refetch_listing` at most
  once (middleware, not just the prompt), and a daily cap on runs
  (`MAX_AGENT_INVOCATIONS_PER_DAY`). Past the cap, or when the model errors, the change is still
  emailed with a clearly labelled *"no AI recommendation, review manually"* decision.
- **Prompt-injection defences.** Tool text is data. Tools refuse to read any other item. Even a
  successful injection can only pick one of the pre-priced options, which a human then approves.
- **Race-safe approvals.** The proposal row is locked (`SELECT … FOR UPDATE`), so a double click
  can't apply twice; a newer competitor change or a manual price edit supersedes open proposals.
- **Postgres everywhere.** App tables come from Alembic; LangGraph's `PostgresSaver` manages
  its own `checkpoint*` tables. There is no SQLite anywhere.

### API

| Method | Path | |
|---|---|---|
| POST | `/api/products` | `listings: [{url}]` (1–10, Amazon.in/Flipkart, short links OK) + `pricing` (SKU, our price, floor, max move, undercut, auto-apply) + `rules` (min change %, stock alerts, interval). Each listing is fetched once |
| GET | `/api/products` | Products with every listing, the lowest competitor, our position/gap and any pending proposal |
| GET / PATCH / DELETE | `/api/products/{id}` | PATCH `our_price_inr` is audited (`changed_by`) and closes open proposals; floor is enforced |
| POST | `/api/products/{id}/listings` | Add another platform's listing `{url}` |
| PATCH / DELETE | `/api/listings/{id}` | Pause/resume `{active}` or remove a listing (history kept) |
| GET | `/api/search?q=` | Find the same product on Amazon.in and Flipkart (AI-scored, grounded in real results; plain search fallback with per-marketplace errors) |
| GET | `/api/products/{id}/history?days=30` | Competitor price points, one series per listing |
| GET | `/api/products/{id}/decisions` | AI decisions (with the platform that triggered them and whether ops was emailed) |
| GET | `/api/products/{id}/our-price-history` | Audit log of our price |
| GET | `/api/activity?days=14&limit=` | Recommendations across all products, with reasoning, confidence and the resulting proposal's status (overview, recommendations page) |
| POST | `/api/products/{id}/recheck` | Fetch every listing of the product now; if a price changed, run the workflow and report whether the pending proposal was replaced |
| POST | `/api/listings/preview` | `{url}`: parse and fetch a listing without saving it (title, price, stock; flags a listing that is already monitored) |
| GET | `/api/monitoring` | Scheduler runs, 24h checks/errors, recommendation runs vs the daily cap, and per-listing health with next due time |
| GET / PUT / DELETE | `/api/settings/team` | The ops team's alert emails: read, save `{ops_alert_emails, updated_by}` (overrides `OPS_ALERT_EMAILS`), or reset to the `.env` default |
| POST | `/api/settings/team/test-email` | Send a test message to the ops team list |
| GET | `/api/proposals?status=pending` · `/api/products/{id}/proposals` | The approval queue; each pending proposal carries guardrail checks and freshness (latest competitor price, when it was checked, whether it or our price changed since) |
| POST | `/api/proposals/{id}/approve` · `/reject` | `{by, price_inr?, note?}`: resumes the paused workflow, re-checks, applies |
| POST | `/internal/run-once?force=` | One cycle. Requires the `X-Internal-Secret` header |
| POST / DELETE | `/internal/demo/price` | Demo only: `{listing_id, price_inr}` / `?product_id=` (see *Demo mode*) |

Interactive docs: http://localhost:8000/docs. Postman: the collection and environment live in
`infra/postman/` (Postman YAML); select "Price Tracker (local)" and set `internal_secret`.

### MCP server (read-only)

The same data is available to any MCP client (an AI assistant or an IDE), so the pricing team can
ask "what's waiting for approval?", "why did the AI propose ₹899 for the JBL Go 4?" or "which
listings are failing?" without opening the dashboard. It lives in `backend/app/mcp/`.

| Tool | Answers |
|---|---|
| `list_products` | Every product: our price, lowest competitor and where, position/gap, pending proposal, last check |
| `get_product` | One product in full: pricing settings and every listing |
| `get_price_history` | Per-listing latest/lowest/highest price plus recent readings (`days`, `max_points`) |
| `list_pending_approvals` | The approval queue with reasoning, guardrail checks and staleness |
| `get_recent_decisions` | The AI's recent decisions for a product, with reasoning and confidence |
| `get_recent_activity` | Recommendations across all products over the last few days |
| `get_monitoring` | Scheduler runs, the daily AI cap and per-listing health |

Every tool is read-only and goes through the same handler as the REST endpoint, so the answers
match the dashboard. Approving, rejecting and editing prices stay in the dashboard, behind the
human approval step; CI fails if `app/mcp` reaches a write path.

Run it over stdio from `backend/` (it reads `DATABASE_URL` from `infra/.env`):

```bash
cd backend && ../.venv/bin/python -m app.mcp
```

Most MCP clients take a config entry like this (use absolute paths):

```json
{
  "mcpServers": {
    "price-tracker": {
      "command": "/path/to/price-tracker/.venv/bin/python",
      "args": ["-m", "app.mcp"],
      "env": { "PYTHONPATH": "/path/to/price-tracker/backend" }
    }
  }
}
```

### Demo mode: simulate a competitor move

Competitor prices rarely move while you're presenting, so an internal endpoint simulates **only
the scraped competitor price**. Everything after it is the production pipeline: rules, the
LangGraph workflow, guardrails, the proposal, the email, approval and the audit log.

Enable it with `DEMO_ENDPOINTS_ENABLED=true` (off by default; keep it off in production). It uses
the same `X-Internal-Secret` header as `/internal/run-once`.

**From the dashboard:** each product page shows *Simulate a competitor move*. Enter the internal
secret once (kept for that browser tab only), choose which platform's listing to simulate, then
pick a scenario: **Competitor cuts 10%**,
**Undercuts our floor**, **Competitor raises 15%**, **Out of stock** / **Back in stock**, or
**Price glitch** (the AI re-checks the live listing and flags it instead of repricing). The panel
shows the rule that fired, the AI recommendation and guardrail notes, whether a proposal is
waiting, and whether the ops team was emailed; the proposal appears at the top of the page to
approve. **Clear demo readings** restores the real competitor history.

A good 3-minute demo: on a product with Amazon.in **and** Flipkart listings, simulate
*Competitor cuts 10%* on **Flipkart** → Flipkart becomes *lowest* and the proposal is priced
against it → approve → *Undercuts our floor* (the guardrail stops at the floor) → *Price glitch*
(marked suspect, investigate, no price change) → show the ops email (a price table for every
platform) and the price log.

**From the command line or Postman** (the `Demo` folder):

```bash
curl -X POST localhost:8000/internal/demo/price -H "X-Internal-Secret: $INTERNAL_RUN_SECRET" \
     -H "Content-Type: application/json" -d '{"listing_id": 5, "price_inr": 719}'
curl -X POST localhost:8000/internal/demo/price -H "X-Internal-Secret: $INTERNAL_RUN_SECRET" \
     -H "Content-Type: application/json" -d '{"listing_id": 5, "in_stock": false}'
curl -X DELETE "localhost:8000/internal/demo/price?product_id=1" -H "X-Internal-Secret: $INTERNAL_RUN_SECRET"
```

The panel also shows **AI runs today / daily limit** (`MAX_AGENT_INVOCATIONS_PER_DAY`, from
`/health`). Once the limit is reached, changes are still stored and emailed but get a labelled
"no AI recommendation" decision and no proposal, and the panel says so; raise the limit for a
demo day and restart the backend.

A simulated reading counts as a check, so it delays that item's next real scrape; clearing the
demo readings restores the schedule. Decisions, proposals and our price log are kept (they
really happened).

## Configuration (`infra/.env`)

| Variable | Notes |
|---|---|
| `DATABASE_URL` | `postgresql+psycopg://…` |
| `AGENT_MODEL` | Any `provider:model` string for LangChain's `init_chat_model`, e.g. `anthropic:claude-haiku-4-5`. Install the matching extra |
| `AI_PROVIDER` | The same extra for the backend Docker image (`google`, `anthropic`, `openai`, `ollama`) |
| `GOOGLE_API_KEY` / `ANTHROPIC_API_KEY` / … | Key for your provider. Without it, monitoring and emails still work with the rule-only fallback; natural-language add returns 503 |
| `OPS_ALERT_EMAILS` | Default ops team addresses (comma-separated); every competitor alert goes here. The list can be changed from the dashboard (**Settings → Alert recipients**), which overrides this until reset |
| `DASHBOARD_URL` | Base URL for the "Review & approve" link in emails (default `http://localhost:5173`) |
| `MAX_AGENT_INVOCATIONS_PER_DAY` | Cost cap on AI runs |
| `ALERT_MIN_CONFIDENCE`, `AUTO_APPLY_MIN_CONFIDENCE` | Below the first, proposals are flagged "review carefully"; auto-apply needs the second (default 0.85) |
| `SECOND_OPINION_ENABLED`, `SECOND_OPINION_MODEL` | The critic agent that reviews each proposed price change (default on; model defaults to `AGENT_MODEL`) |
| `SMTP_USER`, `SMTP_APP_PASSWORD`, `SMTP_PORT` | Gmail address and a [Google app password](https://myaccount.google.com/apppasswords). 587 = STARTTLS (default), 465 = implicit TLS |
| `INTERNAL_RUN_SECRET` | Shared secret for `/internal/*`. `python -c "import secrets;print(secrets.token_urlsafe(32))"` |
| `DEMO_ENDPOINTS_ENABLED` | `true` enables `/internal/demo/price` and the dashboard demo panel |
| `LANGSMITH_TRACING`, `LANGSMITH_API_KEY` | Traces for every workflow run (analyze → guardrails → review → finalize) |
| `SOURCE_MIN_INTERVAL_SECONDS` | Minimum gap between requests to the same marketplace domain |
| `API_MAX_CONCURRENCY`, `API_QUEUE_TIMEOUT_SECONDS` | At most this many `/api` requests run at once (default 10); the rest wait up to the timeout (default 10 s), then get 503. Prevents a thread/connection-pool deadlock under bursts (see `perf/REPORT.md`) |

## Scheduling

- **Locally:** a crontab entry such as
  `17 * * * * cd /path/to/price-tracker/backend && ../.venv/bin/python -m app.cli run-once`
- **GitHub Actions:** `.github/workflows/check-prices.yml` calls `/internal/run-once` every
  hour. Set the repository secrets `BACKEND_URL` and `INTERNAL_RUN_SECRET`; the backend must be
  reachable from the internet. Each item's `check_every_hours` decides what is actually fetched.

## Tests, lint, evals

```bash
(cd backend && ../.venv/bin/pytest -q)   # 134 tests: API, gate, guardrails, workflow, approvals, runner, parsers, races, MCP
.venv/bin/ruff check backend
(cd frontend && npm run typecheck)
```

Backend tests use a separate `tracker_test` Postgres database. The workflow tests run the real
LangGraph runtime (interrupt/resume) with a scripted model, and `test_proposals.py` goes end to
end: competitor drop → paused workflow → approve over HTTP → price applied and audited.
`.github/workflows/ci.yml` also enforces the architecture: `app/ai` never imports FastAPI or
web/DB code, LangChain/LangGraph are only imported inside `app/ai`, and there is no SQLite.

The **evals** run 13 labelled repricing scenarios against a real model: a sustained competitor
cut, a cut while we're still cheaper, a cut below our floor, a floor that blocks any cut, a raise
opportunity, competitor out of stock / back in stock, a price glitch disproved by the refetch, a
flash-sale pattern, a prompt injection in the title, a minor fluctuation, and two multi-platform
cases (Flipkart undercuts while Amazon holds; the cheapest platform goes out of stock). Metrics: action,
event, **price copied from a guardrail option**, urgency, market read, reasoning cites a number,
reasoning ≤ 3 sentences.

```bash
cd backend
../.venv/bin/dotenv -f ../infra/.env run -- ../.venv/bin/python -m evals.evaluators --model anthropic:claude-haiku-4-5
../.venv/bin/dotenv -f ../infra/.env run -- ../.venv/bin/python -m evals.dataset_builder --push price-tracker-repricing   # optional
../.venv/bin/dotenv -f ../infra/.env run -- ../.venv/bin/python -m evals.evaluators --model … --langsmith price-tracker-repricing
```

With `anthropic:claude-haiku-4-5` the analyst picks an acceptable action in 13/13 scenarios and passes
90 of 91 checks (runs on 30 Sept and 2 Oct 2026; the one miss is a market-read label on the minor
fluctuation scenario, where the action, hold, was right). Earlier runs
exposed real gaps (a raise offered after a competitor cut; "undercuts" claimed for a capped cut
that left us above the competitor); both fixes went into the guardrails' data (no raise into a
falling market; `gap_after_inr` on every option), not just the prompt.

## Performance and load testing

`perf/` load-tests an isolated copy of the backend with k6 (its own database and port; scrapers, model and
email faked or switched off), using the dashboard's real request mix. It found and fixed two bottlenecks:
the list endpoints ran one query per listing (`/api/products`: 1,802 SQL statements per request, now 8;
responses byte-for-byte identical), and under bursts the worker threads and the database connection pool
deadlocked (fixed with a small admission limit, `app/core/admission.py`).

| Same test, same data (1 uvicorn worker) | Before | After |
|---|---:|---:|
| Load test (5 → 50 users), p95 | 6.4 s | 282 ms |
| Stress test (to 150 users), errors | 13.5% | 0% (11,068 requests) |
| Spike test (10 → 100 → 10), errors / recovery | 9% / about 60 s | 0% / under 10 s |
| 30-minute soak, 10 users | | 0 errors, p95 flat at 130–134 ms, memory stable |

Approval races are tested too: 10 simultaneous approvals of one proposal apply the price exactly once,
and with the row lock removed the same test applies it 10 times. Numbers are from one laptop and are a
regression baseline, not a capacity claim. Full method and results: [`perf/REPORT.md`](perf/REPORT.md);
how to run: [`perf/README.md`](perf/README.md).

## Known limitations

- **Applying a price updates our catalogue price in this database.** Pushing it to a sales
  channel (Amazon Seller Central / SP-API, Flipkart Seller Hub, Shopify) is one call in
  `app/services/pricing.py::set_our_price`.
- **Matching the exact same product across platforms needs a human check.** The intake agent
  scores matches (model, colour, storage), but a different colour or bundle can look alike, so
  confident matches are pre-ticked and a person confirms.
- **Scraping is best-effort.** Amazon.in parses well today; Flipkart sometimes serves a
  JavaScript challenge, reported as `blocked:` (never bypassed).
- **No login yet.** The reviewer name is typed in the dashboard; put `/api/*` behind SSO before
  real use.

## Where this differs from the original build spec

- **Product direction:** the spec described a personal deal tracker. This version is an
  operations tool: alerts on any competitor move, our price vs theirs, AI repricing proposals,
  approvals, auto-apply limits and an audit log (migration `0002_ops_repricing`), and each of our
  products compared against its listings on every platform (migration `0003`, which turned each
  existing item into a product with one listing, keeping ids; `/items/:id` links redirect). Decisions
  stored by the earlier version still show in the feed, labelled *legacy*.
- **One Python service instead of `backend/` + `ai-layer/`.** The AI layer lives in
  `backend/app/ai/`; the boundary is enforced by CI and the `DataProvider` protocol.
- **LangGraph StateGraph around the agent** (analyze → guardrails → human_review → finalize)
  instead of a single agent call, for durable human-in-the-loop approval.
- **Scheduled workflow location:** `.github/workflows/`, because GitHub only runs workflows there.
