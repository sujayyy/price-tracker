import { motion } from "motion/react";
import { Suspense, lazy, useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import {
  ApiError,
  deleteProduct,
  getDecisions,
  getHealth,
  getHistory,
  getOurPriceHistory,
  getProduct,
  getProductProposals,
  recheckProduct,
  updateProduct,
} from "../api/client";
import DemoPricePanel from "../components/DemoPricePanel";
import Icon from "../components/Icon";
import ListingsPanel from "../components/ListingsPanel";
import PositionBadge from "../components/PositionBadge";
import ProductSettings from "../components/ProductSettings";
import RecommendationCard from "../components/RecommendationCard";
import { useConfirm } from "../components/ui/Confirm";
import { ActionBadge, ConfidenceBar, CopyButton, Delta, EmptyState, ErrorState, PlatformDot, ProductThumb, RollingNumber, Skeleton, SourceChip, Status } from "../components/ui/Primitives";
import Tabs, { Segmented } from "../components/ui/Tabs";
import type { Decision, HistorySeries, OurPriceChange, Product, Proposal } from "../types";
import { EVENT_LABEL, MARKETPLACE_LABEL, MARKET_READ_LABEL, STATUS_LABEL, formatDateTime, formatInr, freqLabel, shortTitle, timeAgo, timeUntil } from "../lib/format";
import { notifyProposalsChanged } from "../lib/events";
import { fadeUp, stagger } from "../lib/motion";

const PriceHistoryChart = lazy(() => import("../components/PriceHistoryChart"));

// Short ranges spread out same-day moves; 90D is left out until there's months of history.
const RANGES = [
  { value: 1, label: "1D" },
  { value: 3, label: "3D" },
  { value: 7, label: "7D" },
  { value: 30, label: "30D" },
];

type Tab = "overview" | "history" | "settings";
const TABS: Tab[] = ["overview", "history", "settings"];
type HistoryFilter = "all" | "recommendation" | "price" | "approval";

type Event =
  | { kind: "recommendation"; at: string; d: Decision }
  | { kind: "price"; at: string; c: OurPriceChange }
  | { kind: "approval"; at: string; p: Proposal };

function Figure({ label, children, sub }: { label: string; children: React.ReactNode; sub?: React.ReactNode }) {
  return (
    <div>
      <div className="eyebrow">{label}</div>
      <div className="mt-2">{children}</div>
      {sub && <div className="mt-1.5 text-[12px] text-muted">{sub}</div>}
    </div>
  );
}

/** Long reasoning collapses to two lines; the full text is one click away. */
function Reasoning({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const long = text.length > 220;
  return (
    <div className="max-w-[72ch]">
      <p className={`text-[13px] leading-relaxed ${long && !open ? "line-clamp-2" : ""}`}>{text}</p>
      {long && (
        <button className="mt-0.5 cursor-pointer text-[12px] text-muted underline-offset-2 hover:text-ink hover:underline" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
          {open ? "Show less" : "Show full reasoning"}
        </button>
      )}
    </div>
  );
}

const PAGE = 20;

function Timeline({ events }: { events: Event[] }) {
  const [shown, setShown] = useState(PAGE);
  if (!events.length) return <EmptyState icon="history" title="Nothing here yet">Recommendations, price changes and approvals appear here as they happen.</EmptyState>;
  return (
    <>
    <ol className="relative space-y-5 before:absolute before:bottom-2 before:left-[5px] before:top-2 before:w-px before:bg-line">
      {events.slice(0, shown).map((e) => {
        const key = e.kind === "recommendation" ? `r${e.d.id}` : e.kind === "price" ? `c${e.c.id}` : `p${e.p.id}`;
        const dot =
          e.kind === "recommendation" ? (e.d.decision.action === "investigate" ? "bg-warn-fill" : e.d.decision.action === "hold" ? "bg-line-strong" : "bg-ink")
          : e.kind === "price" ? "bg-brand"
          : e.p.status === "approved" || e.p.status === "auto_applied" ? "bg-good-fill" : e.p.status === "rejected" ? "bg-bad-fill" : "bg-gray-300";
        return (
          <li key={key} className="relative pl-6">
            <span className={`absolute left-0 top-1.5 h-[11px] w-[11px] rounded-full border-2 border-raised ${dot}`} aria-hidden />
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px] text-muted">
              <span title={formatDateTime(e.at)}>{timeAgo(e.at)}</span>
              <span className="text-faint">·</span>
              <span className="font-medium text-ink">
                {e.kind === "recommendation" ? "Recommendation" : e.kind === "price" ? "Our price changed" : `Recommendation ${STATUS_LABEL[e.p.status].toLowerCase()}`}
              </span>
              {e.kind === "recommendation" && e.d.marketplace && <SourceChip marketplace={e.d.marketplace} />}
            </div>
            {e.kind === "recommendation" && (
              <div className="mt-1.5 space-y-1.5">
                <div className="flex flex-wrap items-center gap-2 text-[13px]">
                  <span className="text-muted">{EVENT_LABEL[e.d.trigger_type] ?? e.d.trigger_type}</span>
                  <Icon name="arrowRight" className="h-3.5 w-3.5 text-faint" />
                  <ActionBadge action={e.d.decision.action} price={e.d.decision.recommended_price_inr} />
                  {e.d.alerted && <span className="chip"><Icon name="mail" className="h-3 w-3" />Emailed</span>}
                </div>
                <Reasoning text={e.d.decision.reasoning} />
                <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px] text-muted">
                  <span>Lowest competitor <span className="mono text-ink">{formatInr(e.d.decision.competitor_price_inr)}</span> · ours <span className="mono text-ink">{formatInr(e.d.decision.our_price_inr)}</span> · {MARKET_READ_LABEL[e.d.decision.market_read]}</span>
                  <ConfidenceBar value={e.d.decision.confidence} />
                </p>
                {e.d.decision.data_issues.length > 0 && (
                  <ul className="space-y-0.5 text-[12px] text-warn">
                    {e.d.decision.data_issues.map((n) => <li key={n} className="flex gap-1.5"><Icon name="shield" className="mt-0.5 h-3 w-3" />{n}</li>)}
                  </ul>
                )}
              </div>
            )}
            {e.kind === "price" && (
              <p className="mt-1 text-[13px]">
                {e.c.old_price_inr != null && <><span className="mono text-muted">{formatInr(e.c.old_price_inr)}</span> → </>}
                <span className="mono font-semibold">{formatInr(e.c.new_price_inr)}</span>
                <span className="text-muted"> · {e.c.source === "auto" ? "applied automatically" : e.c.source === "approved" ? `approved by ${e.c.actor}` : `set by ${e.c.actor}`}</span>
                {e.c.note && <span className="text-muted"> · “{e.c.note}”</span>}
              </p>
            )}
            {e.kind === "approval" && (
              <p className="mt-1 text-[13px] text-muted">
                <ActionBadge action={e.p.action} price={e.p.final_price_inr ?? e.p.to_price_inr} />
                <span className="ml-2">{e.p.resolved_by ? `by ${e.p.resolved_by}` : ""}{e.p.resolution_note ? ` · “${e.p.resolution_note}”` : ""}</span>
              </p>
            )}
          </li>
        );
      })}
    </ol>
    {events.length > shown && (
      <div className="mt-5 flex items-center gap-3 pl-6">
        <button className="btn-ghost btn-sm" onClick={() => setShown((n) => n + PAGE)}>Show {Math.min(PAGE, events.length - shown)} older</button>
        <span className="text-[12px] text-muted">{shown} of {events.length}</span>
      </div>
    )}
    </>
  );
}

