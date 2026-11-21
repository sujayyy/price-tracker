# Price Tracker · Pitch script

Slides about 8:00, then the live demo about 3:00 (about 11:00 in total).

| Speaker | Part | Time |
|---|---|---|
| Siva Prasad | Slides 1–4: title, real problem, why AI, product | 2:05 |
| Sujay | Slides 5–7: architecture, AI workflow, tech stack | 2:00 |
| Mahesh | Slides 8–10: cost & latency, how we test (with AI evals), load testing | 2:00 |
| Yamini | Slides 11–15: responsible AI, challenges, impact, what's next, thank you | 1:55 |
| Sujay | Live demo, after slide 15 | 3:00 |

## 1. Price Tracker · Siva Prasad · 0:20

- "Hi, we're [team]. This is Price Tracker, an AI pricing assistant for brands that sell on Amazon.in and Flipkart."
- Point at the chips: "We scrape competitor listings, a rules gate spots real changes, an LLM agent recommends our price, and a person approves it."

## 2. The real problem · Siva Prasad · 0:45

- "The real problem: a competitor cuts their price at 2 a.m., and nobody notices until 9:30."
- Walk the chart: "For seven and a half hours we're the more expensive seller, and shoppers buy from the cheaper one."
- "Teams check hundreds of pages by hand, react late and guess the new price. Price Tracker scrapes every listing on a schedule, an AI agent recommends our price, and a person approves it."

## 3. Why AI · Siva Prasad · 0:35

- "Why AI? Deterministic rules spot a price change, but can't tell a flash sale from a lasting cut, or a scraping glitch from a real price. An LLM alone can hallucinate a price or ignore our floor, and costs money on every check."
- "So rules detect, the LLM recommends and explains, guardrails enforce the floor, and a human approves. The LLM only runs when the rules gate fires."

## 4. Meet Price Tracker · Siva Prasad · 0:25

- "This is the dashboard. It shows where we stand against the cheapest competitor, what changed, and what's waiting for a decision."
- "Add a product by name, we watch its listings, the analyst agent recommends a price, and one click approves it. We'll show it live in a moment."
- Hand over: "Sujay will show how it's built."

## 5. Architecture · Sujay · 1:00

- Start with the three tiers: "On top, the React dashboard calls our FastAPI backend over REST and JSON. At the bottom, one PostgreSQL database holds the readings, decisions, audit log and the paused workflows. Inside the backend is the workflow."
- Top row, follow the dot: "Every hour a cron calls our FastAPI endpoint. The scheduler runner loads the listings that are due; if none are due, it skips. The scraper does an HTTP GET with httpx and parses the HTML with BeautifulSoup and lxml, JSON-LD first. Every reading is stored in PostgreSQL."
- "The rules gate compares it with the last reading. No real change: stop, zero LLM calls. Otherwise we group changes by product and check the daily AI budget. No budget, or the AI errors: a fallback that says 'review manually'."
- Middle row: "The AI workflow is LangGraph. The agent, Claude Haiku 4.5 through LangChain, returns a RepricingDecision; guardrails keep it to pre-priced options within the floor and a 10% move. Then it routes: no change, auto-apply for small confident moves, or human review, where `interrupt()` pauses the graph."
- "Every outcome, including the fallback, is saved and emailed to the ops team. When someone approves in the dashboard, the graph resumes, re-checks fresh data, and finalize calls `set_our_price()` and writes the audit row. A rejection or stale data ends with no change."
- **If asked about GitHub Actions:** the cron and CI workflows are written and tested locally; they go live once the repo is pushed to GitHub. In the demo we trigger the run by hand. Press **R** to replay the flow.

## 6. AI workflow · Sujay · 0:35

- "Zooming into the AI part. It's a LangGraph StateGraph. analyze is a tool-calling agent; its tools only read data, and it must return a validated RepricingDecision."
- "guardrails is pure code: our code has already priced the allowed options, clamped to the floor and a 10% max move, so the model picks one and never does arithmetic."
- "Then the router. Hold or investigate ends the run. A small, confident move can auto-apply if the team turned that on. Otherwise human_review pauses the graph, and the dashboard's Approve resumes it with `Command(resume)`. finalize refuses a stale approval."

## 7. Tech stack · Sujay · 0:25

- "Our stack in one line each. Python 3.12 and FastAPI for the backend, Pydantic for validation, httpx with BeautifulSoup and lxml for scraping, and PostgreSQL 16 through SQLAlchemy and Alembic."
- Point at the right column: "The AI side is LangChain for the agent, LangGraph with PostgresSaver for the pausable workflow, Claude Haiku 4.5 as the model, and LangSmith for tracing. The dashboard is React and TypeScript, and Docker Compose runs it all."
- **If asked why Haiku:** code prepares the price options, so the model only judges and explains; it's fast and cheap, and the model is one setting.
- **If asked why LangGraph:** approvals can take hours and arrive in another process; `interrupt()` plus the PostgreSQL checkpoint lets the API resume the run.
- Hand over: "Mahesh will show how we keep it cheap and fast, and how we test it."

## 8. Cost and latency · Mahesh · 0:35

