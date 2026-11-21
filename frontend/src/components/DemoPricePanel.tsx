import { useCallback, useEffect, useState } from "react";
import { ApiError, clearSimulatedPrices, getHealth, simulatePrice } from "../api/client";
import type { DemoPriceIn, DemoPriceResult, Health, Product } from "../types";
import { ACTION_LABEL, EVENT_LABEL, MARKETPLACE_LABEL, MARKET_READ_LABEL, formatInr } from "../lib/format";
import Icon, { type IconName } from "./Icon";

// Kept for this browser tab only; the internal secret is never built into the frontend bundle.
const SECRET_KEY = "price-tracker.internal-secret";

function loadSecret(): string {
  try {
    return sessionStorage.getItem(SECRET_KEY) ?? "";
  } catch {
    return "";
  }
}

function storeSecret(value: string) {
  try {
    if (value) sessionStorage.setItem(SECRET_KEY, value);
    else sessionStorage.removeItem(SECRET_KEY);
  } catch {
    /* storage unavailable: the secret just isn't remembered */
  }
}

function emailOutcome(reason: string, emailed: boolean): { text: string; ok: boolean } {
  if (emailed) return { text: "Ops team emailed", ok: true };
  switch (reason) {
    case "email_not_configured":
      return { text: "Email not sent: Gmail isn't configured (SMTP_USER / SMTP_APP_PASSWORD in infra/.env)", ok: false };
    case "no_recipients":
      return { text: "Email not sent: set OPS_ALERT_EMAILS in infra/.env", ok: false };
    case "email_failed":
      return { text: "Email failed to send: see the run notes", ok: false };
    default:
      return { text: `Email not sent: ${reason}`, ok: false };
  }
}

interface Scenario {
  label: string;
  hint: string;
  icon: IconName;
  body: Omit<DemoPriceIn, "listing_id">;
}