export default function ProductPage() {
  const id = Number(useParams().id);
  const navigate = useNavigate();
  const confirm = useConfirm();
  const [params, setParams] = useSearchParams();
  const raw = params.get("tab") === "activity" ? "history" : params.get("tab");
  const tab: Tab = TABS.includes(raw as Tab) ? (raw as Tab) : "overview";
  const setTab = (t: Tab) => setParams(t === "overview" ? {} : { tab: t }, { replace: true });

  const [item, setItem] = useState<Product | null>(null);
  const [history, setHistory] = useState<HistorySeries[] | null>(null);
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [audit, setAudit] = useState<OurPriceChange[]>([]);
  // Chosen once the product loads: 7 days for a product monitored less than a week, else 30.
  const [days, setDays] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [demoEnabled, setDemoEnabled] = useState(false);
  const [filter, setFilter] = useState<HistoryFilter>("all");
  const [rechecking, setRechecking] = useState(false);

  const refresh = useCallback(() => {
    getProduct(id).then(setItem).catch(() => {});
    getDecisions(id).then(setDecisions).catch(() => {});
    getProductProposals(id).then(setProposals).catch(() => {});
    getOurPriceHistory(id).then(setAudit).catch(() => {});
    if (days != null) getHistory(id, days).then(setHistory).catch(() => {});
    notifyProposalsChanged();
  }, [id, days]);

  const loadAll = useCallback(() => {
    setError(null);
    Promise.all([getProduct(id), getDecisions(id), getProductProposals(id), getOurPriceHistory(id)])
      .then(([it, ds, ps, au]) => {
        setItem(it);
        setDecisions(ds);
        setProposals(ps);
        setAudit(au);
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : String(err)));
  }, [id]);

  useEffect(loadAll, [loadAll]);
  useEffect(() => {
    if (item && days == null) setDays(Date.now() - new Date(item.created_at).getTime() < 7 * 86_400_000 ? 7 : 30);
  }, [item, days]);
  useEffect(() => {
    if (days != null) getHistory(id, days).then(setHistory).catch(() => setHistory([]));
  }, [id, days]);
  useEffect(() => {
    getHealth().then((h) => setDemoEnabled(h.demo_endpoints)).catch(() => setDemoEnabled(false));
  }, []);

  const events = useMemo<Event[]>(() => {
    const xs: Event[] = [
      ...decisions.map((d) => ({ kind: "recommendation" as const, at: d.created_at, d })),
      ...audit.map((c) => ({ kind: "price" as const, at: c.changed_at, c })),
      ...proposals.filter((p) => p.status !== "pending" && p.status !== "auto_applied" && p.resolved_at).map((p) => ({ kind: "approval" as const, at: p.resolved_at as string, p })),
    ];
    return xs.filter((e) => filter === "all" || e.kind === filter).sort((a, b) => b.at.localeCompare(a.at));
  }, [decisions, audit, proposals, filter]);

  async function recheck() {
    setRechecking(true);
    try {
      const r = await recheckProduct(id);
      setItem(r.product);
      refresh();
      if (r.proposal_replaced) toast.warning("A competitor moved: the recommendation was updated");
      else if (r.changed) toast.success("Rechecked: a competitor change was recorded");
      else toast.success("Data verified: no competitor change", { description: `${r.checked} listing${r.checked === 1 ? "" : "s"} checked just now` });
    } catch (err) {
      toast.error("We couldn't refresh competitor data", { description: `${err instanceof ApiError ? err.message : String(err)}. The last reading is still shown.` });
    } finally {
      setRechecking(false);
    }
  }

  async function toggleActive() {
    if (!item) return;
    try {
      const updated = await updateProduct(id, { active: !item.active });
      setItem(updated);
      toast.success(updated.active ? "Monitoring resumed" : "Monitoring paused");
    } catch (err) {
      toast.error("Couldn't update the product", { description: err instanceof ApiError ? err.message : String(err) });
    }
  }

  async function remove() {
    const ok = await confirm({
      title: "Stop monitoring this product?",
      body: "Every competitor listing stops being checked. Price history, recommendations and our price log are kept.",
      confirmLabel: "Stop monitoring",
      danger: true,
    });
    if (!ok) return;
    await deleteProduct(id);
    toast.success("Product removed", { description: "History and the price log are kept." });
    navigate("/products");
  }

  if (error && !item) return <ErrorState message={`We couldn't load this product: ${error}`} onRetry={loadAll} />;
  if (!item) {
    return (
      <div className="space-y-7" aria-busy="true" aria-label="Loading product">
        <div className="space-y-3"><Skeleton className="h-3 w-20" /><Skeleton className="h-10 w-2/3" /><Skeleton className="h-3 w-72" /></div>
        <Skeleton className="h-10 w-72" />
        <div className="grid grid-cols-2 gap-6 md:grid-cols-5">{[0, 1, 2, 3, 4].map((i) => <div key={i} className="space-y-2"><Skeleton className="h-3 w-20" /><Skeleton className="h-7 w-24" /></div>)}</div>
        <Skeleton className="h-64 rounded-[10px]" />
        <Skeleton className="h-80 rounded-[10px]" />
      </div>
    );
  }

  const pending = proposals.filter((p) => p.status === "pending");
  const lowest = item.listings.find((l) => l.id === item.lowest_listing_id);
  const active = item.listings.filter((l) => l.active);
  const inStock = active.filter((l) => l.latest?.in_stock !== false).length;
  const nextDue = item.last_checked_at ? new Date(new Date(item.last_checked_at).getTime() + item.check_every_hours * 3600_000).toISOString() : null;

  return (
    <div className="space-y-6">
      <div>
        <Link to="/products" className="inline-flex items-center gap-1 text-[13px] text-muted hover:text-ink">
          <Icon name="back" className="h-3.5 w-3.5" />Products
        </Link>
        <div className="mt-4 flex flex-wrap items-start justify-between gap-4">
          <div className="flex min-w-0 max-w-3xl items-start gap-5">
          <ProductThumb src={item.image_url} size={88} className="hidden rounded-[12px] sm:grid" />
          <div className="min-w-0">
            <h1 className="display line-clamp-2 text-[34px] leading-[1.05] sm:text-[40px]" title={item.title}>{shortTitle(item.title, 8, 60)}</h1>
            {shortTitle(item.title, 8, 60) !== item.title && <p className="mt-1.5 line-clamp-1 max-w-2xl text-[12px] text-muted" title={item.title}>{item.title}</p>}
            <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[12px] text-muted">
              {item.our_sku && (
                <span className="inline-flex items-center gap-0.5">
                  <span className="code rounded-[4px] border border-line bg-raised px-1.5 py-0.5 text-ink">{item.our_sku}</span>
                  <CopyButton value={item.our_sku} label="SKU" />
                </span>
              )}
              {item.active ? (
                rechecking ? (
                  <Status tone="info" live>Rechecking {active.length} listing{active.length === 1 ? "" : "s"}…</Status>
                ) : (
                  <Status tone="teal" live>Checking {freqLabel(item.check_every_hours).toLowerCase()} · last {timeAgo(item.last_checked_at)} · next {timeUntil(nextDue)}</Status>
                )
              ) : (
                <Status tone="muted">Monitoring paused</Status>
              )}
            </div>
          </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <button className="btn-ghost" onClick={recheck} disabled={rechecking || !item.active}>
              <Icon name="refresh" className={`h-3.5 w-3.5 ${rechecking ? "animate-spin" : ""}`} />{rechecking ? "Rechecking…" : "Recheck now"}
            </button>
            <button className="btn-ghost" onClick={toggleActive}><Icon name={item.active ? "pause" : "play"} />{item.active ? "Pause" : "Resume"}</button>
          </div>
        </div>
        <div className="mt-5">
          <Tabs
            label="Product"
            value={tab}
            onChange={setTab}
            items={[
              { id: "overview", label: "Overview", count: pending.length || undefined },
              { id: "history", label: "History", count: decisions.length + audit.length },
              { id: "settings", label: "Settings" },
            ]}
          />
        </div>
      </div>

      {tab === "overview" && (
        <motion.div key="overview" className="space-y-7" variants={stagger} initial="hidden" animate="show" role="tabpanel">
          {/* Price intelligence */}
          <motion.section variants={fadeUp} aria-label="Price intelligence" className="stat-band">
            <Figure label="Our price" sub={item.floor_price_inr != null ? <>floor <span className="mono">{formatInr(item.floor_price_inr)}</span></> : "No floor set"}>
              <RollingNumber value={item.our_price_inr} format={formatInr} tint={false} className="mono text-[26px] font-semibold leading-none" />
            </Figure>
            <Figure
              label="Lowest competitor"
              sub={lowest ? (
                <a href={lowest.canonical_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 hover:text-ink"><PlatformDot marketplace={lowest.marketplace} />on {MARKETPLACE_LABEL[lowest.marketplace]}<Icon name="external" className="h-3 w-3" /></a>
              ) : item.competitor_in_stock === false ? "All competitors out of stock" : "No reading yet"}
            >
              <span className="inline-flex items-center gap-2">
                <RollingNumber value={item.lowest_price_inr} format={formatInr} className="mono text-[26px] font-semibold leading-none" />
                <Delta from={lowest?.previous_price_inr} to={lowest?.latest?.price_inr} size="xs" />
              </span>
            </Figure>
            <Figure label="Price gap"><PositionBadge position={item.position} gap={item.gap_inr} gapPct={item.gap_pct} compact /></Figure>
            <Figure label="Competitor stock" sub={`${active.length} platform${active.length === 1 ? "" : "s"} monitored`}>
              <span className="num text-[20px] font-semibold leading-none">{inStock}</span>
              <span className="text-[13px] text-muted"> of {active.length} in stock</span>
            </Figure>
            <Figure label="Repricing" sub={<button className="cursor-pointer underline-offset-2 hover:text-ink hover:underline" onClick={() => setTab("settings")}>Max move {item.max_change_pct}% · edit rules</button>}>
              <span className="text-[13px] font-medium">{item.auto_apply ? <>Auto-apply ≤ <span className="num">{item.auto_apply_max_pct}%</span></> : "Approval required"}</span>
            </Figure>
          </motion.section>

          {pending.map((p) => (
            <motion.div key={p.id} variants={fadeUp}><RecommendationCard proposal={p} onResolved={refresh} /></motion.div>
          ))}

          <motion.section variants={fadeUp} className="card overflow-hidden" aria-labelledby="chart-title">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-3.5">
              <div>
                <h2 id="chart-title" className="card-title">Price history</h2>
                <p className="card-sub">Every platform against our price and floor</p>
              </div>
              <Segmented label="Time range" value={days ?? 30} onChange={setDays} options={RANGES} />
            </div>
            <div className="px-3 pb-4 pt-3 sm:px-5">
              {history === null || days == null ? <Skeleton className="h-72" /> : (
                <Suspense fallback={<Skeleton className="h-72" />}>
                  <PriceHistoryChart series={history} ourChanges={audit} ourPrice={item.our_price_inr} floorPrice={item.floor_price_inr} days={days} />
                </Suspense>
              )}
            </div>
          </motion.section>

          <motion.div variants={fadeUp}><ListingsPanel product={item} onChanged={refresh} /></motion.div>

          {demoEnabled && <motion.div variants={fadeUp}><DemoPricePanel product={item} onChanged={refresh} /></motion.div>}
        </motion.div>
      )}

      {tab === "history" && (
        <motion.section key="history" variants={fadeUp} initial="hidden" animate="show" role="tabpanel" aria-label="History" className="card overflow-hidden">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-3.5">
            <div>
              <h2 className="card-title">History</h2>
              <p className="card-sub">Recommendations, price changes and approvals, newest first</p>
            </div>
            <Segmented
              label="Show"
              value={filter}
              onChange={setFilter}
              options={[
                { value: "all", label: "All" },
                { value: "recommendation", label: "Recommendations" },
                { value: "price", label: "Price changes" },
                { value: "approval", label: "Decisions" },
              ]}
            />
          </div>
          <div className="px-5 py-5"><Timeline key={filter} events={events} /></div>
        </motion.section>
      )}

      {tab === "settings" && (
        <motion.div key="settings" variants={fadeUp} initial="hidden" animate="show" role="tabpanel" aria-label="Settings">
          <ProductSettings product={item} onSaved={(p) => { setItem(p); refresh(); }} onRemove={remove} />
        </motion.div>
      )}
    </div>
  );
}