- "To keep cost down, the AI only runs when it has to. The rules gate stops quiet checks with zero LLM calls, changes are grouped so two platforms moving is one AI run, there's a daily budget, call limits per run, and a small model."
- "For speed, code prepares the price options so the model just picks one, which keeps answers short. We batched database reads and added an admission limit after load testing."
- "The result: about a rupee and six seconds per AI decision, and nothing when prices are quiet."
- **If asked for detail:** about 10,000 tokens in and 400 out per decision ($0.012 at $1/$5 per million tokens); slowest run 13.8 s; worst case about ₹200 a day at the 200-run cap.
- **If asked "10× the load":** one API worker levels off near 50 requests a second and 4 workers reached 109; we'd add workers, cache the fixed prompt and tools, and keep Haiku.

## 9. How we test · Mahesh · 0:45

- "We test in four layers. Code tests in pytest cover the rules gate, guardrails, the scrapers on saved Amazon and Flipkart pages, and the real LangGraph runtime with a scripted model, right through to approving over HTTP."
- "AI evals: 13 pricing situations with known answers, run on the real model. Point at the strip: it picked the right move in all 13, every price came from an allowed option, never below the floor, and the evals caught two real bugs we fixed in code."
- "k6 load-tests the backend, and we check endpoints in Postman. The CI pipeline is configured in GitHub Actions; we run the same steps locally until the repo is pushed."
- **If asked for detail:** 128 pytest tests (`pytest`); each eval answer is scored on 7 checks, 90 of 91 passed (one market-read label on a tiny move; the action was right).

## 10. Load testing · Mahesh · 0:40

- "Load testing with k6 found two real bugs. First, one product-list request ran 1,802 SQL statements, an N+1 problem. Batching the reads brought it to 8, with identical responses."
- "Second, at 100 users the server deadlocked: every worker thread was waiting for a database connection held by a request waiting for a thread. An admission limit of 10 concurrent requests fixed it."
- "After both fixes, p95 latency dropped from 6.4 seconds to 282 milliseconds, with zero errors at 150 users. And 200 simultaneous approve clicks never applied a price twice, because of the row lock."
- Hand over: "Yamini on how we keep the AI safe."

## 11. Responsible AI · Yamini · 0:30

- "Responsible AI was designed in. A person decides; auto-apply is opt-in and only for small moves."
- "The floor and max move live in code, not the prompt. The model returns a validated choice from options we priced, so it can't invent a number."
- "Scraped text is data, never instructions, and we have an eval for that. No shopper data is stored, and every decision is in PostgreSQL and traced in LangSmith."

## 12. Challenges · Yamini · 0:30

- "A few problems we hit. The evals caught the AI suggesting a raise while a competitor was cutting; we fixed it in the guardrails, not the prompt. It also claimed we'd be cheapest when we weren't, so every option now carries `gap_after_inr`."
- "Broken readings are marked suspect and re-checked live. Late approvals resume from the checkpoint and are re-validated. Amazon short links needed a GET instead of HEAD, and Flipkart's JavaScript challenge is reported, never bypassed."

## 13. The impact · Yamini · 0:20

- "Before: someone opens every listing by hand and spots cuts the next morning. With Price Tracker, the team gets an email with a recommended price and the reason, and approving is one click, recorded in the audit log."
- "The team stops checking and starts deciding."

## 14. Future enhancements · Yamini · 0:25

- "Next, we'd publish approved prices through Amazon's SP-API and Flipkart's Seller API. Every change already goes through one function, `set_our_price()`, so that's where it plugs in."
- Read the other titles only. "Today, approved prices are saved in Price Tracker, and a person confirms product matches."

## 15. Thank you · Yamini · 0:10

- Read the four lines. "Thank you. Now Sujay will show it working, live."
- **Q&A, who answers what:** problem, users, why AI, the product → Siva Prasad · architecture, AI workflow, tech stack, the demo → Sujay · cost, testing, evals, load tests → Mahesh · responsible AI, challenges, impact, next steps → Yamini.
- If you don't know: "I don't know. Here's how I'd find out."
**→ AFTER THE SLIDES · LIVE DEMO · Sujay · 3:00**
- Open with: "We simulate only the competitor's new price. Everything after it is the real system."
- **Before you present:** backend on :8000 and frontend on :5173, DEMO_ENDPOINTS_ENABLED=true. Open the product page, type the internal secret into the simulator, click "Clear demo readings", and approve or reject any old pending proposal. Check "AI runs today" is well under the limit, keep Gmail open in a second tab, and have a screen recording ready.
- **1. Competitor cuts 10%:** read out the rule that fired, the recommendation and the reasoning. Open Approvals and approve.
- **2. Undercuts our floor:** the proposal stops at the floor.
- **3. Price glitch** (skip and say it in one sentence if you are behind time): the agent re-fetches the live listing, marks it suspect, and recommends investigate, with no price change.
- Show the email in Gmail, then the product's History tab (the audit log). If anything stalls for more than 10 seconds, switch to the recording calmly.
- End with: "That's Price Tracker. We're happy to take your questions." Then Q&A.