export default function DemoPricePanel({ product, onChanged }: { product: Product; onChanged: () => void }) {
  const active = product.listings.filter((l) => l.active);
  const [listingId, setListingId] = useState<number | null>(active[0]?.id ?? null);
  const listing = active.find((l) => l.id === listingId) ?? active[0];
  const [secret, setSecret] = useState(loadSecret);
  const [editingSecret, setEditingSecret] = useState(!loadSecret());
  const [price, setPrice] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<DemoPriceResult | null>(null);
  const [cleared, setCleared] = useState<number | null>(null);
  const [ai, setAi] = useState<Health["ai"]>();
  const loadAi = useCallback(() => getHealth().then((h) => setAi(h.ai)).catch(() => {}), []);
  useEffect(() => {
    loadAi();
  }, [loadAi]);
  const aiExhausted = ai != null && ai.runs_today >= ai.daily_limit;

  const outOfStock = listing?.latest?.in_stock === false;
  const c = listing?.latest?.price_inr ?? listing?.previous_price_inr ?? product.our_price_inr ?? 1000;
  const floor = product.floor_price_inr;
  const scenarios: Scenario[] = outOfStock
    ? [{ label: "Back in stock", hint: `at ${formatInr(c)}`, icon: "package", body: { price_inr: c } }]
    : [
        { label: "Competitor cuts 10%", hint: formatInr(Math.round(c * 0.9)), icon: "down", body: { price_inr: Math.round(c * 0.9) } },
        ...(floor != null
          ? [{ label: "Undercuts our floor", hint: formatInr(Math.round(floor * 0.95)), icon: "shield" as IconName, body: { price_inr: Math.round(floor * 0.95) } }]
          : []),
        { label: "Competitor raises 15%", hint: formatInr(Math.round(c * 1.15)), icon: "up", body: { price_inr: Math.round(c * 1.15) } },
        { label: "Out of stock", hint: "listing unavailable", icon: "package", body: { in_stock: false } },
        { label: "Price glitch", hint: `${formatInr(Math.max(1, Math.round(c * 0.05)))} · re-checked live`, icon: "alert", body: { price_inr: Math.max(1, Math.round(c * 0.05)) } },
      ];

  function fail(err: unknown) {
    if (err instanceof ApiError && err.status === 401) {
      storeSecret("");
      setEditingSecret(true);
      setError("Wrong internal secret. Use INTERNAL_RUN_SECRET from infra/.env.");
    } else {
      setError(err instanceof ApiError ? err.message : String(err));
    }
  }

  async function run(key: string, body: Omit<DemoPriceIn, "listing_id">) {
    if (!listing) return;
    if (!secret) {
      setEditingSecret(true);
      setError("Enter the internal secret first.");
      return;
    }
    setBusy(key);
    setError(null);
    setCleared(null);
    try {
      storeSecret(secret);
      setEditingSecret(false);
      setResult(await simulatePrice(secret, { listing_id: listing.id, ...body }));
      onChanged();
      loadAi();
    } catch (err) {
      fail(err);
    } finally {
      setBusy(null);
    }
  }

  async function clear() {
    setBusy("clear");
    setError(null);
    try {
      const res = await clearSimulatedPrices(secret, product.id);
      setCleared(res.deleted_observations);
      setResult(null);
      onChanged();
    } catch (err) {
      fail(err);
    } finally {
      setBusy(null);
    }
  }

  const trigger = result?.run.triggers[0];
  const d = result?.decision;
  const customPrice = Number(price);

  return (
    <section className="relative rounded-[12px] border border-dashed border-line-strong bg-[repeating-linear-gradient(135deg,rgb(var(--sunken)/0.4)_0_10px,transparent_10px_20px)] p-4 sm:p-5" aria-labelledby="demo-title">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="demo-title" className="flex flex-wrap items-center gap-2 text-[14px] font-semibold">
            <span className="code rounded-[4px] bg-ink px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-surface">Demo</span>
            <Icon name="flask" className="h-4 w-4 text-muted" />Simulate a competitor move
          </h2>
          <p className="mt-1 text-xs text-muted">Only the scraped competitor price is simulated. The real rules, recommendation, guardrails, approvals and email run.</p>
          {ai && (
            <p className={`mt-1 text-xs ${aiExhausted ? "font-medium text-bad" : "text-muted"}`}>
              Recommendation runs today: {ai.runs_today} / {ai.daily_limit}
              {aiExhausted && " · limit reached: changes are recorded and emailed, but without a recommendation or proposal"}
            </p>
          )}
        </div>
        {editingSecret ? (
          <div className="w-full sm:w-64">
            <label className="label" htmlFor="demo-secret">Internal secret</label>
            <input id="demo-secret" className="input" type="password" autoComplete="off" placeholder="INTERNAL_RUN_SECRET"
              value={secret} onChange={(e) => setSecret(e.target.value.trim())} />
          </div>
        ) : (
          <p className="text-xs text-muted">
            Secret saved for this tab ·{" "}
            <button className="cursor-pointer font-medium text-ink underline-offset-2 hover:underline" onClick={() => setEditingSecret(true)}>change</button>
          </p>
        )}
      </div>

      {active.length === 0 ? (
        <p className="mt-4 text-sm text-muted">Add or resume a competitor listing to simulate its price.</p>
      ) : (
        <div className="mt-4 flex flex-wrap items-center gap-2" role="radiogroup" aria-label="Which platform's price to simulate">
          <span className="text-xs text-muted">Simulate on:</span>
          {active.map((l) => (
            <button key={l.id} role="radio" aria-checked={listing?.id === l.id} onClick={() => { setListingId(l.id); setResult(null); }}
              className={`inline-flex min-h-[32px] cursor-pointer items-center gap-1.5 rounded-full border px-3 py-1 text-xs transition-colors duration-150 ${listing?.id === l.id ? "border-ink bg-ink text-surface" : "border-line bg-raised text-muted hover:text-ink"}`}>
              {MARKETPLACE_LABEL[l.marketplace]} · {l.latest?.in_stock === false ? "out of stock" : formatInr(l.latest?.price_inr)}
            </button>
          ))}
        </div>
      )}

      <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {scenarios.map((s) => (
          <button key={s.label} className="btn-ghost h-auto justify-start py-2.5 text-left" disabled={!!busy || !listing} onClick={() => run(s.label, s.body)}>
            <Icon name={s.icon} className="h-4 w-4 text-muted" />
            <span className="min-w-0">
              <span className="block">{busy === s.label ? "Running…" : s.label}</span>
              <span className="block text-xs font-normal text-muted">{s.hint}</span>
            </span>
          </button>
        ))}
      </div>

      <div className="mt-3 flex flex-wrap items-end gap-2">
        <div className="w-36">
          <label className="label" htmlFor="demo-price">Custom price (₹)</label>
          <input id="demo-price" className="input tabular-nums" type="number" min={1} value={price} onChange={(e) => setPrice(e.target.value)} />
        </div>
        <button className="btn border border-ink bg-ink text-surface hover:bg-ink/90" disabled={!!busy || !listing || !(customPrice > 0)} onClick={() => run("custom", { price_inr: customPrice })}>
          {busy === "custom" ? "Running…" : "Simulate"}
        </button>
        <button className="btn-ghost ml-auto" disabled={!!busy || !secret} onClick={clear}>
          <Icon name="history" />Clear demo readings
        </button>
      </div>

      {error && <p role="alert" className="mt-3 text-sm text-bad">{error}</p>}
      {cleared != null && <p className="mt-3 text-sm text-muted">Removed {cleared} simulated reading{cleared === 1 ? "" : "s"} across this product's listings; the real competitor history is back. Our price and its log are unchanged.</p>}

      {result && (
        <div className="mt-4 space-y-3 rounded-[8px] border border-line bg-raised p-4 text-[13px]" aria-live="polite">
          <p className="tabular-nums">
            <span className="text-muted">{MARKETPLACE_LABEL[result.marketplace]}</span> {formatInr(result.previous_price_inr)} →{" "}
            <b>{result.observation.in_stock === false ? "out of stock" : formatInr(result.simulated_price_inr)}</b>
            <span className="text-muted"> · lowest competitor </span>
            {result.lowest_price_inr != null ? <>{formatInr(result.lowest_price_inr)} on {result.lowest_marketplace ? MARKETPLACE_LABEL[result.lowest_marketplace] : "—"}</> : "none in stock"}
            <span className="text-muted"> · our price </span>{formatInr(result.our_price_before_inr)}
            {result.our_price_after_inr !== result.our_price_before_inr && <> → <b className="text-good">{formatInr(result.our_price_after_inr)}</b></>}
          </p>
          {d?.data_issues.some((n) => n.startsWith("llm_unavailable")) && (
            <div role="alert" className="flex gap-2 rounded-lg border border-bad/30 bg-bad/5 p-3 text-sm text-bad">
              <Icon name="alert" className="mt-0.5" />
              <span>
                <b>No recommendation was made</b> ({d.data_issues.find((n) => n.startsWith("llm_unavailable"))?.replace("llm_unavailable: ", "")}), so
                no price was proposed. {d.data_issues.some((n) => n.includes("daily agent cap"))
                  ? "Raise MAX_AGENT_INVOCATIONS_PER_DAY in infra/.env and restart the backend (or wait until midnight UTC)."
                  : "Check the model key (ANTHROPIC_API_KEY / AGENT_MODEL) in infra/.env."}
              </span>
            </div>
          )}
          {trigger ? (
            <>
              <ol className="space-y-2">
                <li className="flex gap-2"><Icon name="zap" className="mt-0.5 text-muted" /><span><span className="text-muted">Rule fired:</span> <b>{EVENT_LABEL[trigger.trigger] ?? trigger.trigger}</b></span></li>
                {d && (
                  <li className="flex gap-2">
                    <Icon name="insight" className="mt-0.5 text-muted" />
                    <span>
                      <span className="text-muted">Recommendation:</span> <b>{ACTION_LABEL[d.action]}{d.recommended_price_inr != null && <> → {formatInr(d.recommended_price_inr)}</>}</b>
                      <span className="text-muted"> · {MARKET_READ_LABEL[d.market_read]} · {d.urgency} urgency · {Math.round(d.confidence * 100)}%</span>
                      <span className="mt-1 block text-muted">“{d.reasoning}”</span>
                      {d.data_issues.map((n) => <span key={n} className="mt-1 flex gap-1.5 text-xs text-warn"><Icon name="shield" className="mt-0.5 h-3 w-3" />{n}</span>)}
                    </span>
                  </li>
                )}
                <li className="flex gap-2">
                  <Icon name={trigger.proposal_status === "pending" ? "clock" : trigger.proposal_status === "auto_applied" ? "check" : "minus"} className="mt-0.5 text-warn" />
                  <span>
                    {trigger.proposal_status === "pending"
                      ? <><b>Waiting for approval.</b> The workflow is paused; approve or reject it in the card at the top of this page.</>
                      : trigger.proposal_status === "auto_applied"
                        ? <><b>Auto-applied</b> within this product's auto-apply limit.</>
                        : "No price change proposed."}
                  </span>
                </li>
                <li className="flex gap-2">
                  <Icon name="mail" className={`mt-0.5 ${trigger.emailed ? "text-good" : "text-muted"}`} />
                  <span className={trigger.emailed ? "text-good" : "text-muted"}>{emailOutcome(trigger.reason, trigger.emailed).text}</span>
                </li>
              </ol>
            </>
          ) : (
            <p className="text-muted">No rule fired (the price didn't change, or the move was under the alert threshold), so no recommendation was needed and no email was sent.</p>
          )}
        </div>
      )}
    </section>
  );
}
