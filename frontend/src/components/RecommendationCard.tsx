import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { ApiError, approveProposal, recheckProduct, rejectProposal } from "../api/client";
import type { Proposal } from "../types";
import { MARKETPLACE_LABEL, MARKET_READ_LABEL, STATUS_LABEL, formatDateTime, formatInr, formatPct, loadReviewer, shortTitle, timeAgo } from "../lib/format";
import { EASE_OUT, PRESS_SPRING } from "../lib/motion";
import Icon from "./Icon";
import { ActionBadge, ConfidenceBar, PlatformDot, ProductThumb, Status } from "./ui/Primitives";

const STATUS_TONE = {
  pending: "warn",
  approved: "good",
  auto_applied: "good",
  rejected: "bad",
  superseded: "muted",
  stale: "muted",
  failed: "bad",
} as const;

type Phase = "idle" | "rechecking" | "validating" | "approved" | "rejecting";

/** Notes the critic agent adds to decision.data_issues (backend: app/ai/guardrails.py SECOND_OPINION). */
const SECOND_OPINION = "second opinion: ";

function secondOpinion(issues: string[] | undefined) {
  const notes = (issues ?? []).filter((n) => n.startsWith(SECOND_OPINION)).map((n) => n.slice(SECOND_OPINION.length));
  if (!notes.length) return null;
  const concerns = notes.filter((n) => n.startsWith("concern: ")).map((n) => n.slice("concern: ".length));
  const agrees = notes.find((n) => n.startsWith("agrees"));
  const unavailable = notes.some((n) => n.startsWith("unavailable"));
  const escalated = notes.some((n) => n.startsWith("sent to a person"));
  return { concerns, agrees: agrees?.replace(/^agrees\.?\s*/, ""), unavailable, escalated };
}

interface Props {
  proposal: Proposal;
  onResolved: () => void;
  showProduct?: boolean;
  /** Borderless, for a pane that already frames it (the approvals inbox). */
  flush?: boolean;
}

/**
 * A recommended price change as a structured decision: what, why, which rules it passed, how
 * fresh the data is, and the approval controls. Not a chat: decision support.
 */
