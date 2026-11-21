import { AnimatePresence, motion } from "motion/react";
import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, getActivity } from "../api/client";
import Icon from "../components/Icon";
import { ActionBadge, ConfidenceBar, EmptyState, ErrorState, PageHeader, PlatformDot, Skeleton, Status } from "../components/ui/Primitives";
import { Segmented } from "../components/ui/Tabs";
import type { Activity, PriceAction } from "../types";
import { ACTION_LABEL, EVENT_LABEL, MARKETPLACE_LABEL, MARKET_READ_LABEL, STATUS_LABEL, formatDateTime, formatInr, shortTitle, timeAgo } from "../lib/format";

type ActionFilter = "all" | PriceAction;
const ACTIONS: PriceAction[] = ["lower_price", "raise_price", "hold", "investigate"];
// Our actions are decisions, not alarms: ink and aqua for moves, paper-grey for holds, saffron only for "investigate".
const BAR: Record<PriceAction, string> = { lower_price: "bg-ink", raise_price: "bg-accent", hold: "bg-line-strong", investigate: "bg-warn-fill" };
const DAYS = 30;

function Outcome({ a }: { a: Activity }) {
  if (!a.proposal_status) return <span className="text-[12px] text-muted">{a.action === "hold" ? "No change needed" : a.action === "investigate" ? "Check the listing" : "—"}</span>;
  const tone = a.proposal_status === "pending" ? "warn" : a.proposal_status === "approved" || a.proposal_status === "auto_applied" ? "good" : a.proposal_status === "rejected" || a.proposal_status === "failed" ? "bad" : "muted";
  const by = a.resolved_by && a.proposal_status !== "superseded" && a.proposal_status !== "auto_applied" ? ` · ${a.resolved_by}` : "";
  const text = a.proposal_status === "auto_applied" ? "Applied automatically" : `${STATUS_LABEL[a.proposal_status]}${by}`;
  return a.proposal_status === "pending" ? (
    <Link to={`/approvals?id=${a.proposal_id}`} className="hover:underline"><Status tone={tone}>{text}</Status></Link>
  ) : (
    <Status tone={tone} className="text-muted">{text}</Status>
  );
}