export default function RecommendationCard({ proposal: p, onResolved, showProduct = false, flush = false }: Props) {
  const reviewer = loadReviewer();
  const [name, setName] = useState(reviewer);
  const [note, setNote] = useState("");
  const [override, setOverride] = useState<string | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [verifiedAt, setVerifiedAt] = useState<string | null>(p.latest_checked_at);
  const [error, setError] = useState<string | null>(null);
  const d = p.decision;
  const opinion = secondOpinion(d?.data_issues);
  const pending = p.status === "pending";
  const price = override != null ? Number(override) : p.to_price_inr;
  const warnings = [
    p.our_price_changed && "Our price changed since this was recommended. Approving will be refused as stale.",
    p.competitor_changed && `The lowest competitor is now ${formatInr(p.latest_competitor_price_inr)} (was ${formatInr(p.competitor_price_inr)}). Recheck before approving.`,
  ].filter(Boolean) as string[];

  async function recheck() {
    setPhase("rechecking");
    setError(null);
    try {
      const r = await recheckProduct(p.product_id);
      if (r.proposal_replaced) {
        toast.warning("A competitor moved: the recommendation was updated", { description: p.product_title });
        onResolved();
        return;
      }
      setVerifiedAt(r.checked_at);
      toast.success(r.changed ? "Rechecked: a change was recorded" : "Data verified: no competitor change", { description: `${r.checked} listing${r.checked === 1 ? "" : "s"} checked` });
      setPhase("idle");
    } catch (err) {
      setError(err instanceof ApiError ? `We couldn't refresh competitor data: ${err.message}. The last reading is still shown.` : String(err));
      setPhase("idle");
    }
  }

  async function approve() {
    if (!name.trim()) {
      setError("Enter your name: it goes into the price log.");
      return;
    }
    if (override != null && !(Number(override) > 0)) {
      setError("Enter a valid price.");
      return;
    }
    setPhase("validating");
    setError(null);
    try {
      const res = await approveProposal(p.id, { by: name.trim(), price_inr: override != null ? Number(override) : null, note: note.trim() || null });
      if (res.status === "approved") {
        setPhase("approved");
        toast.success(`Price set to ${formatInr(res.final_price_inr ?? res.to_price_inr)}`, { description: `${res.product_title} · approved by ${res.resolved_by}` });
        window.setTimeout(onResolved, 900);
      } else {
        setPhase("idle");
        toast.warning(`Not applied: ${STATUS_LABEL[res.status].toLowerCase()}`, { description: res.resolution_note ?? undefined });
        onResolved();
      }
    } catch (err) {
      setPhase("idle");
      setError(err instanceof ApiError ? err.message : String(err));
    }
  }

  async function reject() {
    if (!name.trim()) {
      setError("Enter your name: it goes into the price log.");
      return;
    }
    setPhase("rejecting");
    setError(null);
    try {
      const res = await rejectProposal(p.id, { by: name.trim(), note: note.trim() || null });
      toast("Recommendation rejected", { description: `${res.product_title} stays at ${formatInr(res.from_price_inr)}` });
      onResolved();
    } catch (err) {
      setPhase("idle");
      setError(err instanceof ApiError ? err.message : String(err));
    }
  }

  const busy = phase !== "idle";

  return (
    <article className={flush ? "relative" : "card relative overflow-hidden"} aria-label={`Recommendation: ${ACTION_TITLE[p.action]}`}>
      {pending && !flush && <div className="absolute inset-y-0 left-0 w-[3px] bg-warn-fill" aria-hidden />}

      {/* Header: what kind of decision, its state, where it came from */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-line px-5 py-3.5 sm:px-6">
        <span className="eyebrow">Proposed change</span>
        <ActionBadge action={p.action} />
        {pending ? <Status tone="warn">Approval required</Status> : <Status tone={STATUS_TONE[p.status]}>{STATUS_LABEL[p.status]}</Status>}
        <span className="ml-auto inline-flex items-center gap-1.5 text-[12px] text-muted" title={formatDateTime(p.created_at)}>
          {p.marketplace && <><PlatformDot marketplace={p.marketplace} />{MARKETPLACE_LABEL[p.marketplace]} moved · </>}{timeAgo(p.created_at)}
        </span>
      </div>

      {showProduct && (
        <div className="flex flex-wrap items-end justify-between gap-3 border-b border-line px-5 py-4 sm:px-6">
          <div className="flex min-w-0 items-center gap-4">
            <ProductThumb src={p.product_image_url} size={60} className="rounded-[10px]" />
            <div className="min-w-0">
              <Link to={`/products/${p.product_id}`} className="display line-clamp-1 text-[28px] leading-tight hover:underline" title={p.product_title}>{shortTitle(p.product_title)}</Link>
              {p.our_sku && <span className="code text-muted">{p.our_sku}</span>}
            </div>
          </div>
          <Link to={`/products/${p.product_id}`} className="link-quiet">Price history and listings<Icon name="arrowRight" className="h-3 w-3" /></Link>
        </div>
      )}

      <div className={`grid gap-6 px-5 py-5 sm:px-6 ${flush ? "2xl:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)] 2xl:gap-8" : "lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)] lg:gap-8"}`}>
        {/* The ticket: what moves, and why */}
        <div className="space-y-5">
          <div className="rounded-[10px] border border-line bg-sunken/40">
            <div className="flex flex-wrap items-end gap-x-5 gap-y-3 px-4 pb-4 pt-3.5">
              <div>
                <div className="eyebrow">Our price now</div>
                <div className="mono mt-1.5 text-[20px] text-muted line-through decoration-faint decoration-1">{formatInr(p.from_price_inr)}</div>
              </div>
              <Icon name="arrowRight" className="mb-2 h-5 w-5 text-faint" />
              <div>
                <div className="eyebrow">{pending ? "Proposed" : "Set to"}</div>
                <div className="mono mt-1 text-[40px] font-semibold leading-none tracking-[-0.04em]">{formatInr(p.final_price_inr ?? price)}</div>
              </div>
              <span className="mono mb-1 rounded-[5px] border border-line-strong bg-raised px-1.5 py-0.5 text-[12px] font-medium">{formatPct(p.change_pct)}</span>
            </div>
            <dl className="grid grid-cols-2 border-t border-line text-[12px] sm:grid-cols-3">
              <div className="px-4 py-2.5">
                <dt className="text-muted">Lowest rival</dt>
                <dd className="mono mt-0.5 text-[14px] font-medium">{formatInr(p.competitor_price_inr)}</dd>
              </div>
              <div className="border-l border-line px-4 py-2.5">
                <dt className="text-muted">Our floor</dt>
                <dd className="mono mt-0.5 text-[14px] font-medium">{formatInr(p.floor_price_inr)}</dd>
              </div>
              <div className="col-span-2 border-t border-line px-4 py-2.5 sm:col-span-1 sm:border-l sm:border-t-0">
                <dt className="text-muted">Gap after</dt>
                <dd className="mono mt-0.5 text-[14px] font-medium">
                  {p.competitor_price_inr != null ? <>{price - p.competitor_price_inr > 0 ? "+" : price - p.competitor_price_inr < 0 ? "−" : ""}{formatInr(Math.abs(price - p.competitor_price_inr))}</> : "—"}
                  {p.limited_by && <span className="block font-sans text-[11px] font-medium text-warn">Held at {p.limited_by === "floor" ? "the floor" : "the max move"}</span>}
                </dd>
              </div>
            </dl>
          </div>

          {d && (
            <figure>
              <blockquote className="border-l-2 border-brand/70 pl-4 text-[14px] leading-relaxed text-ink">{d.reasoning}</blockquote>
              <figcaption className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1.5 pl-4 text-[12px] text-muted">
                <span className="inline-flex items-center gap-1.5 font-medium text-ink"><Icon name="insight" className="h-3.5 w-3.5 text-muted" />Pricing analyst</span>
                <span>{MARKET_READ_LABEL[d.market_read]}</span>
                <span>{d.urgency.charAt(0).toUpperCase() + d.urgency.slice(1)} urgency</span>
                <ConfidenceBar value={d.confidence} />
              </figcaption>
            </figure>
          )}

          {opinion && (
            <figure className={`rounded-[10px] border px-4 py-3 ${opinion.concerns.length || opinion.unavailable ? "border-warn/40 bg-warn/5" : "border-line bg-raised"}`}>
              <figcaption className="flex items-center gap-1.5 text-[12px] font-medium text-ink">
                <Icon name={opinion.concerns.length || opinion.unavailable ? "shield" : "check"} className={`h-3.5 w-3.5 ${opinion.concerns.length || opinion.unavailable ? "text-warn" : "text-good"}`} />
                Second opinion
                <span className="font-normal text-muted">
                  {opinion.concerns.length ? "· raised concerns" : opinion.unavailable ? "· not available" : "· agrees"}
                </span>
              </figcaption>
              {opinion.concerns.length > 0 ? (
                <ul className="mt-2 space-y-1.5 text-[13px] leading-relaxed text-ink">
                  {opinion.concerns.map((c) => <li key={c} className="flex gap-2"><span className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-warn" aria-hidden />{c}</li>)}
                </ul>
              ) : opinion.agrees ? (
                <p className="mt-1.5 text-[13px] leading-relaxed text-muted">{opinion.agrees}</p>
              ) : opinion.unavailable ? (
                <p className="mt-1.5 text-[13px] leading-relaxed text-muted">The reviewing agent could not run, so this change waits for a person.</p>
              ) : null}
              {opinion.escalated && (
                <p className="mt-2 text-[12px] text-warn">Sent to you instead of being applied automatically.</p>
              )}
            </figure>
          )}
        </div>

        {/* Rules and freshness */}
        <div className="space-y-4">
          <div>
            <div className="eyebrow">Guardrails</div>
            <ul className="mt-2.5 space-y-2.5">
              {p.guardrails.map((g) => (
                <li key={g.key} className="flex gap-2.5 text-[13px]">
                  <span className={`mt-0.5 grid h-[18px] w-[18px] shrink-0 place-items-center rounded-full ${g.passed === false ? "bg-bad/15 text-bad" : g.passed ? "bg-good/15 text-good" : "bg-sunken text-muted"}`} aria-hidden>
                    <Icon name={g.passed === false ? "x" : g.passed ? "check" : "minus"} className="h-3 w-3" />
                  </span>
                  <span>
                    <span>{g.label}</span>
                    <span className="sr-only">{g.passed === false ? " (failed)" : g.passed ? " (passed)" : " (not configured)"}</span>
                    {g.detail && <span className="block text-[12px] text-muted">{g.detail}</span>}
                  </span>
                </li>
              ))}
            </ul>
          </div>

          {pending && (
            <div className="rounded-[10px] border border-line bg-raised px-3.5 py-3">
              <div className="flex items-center justify-between gap-3">
                <AnimatePresence mode="wait" initial={false}>
                  <motion.span
                    key={phase === "rechecking" ? "checking" : verifiedAt ?? "none"}
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1, transition: { duration: 0.15 } }}
                    exit={{ opacity: 0, transition: { duration: 0.1 } }}
                  >
                    {phase === "rechecking" ? (
                      <Status tone="info" live>Rechecking competitor data…</Status>
                    ) : (
                      <Status tone={warnings.length ? "warn" : "good"}>Data verified {timeAgo(verifiedAt)}</Status>
                    )}
                  </motion.span>
                </AnimatePresence>
                <button className="btn-quiet btn-sm -mr-1.5" onClick={recheck} disabled={busy}>
                  <Icon name="refresh" className={`h-3.5 w-3.5 ${phase === "rechecking" ? "animate-spin" : ""}`} />Recheck
                </button>
              </div>
              {warnings.map((w) => (
                <p key={w} className="mt-2 flex gap-1.5 text-[12px] text-warn"><Icon name="alert" className="mt-0.5 h-3.5 w-3.5" />{w}</p>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Decision */}
      {pending ? (
        <div className="border-t border-line bg-sunken/40 px-5 py-4 sm:px-6">
          <AnimatePresence mode="wait" initial={false}>
            {phase === "approved" ? (
              <motion.div
                key="done"
                className="flex items-center gap-2.5 py-1.5 text-[15px] font-medium text-good"
                initial={{ opacity: 0, transform: "translateY(4px)" }}
                animate={{ opacity: 1, transform: "translateY(0px)", transition: { duration: 0.2, ease: EASE_OUT } }}
              >
                <Icon name="done" className="h-5 w-5" />Approved · our price is now <span className="mono">{formatInr(price)}</span>
              </motion.div>
            ) : (
              <motion.div key="form" className="space-y-3" exit={{ opacity: 0, transition: { duration: 0.1 } }}>
                {error && <p role="alert" className="rounded-[8px] border border-bad/30 bg-bad/[0.05] px-3 py-2 text-[13px] text-bad">{error}</p>}
                {override != null && (
                  <div className="flex max-w-xs items-center gap-2">
                    <label className="shrink-0 text-[12px] text-muted" htmlFor={`override-${p.id}`}>Approve at ₹</label>
                    <input id={`override-${p.id}`} className="input mono h-9" type="number" min={1} value={override} onChange={(e) => setOverride(e.target.value)} autoFocus />
                  </div>
                )}
                <div className="flex flex-wrap items-center gap-2">
                  <motion.button className="btn-primary btn-lg" onClick={approve} disabled={busy} whileTap={{ scale: 0.96 }} transition={PRESS_SPRING}>
                    {phase === "validating" ? (
                      <><Icon name="refresh" className="h-4 w-4 animate-spin" />Validating against the latest data…</>
                    ) : (
                      <><Icon name="check" className="h-4 w-4" />Approve <span className="mono">{formatInr(price)}</span></>
                    )}
                  </motion.button>
                  <button className="btn-ghost btn-lg" onClick={() => setOverride(override == null ? String(p.to_price_inr) : null)} disabled={busy}>
                    <Icon name="pencil" />{override == null ? "Edit price" : "Use recommended"}
                  </button>
                  <button className="btn-quiet btn-lg text-bad hover:bg-bad/[0.06] hover:text-bad" onClick={reject} disabled={busy}>
                    {phase === "rejecting" ? "Rejecting…" : "Reject"}
                  </button>
                </div>
                <div className="flex flex-wrap items-center gap-x-3 gap-y-2 text-[12px] text-muted">
                  {reviewer ? (
                    <span>Deciding as <span className="font-medium text-ink">{reviewer}</span> · <Link to="/settings#profile" className="underline-offset-2 hover:text-ink hover:underline">change</Link></span>
                  ) : (
                    <input className="input h-8 max-w-[220px]" aria-label="Your name" placeholder="Your name (for the price log)" value={name} onChange={(e) => setName(e.target.value)} />
                  )}
                  <input className="input h-8 min-w-[180px] flex-1" aria-label="Note" placeholder="Add a note for the log (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
                  <span className="hidden w-full md:block">Approving re-checks our price and the floor against the latest reading before anything changes.</span>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      ) : (
        p.resolved_at && (
          <div className="border-t border-line px-5 py-3 text-[12px] text-muted sm:px-6">
            {STATUS_LABEL[p.status]} by {p.resolved_by ?? "system"} · {formatDateTime(p.resolved_at)}
            {p.resolution_note ? ` · “${p.resolution_note}”` : ""}
          </div>
        )
      )}
    </article>
  );
}

const ACTION_TITLE = { lower_price: "Lower price", raise_price: "Raise price", hold: "Hold", investigate: "Investigate" } as const;