export default function RecommendationsPage() {
  const [items, setItems] = useState<Activity[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [action, setAction] = useState<ActionFilter>("all");
  const [platform, setPlatform] = useState<string>("all");
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      setItems(await getActivity(DAYS, 500));
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    }
  }, []);
  useEffect(() => {
    load();
  }, [load]);

  const counts = useMemo(() => Object.fromEntries(ACTIONS.map((a) => [a, (items ?? []).filter((x) => x.action === a).length])) as Record<PriceAction, number>, [items]);
  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (items ?? []).filter(
      (a) => (action === "all" || a.action === action) && (platform === "all" || a.marketplace === platform) && (!q || a.product_title.toLowerCase().includes(q)),
    );
  }, [items, action, platform, query]);
  const total = items?.length ?? 0;

  return (
    <div className="space-y-6">
      <PageHeader title="Recommendations" description={`Every call the pricing analyst made after a competitor change in the last ${DAYS} days: what changed, what it suggested, and what happened next.`} />

      {error && <ErrorState message={error} onRetry={load} />}
      {items === null && !error && <div className="space-y-4"><Skeleton className="h-2.5 rounded-full" /><Skeleton className="h-4 w-80" /><div className="space-y-1.5"><Skeleton className="h-12" /><Skeleton className="h-14" /><Skeleton className="h-14" /><Skeleton className="h-14" /></div></div>}

      {items && (
        <>
          {/* Mix: how the recommendations split */}
          {total > 0 && (
            <section aria-label="Recommendation mix" className="space-y-2.5">
              <div className="flex h-2.5 w-full gap-[3px]" role="img" aria-label={ACTIONS.map((a) => `${counts[a]} ${ACTION_LABEL[a]}`).join(", ")}>
                {ACTIONS.map((a) => (counts[a] ? <span key={a} className={`${BAR[a]} h-full rounded-[3px]`} style={{ flexGrow: counts[a], flexBasis: 0 }} /> : null))}
              </div>
              <div className="flex flex-wrap gap-x-5 gap-y-1 text-[12px]">
                {ACTIONS.map((a) => (
                  <span key={a} className="flex items-center gap-1.5">
                    <span className={`h-2 w-2 rounded-[2px] ${BAR[a]}`} aria-hidden />
                    <span className="text-muted">{ACTION_LABEL[a]}</span>
                    <span className="num font-medium">{counts[a]}</span>
                  </span>
                ))}
                <span className="ml-auto text-muted"><span className="num font-medium text-ink">{total}</span> recommendations</span>
              </div>
            </section>
          )}

          <section className="card overflow-hidden" aria-label="Recommendations">
            <div className="flex flex-wrap items-center gap-2.5 border-b border-line px-3 py-2.5 sm:px-4">
              <div className="relative min-w-[180px] flex-1 sm:max-w-[260px]">
                <Icon name="search" className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-faint" />
                <input className="input h-8 pl-8" placeholder="Filter by product" aria-label="Filter by product" value={query} onChange={(e) => setQuery(e.target.value)} />
              </div>
              <div className="overflow-x-auto">
                <Segmented
                  label="Action"
                  value={action}
                  onChange={setAction}
                  options={[{ value: "all" as ActionFilter, label: "All" }, ...ACTIONS.map((a) => ({ value: a as ActionFilter, label: ACTION_LABEL[a].replace(" price", "") }))]}
                />
              </div>
              <select className="input h-8 w-auto" aria-label="Platform" value={platform} onChange={(e) => setPlatform(e.target.value)}>
                <option value="all">All platforms</option>
                <option value="amazon_in">Amazon.in</option>
                <option value="flipkart">Flipkart</option>
              </select>
            </div>

            {total === 0 ? (
              <EmptyState icon="recommendations" title="No recommendations yet">No pricing action has been needed. Recommendations appear when a competitor's listing changes.</EmptyState>
            ) : shown.length === 0 ? (
              <EmptyState icon="search" title="Nothing matches these filters" action={<button className="btn-ghost" onClick={() => { setAction("all"); setPlatform("all"); setQuery(""); }}>Clear filters</button>} />
            ) : (
              <div className="relative overflow-x-auto">
                <table className="w-full min-w-[760px] text-left text-[13px]">
                  <thead className="thead sticky top-0">
                    <tr className="border-b border-line">
                      <th scope="col" className="w-[96px] px-4 py-2.5 font-medium">When</th>
                      <th scope="col" className="px-3 py-2 font-medium">Product and trigger</th>
                      <th scope="col" className="px-3 py-2 font-medium">Recommendation</th>
                      <th scope="col" className="px-3 py-2 font-medium">Outcome</th>
                      <th scope="col" className="w-10 px-3 py-2"><span className="sr-only">Details</span></th>
                    </tr>
                  </thead>
                  <tbody>
                    {shown.slice(0, 200).map((a) => {
                      const expanded = open === a.id;
                      return (
                        <Fragment key={a.id}>
                          <tr className={`cursor-pointer border-b border-line transition-colors duration-150 hover:bg-sunken/50 ${expanded ? "bg-sunken/50" : ""}`} onClick={() => setOpen(expanded ? null : a.id)}>
                            <td className="px-4 py-3 align-top text-[12px] text-muted" title={formatDateTime(a.created_at)}>{timeAgo(a.created_at)}</td>
                            <td className="max-w-[360px] px-3 py-3 align-top">
                              <Link to={`/products/${a.product_id}`} className="line-clamp-1 font-medium hover:underline" title={a.product_title}>{shortTitle(a.product_title)}</Link>
                              <span className="mt-1 flex flex-wrap items-center gap-1.5 text-[12px] text-muted">
                                {a.marketplace && <><PlatformDot marketplace={a.marketplace} /><span className="text-ink">{MARKETPLACE_LABEL[a.marketplace]}</span></>}
                                {a.trigger_type === "price_drop" && <span className="text-bad" aria-hidden>▼</span>}
                                {a.trigger_type === "price_increase" && <span className="text-good" aria-hidden>▲</span>}
                                {(EVENT_LABEL[a.trigger_type] ?? a.trigger_type).replace("Competitor ", "").toLowerCase()}
                                {a.competitor_price_inr != null && <> · lowest <span className="mono text-ink">{formatInr(a.competitor_price_inr)}</span></>}
                              </span>
                            </td>
                            <td className="px-3 py-3 align-top"><ActionBadge action={a.action} price={a.recommended_price_inr} /></td>
                            <td className="px-3 py-3 align-top"><Outcome a={a} /></td>
                            <td className="px-3 py-3 align-top">
                              <button className="icon-btn h-7 w-7" onClick={(e) => { e.stopPropagation(); setOpen(expanded ? null : a.id); }} aria-expanded={expanded} aria-label={expanded ? "Hide reasoning" : "Show reasoning"}>
                                <Icon name="chevronDown" className={`h-4 w-4 transition-transform duration-150 ${expanded ? "rotate-180" : ""}`} />
                              </button>
                            </td>
                          </tr>
                          <AnimatePresence initial={false}>
                            {expanded && (
                              <motion.tr key="details" initial={{ opacity: 0 }} animate={{ opacity: 1, transition: { duration: 0.15 } }} exit={{ opacity: 0, transition: { duration: 0.1 } }} className="border-b border-line bg-sunken/40">
                                <td />
                                <td colSpan={4} className="px-3 pb-4 pt-0">
                                  <blockquote className="max-w-[72ch] border-l-2 border-brand/60 pl-3 text-[13px] leading-relaxed">{a.reasoning}</blockquote>
                                  <p className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 pl-3.5 text-[12px] text-muted">
                                    <span>{a.market_read ? MARKET_READ_LABEL[a.market_read] : "—"} · {a.urgency ?? "—"} urgency</span>
                                    {a.confidence != null && <ConfidenceBar value={a.confidence} />}
                                    {a.our_price_inr != null ? <span>· our price then <span className="mono">{formatInr(a.our_price_inr)}</span></span> : null}
                                    {a.alerted ? <span>· ops team emailed</span> : null}
                                  </p>
                                </td>
                              </motion.tr>
                            )}
                          </AnimatePresence>
                        </Fragment>
                      );
                    })}
                  </tbody>
                </table>
                {shown.length > 200 && <p className="px-4 py-3 text-[12px] text-muted">Showing the latest 200 of {shown.length}. Narrow the filters to see older ones.</p>}
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}
