import { motion } from "motion/react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, getActivity, listProducts, listProposals } from "../api/client";
import Icon from "../components/Icon";
import { ActionBadge, EmptyState, ErrorState, PlatformDot, ProductThumb, RollingNumber, SectionHeader, Skeleton, Status } from "../components/ui/Primitives";
import type { Activity, Product, Proposal } from "../types";
import { EVENT_LABEL, MARKETPLACE_LABEL, MARKETPLACE_SHORT, STATUS_LABEL, formatInr, formatPct, loadReviewer, shortTitle, timeAgo } from "../lib/format";
import { EASE_OUT, fadeUp, stagger } from "../lib/motion";

const DAYS = 14;
const WEEK = 7 * 86_400_000;

// ---------------------------------------------------------------------------------------------
// Data shaping

interface MovesDay {
  day: string; // YYYY-MM-DD
  drops: number;
  rises: number;
  other: number;
}

function movesByDay(activity: Activity[]): MovesDay[] {
  const days: MovesDay[] = [];
  const today = new Date();
  for (let i = DAYS - 1; i >= 0; i--) {
    const d = new Date(today);
    d.setDate(today.getDate() - i);
    days.push({ day: d.toLocaleDateString("en-CA"), drops: 0, rises: 0, other: 0 });
  }
  const index = new Map(days.map((d) => [d.day, d]));
  for (const a of activity) {
    const row = index.get(new Date(a.created_at).toLocaleDateString("en-CA"));
    if (!row) continue;
    if (a.trigger_type === "price_drop") row.drops++;
    else if (a.trigger_type === "price_increase") row.rises++;
    else row.other++;
  }
  return days;
}

const fmtDay = (d: string) => new Date(`${d}T00:00:00`).toLocaleDateString("en-IN", { day: "numeric", month: "short" });

function greeting(): string {
  const h = new Date().getHours();
  return h < 5 ? "Working late" : h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
}

// ---------------------------------------------------------------------------------------------
// Command band: are we competitive, and what is waiting on us?

function CommandBand({ products, pending, lastChecked }: { products: Product[]; pending: Proposal[]; lastChecked: string | null }) {
  const active = products.filter((p) => p.active);
  const cheaper = active.filter((p) => p.position === "we_are_cheaper").length;
  const matched = active.filter((p) => p.position === "same_price").length;
  const pricier = active.filter((p) => p.position === "we_are_pricier");
  const other = active.length - cheaper - matched - pricier.length;
  const comparable = cheaper + matched + pricier.length;
  const competitive = cheaper + matched;
  const avgGap = pricier.length ? pricier.reduce((n, p) => n + (p.gap_pct ?? 0), 0) / pricier.length : null;
  const oldest = pending.length ? pending.reduce((a, b) => (a.created_at < b.created_at ? a : b)) : null;
  const reviewer = loadReviewer();
  const today = new Date().toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long" });

  const segs = [
    { key: "cheaper", n: cheaper, cls: "bg-good-fill", label: "Cheaper" },
    { key: "matched", n: matched, cls: "bg-on-band/70", label: "Matched" },
    { key: "pricier", n: pricier.length, cls: "bg-warn-fill", label: "Pricier" },
    { key: "other", n: other, cls: "hatch text-on-band/35 bg-on-band/[0.06]", label: "Not comparable" },
  ].filter((s) => s.n > 0);

  return (
    <section className="band" aria-label="Pricing position">
      <div className="grid lg:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)]">
        <div className="p-6 sm:p-8">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-on-band/65">
            <span className="font-medium text-on-band/85">{greeting()}{reviewer ? `, ${reviewer.split(" ")[0]}` : ""}</span>
            <span aria-hidden>·</span>
            <span>{today}</span>
            <span aria-hidden>·</span>
            <span>Last check {timeAgo(lastChecked)}</span>
          </div>

          {comparable === 0 ? (
            <h1 className="display mt-5 text-[34px] leading-[1.05] sm:text-[42px]">
              No product can be compared yet.
              <span className="mt-2 block font-sans text-[14px] leading-relaxed text-on-band/70">Set our price on a product, and keep at least one competitor listing in stock.</span>
            </h1>
          ) : (
            <h1 className="mt-5">
              <span className="display flex items-baseline gap-2 leading-none">
                <span className="text-[64px] sm:text-[76px]"><RollingNumber value={competitive} tint={false} /></span>
                <span className="text-[30px] text-on-band/55 sm:text-[36px]">of {comparable}</span>
              </span>
              <span className="mt-2 block max-w-md text-[15px] leading-snug text-on-band/85">
                {comparable === 1 ? "product is" : "products are"} priced at or below the lowest competitor
              </span>
            </h1>
          )}

          {active.length > 0 && (
            <div className="mt-7 max-w-xl">
              <div className="flex h-2.5 w-full gap-[3px]" role="img" aria-label={segs.map((s) => `${s.n} ${s.label.toLowerCase()}`).join(", ")}>
                {segs.map((s, i) => (
                  <motion.span
                    key={s.key}
                    className={`h-full rounded-[3px] ${s.cls}`}
                    style={{ flexGrow: s.n, flexBasis: 0, transformOrigin: "left" }}
                    initial={{ transform: "scaleX(0)" }}
                    animate={{ transform: "scaleX(1)", transition: { duration: 0.7, delay: 0.15 + i * 0.08, ease: EASE_OUT } }}
                  />
                ))}
              </div>
              <ul className="mt-3 flex flex-wrap gap-x-5 gap-y-1.5 text-[12px] text-on-band/75">
                {segs.map((s) => (
                  <li key={s.key} className="flex items-center gap-1.5">
                    <span className={`h-2 w-2 rounded-[2px] ${s.cls}`} aria-hidden />
                    {s.label}
                    <span className="num font-semibold text-on-band">{s.n}</span>
                  </li>
                ))}
              </ul>
              {avgGap != null && (
                <p className="mt-4 text-[13px] text-on-band/75">
                  Where we're pricier, we sit <span className="mono font-semibold text-warn-fill">+{formatPct(avgGap, false)}</span> above the lowest competitor on average.
                </p>
              )}
            </div>
          )}
        </div>

        <div className="flex flex-col justify-between gap-6 border-t border-on-band/10 p-6 sm:p-8 lg:border-l lg:border-t-0">
          <div>
            <div className="eyebrow text-on-band/60">Awaiting your approval</div>
            <div className="display mt-3 text-[64px] leading-none sm:text-[76px]">
              <RollingNumber value={pending.length} tint={false} />
            </div>
            <p className="mt-2 text-[13px] text-on-band/75">
              {pending.length === 0
                ? "Nothing is waiting. New recommendations land here and in the ops inbox."
                : <>price change{pending.length === 1 ? "" : "s"} held for a decision{oldest ? <> · oldest {timeAgo(oldest.created_at)}</> : null}</>}
            </p>
          </div>
          {pending.length > 0 ? (
            <Link to={`/approvals?id=${oldest?.id ?? ""}`} className="btn-band btn-lg self-start">
              Review {pending.length === 1 ? "it" : `${pending.length} changes`}<Icon name="arrowRight" className="h-4 w-4" />
            </Link>
          ) : (
            <Link to="/approvals" className="inline-flex items-center gap-1 self-start text-[13px] font-medium text-on-band/80 hover:text-on-band">
              Past decisions<Icon name="arrowRight" className="h-3.5 w-3.5" />
            </Link>
          )}
        </div>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------------------------
// Secondary figures: one quiet strip.

function Figure({ label, value, sub, to }: { label: string; value: number; sub: React.ReactNode; to?: string }) {
  const body = (
    <>
      <div className="eyebrow">{label}</div>
      <div className="mt-2 text-[26px] font-semibold leading-none tracking-[-0.03em]"><RollingNumber value={value} tint={false} /></div>
      <div className="mt-2 text-[12px] text-muted">{sub}</div>
    </>
  );
  return to ? (
    <Link to={to} className="group block rounded-[4px] transition-colors duration-150 hover:[&_.eyebrow]:text-ink">{body}</Link>
  ) : (
    <div>{body}</div>
  );
}

// ---------------------------------------------------------------------------------------------
// Needs attention: each product told as one situation, with one next step.

function AttentionRow({ product: p, proposal }: { product: Product; proposal?: Proposal }) {
  const lowest = p.listings.find((l) => l.id === p.lowest_listing_id);
  const moved = lowest?.previous_price_inr != null && lowest.latest?.price_inr != null ? lowest.latest.price_inr - lowest.previous_price_inr : null;
  return (
    <li className="group relative grid gap-x-6 gap-y-3 px-5 py-4 transition-colors duration-150 hover:bg-sunken/50 md:grid-cols-[minmax(0,1fr)_auto_auto] md:items-center">
      <span className={`absolute inset-y-3 left-0 w-[3px] rounded-r-full ${proposal ? "bg-warn-fill" : "bg-line-strong"}`} aria-hidden />
      <div className="flex min-w-0 items-center gap-3.5">
      <ProductThumb src={p.image_url} size={44} />
      <div className="min-w-0">
        <div className="flex items-baseline gap-2">
          <Link to={`/products/${p.id}`} className="truncate text-[14px] font-semibold hover:underline" title={p.title}>{shortTitle(p.title)}</Link>
          {p.our_sku && <span className="code hidden shrink-0 text-muted sm:inline">{p.our_sku}</span>}
        </div>
        <p className="mt-1 text-[13px] text-muted">
          {lowest ? (
            <>
              <PlatformDot marketplace={lowest.marketplace} className="mr-1.5 align-middle" />
              {MARKETPLACE_SHORT[lowest.marketplace]}{" "}
              {moved != null && Math.abs(moved) >= 0.5 ? (
                <>{moved < 0 ? "cut" : "raised"} <span className={`mono font-medium ${moved < 0 ? "text-bad" : "text-good"}`}>{moved < 0 ? "▼" : "▲"}{formatInr(Math.abs(moved))}</span> to </>
              ) : "is at "}
              <span className="mono font-medium text-ink">{formatInr(p.lowest_price_inr)}</span>
            </>
          ) : "No competitor in stock"}
          {p.our_price_inr != null && <> · we're at <span className="mono font-medium text-ink">{formatInr(p.our_price_inr)}</span></>}
          {p.position === "we_are_pricier" && p.gap_inr != null && <span className="mono text-warn"> +{formatInr(p.gap_inr)} ({formatPct(p.gap_pct, false)})</span>}
        </p>
      </div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {proposal ? (
          <>
            <ActionBadge action={proposal.action} price={proposal.to_price_inr} />
            <Status tone="warn" className="text-muted">Awaiting approval</Status>
          </>
        ) : (
          <Status tone="muted" className="text-muted">Pricier · no change proposed</Status>
        )}
      </div>
      <div className="flex md:justify-end">
        {proposal ? (
          <Link to={`/approvals?id=${proposal.id}`} className="btn-primary btn-sm">Review<Icon name="arrowRight" className="h-3.5 w-3.5" /></Link>
        ) : (
          <Link to={`/products/${p.id}`} className="btn-ghost btn-sm">Open</Link>
        )}
      </div>
    </li>
  );
}

// ---------------------------------------------------------------------------------------------
// Market movement: 14 small stacked columns, no chart library.

function MovesStrip({ days }: { days: MovesDay[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const max = Math.max(1, ...days.map((d) => d.drops + d.rises + d.other));
  const h = (n: number) => `${(n / max) * 100}%`;
  const shown = hover != null ? days[hover] : null;
  return (
    <div className="relative">
      <div className="flex h-[132px] items-end gap-1.5" role="img" aria-label={`Competitor moves per day over the last ${DAYS} days: ${days.reduce((n, d) => n + d.drops, 0)} cuts, ${days.reduce((n, d) => n + d.rises, 0)} raises.`} onMouseLeave={() => setHover(null)}>
        {days.map((d, i) => {
          const total = d.drops + d.rises + d.other;
          return (
            <div key={d.day} className="relative flex h-full flex-1 cursor-default flex-col justify-end" onMouseEnter={() => setHover(i)}>
              <div className={`absolute inset-x-[-3px] inset-y-0 rounded-[4px] transition-colors duration-150 ${hover === i ? "bg-sunken" : ""}`} aria-hidden />
              {total === 0 ? (
                <div className="relative h-[2px] rounded-full bg-line" />
              ) : (
                <motion.div
                  className="relative flex flex-col justify-end gap-[2px]"
                  style={{ height: h(total), transformOrigin: "bottom" }}
                  initial={{ transform: "scaleY(0)" }}
                  animate={{ transform: "scaleY(1)", transition: { duration: 0.5, delay: 0.1 + i * 0.02, ease: EASE_OUT } }}
                >
                  {d.other > 0 && <span className="w-full rounded-t-[3px] bg-line-strong" style={{ flexGrow: d.other }} />}
                  {d.rises > 0 && <span className={`w-full bg-good-fill ${d.other ? "" : "rounded-t-[3px]"}`} style={{ flexGrow: d.rises }} />}
                  {d.drops > 0 && <span className={`w-full rounded-b-[2px] bg-bad-fill ${d.other || d.rises ? "" : "rounded-t-[3px]"}`} style={{ flexGrow: d.drops }} />}
                </motion.div>
              )}
            </div>
          );
        })}
      </div>
      <div className="mt-2 flex justify-between text-[11px] text-muted">
        <span>{fmtDay(days[0].day)}</span>
        <span>{fmtDay(days[Math.floor(days.length / 2)].day)}</span>
        <span>Today</span>
      </div>
      {shown && hover != null && (
        <div
          className="pointer-events-none absolute bottom-[calc(100%+8px)] z-10 w-44 rounded-[10px] border border-line bg-raised px-3 py-2 text-[12px] shadow-pop"
          style={{ left: `clamp(0px, calc(${((hover + 0.5) / days.length) * 100}% - 88px), calc(100% - 176px))` }}
        >
          <div className="mb-1 font-medium">{fmtDay(shown.day)}</div>
          <div className="flex items-center gap-2 text-muted"><span className="h-2 w-2 rounded-[2px] bg-bad-fill" />▼ Cuts<b className="num ml-auto text-ink">{shown.drops}</b></div>
          <div className="flex items-center gap-2 text-muted"><span className="h-2 w-2 rounded-[2px] bg-good-fill" />▲ Raises<b className="num ml-auto text-ink">{shown.rises}</b></div>
          {shown.other > 0 && <div className="flex items-center gap-2 text-muted"><span className="h-2 w-2 rounded-[2px] bg-line-strong" />Stock / other<b className="num ml-auto text-ink">{shown.other}</b></div>}
        </div>
      )}
      <table className="sr-only">
        <caption>Competitor moves per day</caption>
        <thead><tr><th>Day</th><th>Cuts</th><th>Raises</th><th>Other</th></tr></thead>
        <tbody>{days.map((d) => <tr key={d.day}><td>{fmtDay(d.day)}</td><td>{d.drops}</td><td>{d.rises}</td><td>{d.other}</td></tr>)}</tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------
// Price position: products ranked by how far we sit from the lowest competitor.

function PositionList({ products }: { products: Product[] }) {
  const comparable = products.filter((p) => p.gap_pct != null).sort((a, b) => (b.gap_pct ?? 0) - (a.gap_pct ?? 0));
  const others = products.length - comparable.length;
  const max = Math.max(5, ...comparable.map((p) => Math.abs(p.gap_pct ?? 0)));
  if (!comparable.length) return <EmptyState compact icon="products" title="Nothing to rank yet">Set our price on a product to see where it stands.</EmptyState>;
  return (
    <div className="px-5 pb-5 pt-4">
      <div className="mb-3 flex justify-between text-[11px] text-muted"><span>◀ Cheaper</span><span>Pricier ▶</span></div>
      <ul className="space-y-3.5">
        {comparable.map((p) => {
          const gap = p.gap_pct ?? 0;
          const w = `${(Math.abs(gap) / max) * 50}%`;
          return (
            <li key={p.id}>
              <Link to={`/products/${p.id}`} className="group block">
                <div className="flex items-baseline justify-between gap-3 text-[12px]">
                  <span className="truncate font-medium text-ink group-hover:underline" title={p.title}>{shortTitle(p.title, 5, 32)}</span>
                  <span className={`mono shrink-0 font-medium ${gap > 0 ? "text-warn" : gap < 0 ? "text-good" : "text-muted"}`}>{gap > 0 ? "+" : gap < 0 ? "−" : ""}{formatPct(Math.abs(gap), false)}</span>
                </div>
                <div className="relative mt-1.5 h-2 rounded-full bg-sunken" aria-hidden>
                  <span className="absolute inset-y-[-3px] left-1/2 w-px bg-line-strong" />
                  <span className={`absolute inset-y-0 rounded-full ${gap > 0 ? "left-1/2 bg-warn-fill" : "right-1/2 bg-good-fill"}`} style={{ width: w }} />
                </div>
              </Link>
            </li>
          );
        })}
      </ul>
      {others > 0 && <p className="mt-4 border-t border-line pt-3 text-[12px] text-muted">{others} more not comparable yet: no price of ours, or no competitor in stock.</p>}
    </div>
  );
}

// ---------------------------------------------------------------------------------------------
// Recent activity: detected change → recommendation → outcome, one calm line each.

function eventText(a: Activity): React.ReactNode {
  const price = a.competitor_price_inr != null ? <span className="mono text-ink">{formatInr(a.competitor_price_inr)}</span> : null;
  switch (a.trigger_type) {
    case "price_drop":
      return <><span className="text-bad" aria-hidden>▼ </span>cut{price && <> to {price}</>}</>;
    case "price_increase":
      return <><span className="text-good" aria-hidden>▲ </span>raised{price && <> to {price}</>}</>;
    case "out_of_stock":
      return "went out of stock";
    case "back_in_stock":
      return <>back in stock{price && <> at {price}</>}</>;
    default:
      return (EVENT_LABEL[a.trigger_type] ?? a.trigger_type).toLowerCase();
  }
}

function outcomeOf(a: Activity): { tone: "good" | "warn" | "bad" | "muted"; text: string } {
  if (!a.proposal_status) return { tone: "muted", text: a.action === "investigate" ? "Flagged for a check" : "No change needed" };
  switch (a.proposal_status) {
    case "pending":
      return { tone: "warn", text: "Awaiting approval" };
    case "approved":
      return { tone: "good", text: `Approved${a.resolved_by ? ` · ${a.resolved_by}` : ""}` };
    case "auto_applied":
      return { tone: "good", text: "Applied automatically" };
    case "rejected":
    case "failed":
      return { tone: "bad", text: STATUS_LABEL[a.proposal_status] };
    default:
      return { tone: "muted", text: STATUS_LABEL[a.proposal_status] };
  }
}

function ActivityRow({ a }: { a: Activity }) {
  const out = outcomeOf(a);
  return (
    <li className="grid gap-x-5 gap-y-1.5 px-5 py-3.5 transition-colors duration-150 hover:bg-sunken/50 lg:grid-cols-[64px_minmax(0,1fr)_minmax(0,1.15fr)_176px_168px] lg:items-center">
      <span className="text-[12px] text-muted">{timeAgo(a.created_at)}</span>
      <Link to={`/products/${a.product_id}`} className="truncate text-[13px] font-medium hover:underline" title={a.product_title}>{shortTitle(a.product_title)}</Link>
      <span className="flex min-w-0 items-center gap-1.5 truncate text-[13px] text-muted">
        {a.marketplace && <><PlatformDot marketplace={a.marketplace} /><span className="text-ink">{MARKETPLACE_LABEL[a.marketplace]}</span></>}
        <span className="truncate">{eventText(a)}</span>
      </span>
      <span><ActionBadge action={a.action} price={a.recommended_price_inr} /></span>
      <span className="lg:text-right"><Status tone={out.tone} className="text-muted">{out.text}</Status></span>
    </li>
  );
}

// ---------------------------------------------------------------------------------------------

export default function DashboardPage() {
  const [products, setProducts] = useState<Product[] | null>(null);
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [activity, setActivity] = useState<Activity[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [ps, pr, ac] = await Promise.all([listProducts(), listProposals(), getActivity(DAYS)]);
      setProducts(ps);
      setProposals(pr);
      setActivity(ac);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    load();
    const t = window.setInterval(load, 30_000);
    return () => window.clearInterval(t);
  }, [load]);

  const stats = useMemo(() => {
    const xs = products ?? [];
    const recent = activity.filter((a) => Date.now() - new Date(a.created_at).getTime() < WEEK);
    const applied = proposals.filter((p) => (p.status === "approved" || p.status === "auto_applied") && p.resolved_at && Date.now() - new Date(p.resolved_at).getTime() < WEEK);
    const checks = xs.map((p) => p.last_checked_at).filter((t): t is string => !!t).sort();
    return {
      cuts: recent.filter((a) => a.trigger_type === "price_drop").length,
      raises: recent.filter((a) => a.trigger_type === "price_increase").length,
      recs: recent.filter((a) => a.action === "lower_price" || a.action === "raise_price").length,
      holds: recent.filter((a) => a.action === "hold").length,
      decisions: recent.length,
      applied: applied.length,
      auto: applied.filter((p) => p.status === "auto_applied").length,
      listings: xs.reduce((n, p) => n + p.listings.filter((l) => l.active).length, 0),
      lastChecked: checks.length ? checks[checks.length - 1] : null,
    };
  }, [products, proposals, activity]);

  const pending = useMemo(() => proposals.filter((p) => p.status === "pending"), [proposals]);
  const pendingByProduct = useMemo(() => new Map(pending.map((p) => [p.product_id, p])), [pending]);
  const attention = useMemo(
    () =>
      (products ?? [])
        .filter((p) => p.pending_proposal || p.position === "we_are_pricier")
        .sort((a, b) => Number(!!b.pending_proposal) - Number(!!a.pending_proposal) || (b.gap_pct ?? 0) - (a.gap_pct ?? 0)),
    [products],
  );
  const moves = useMemo(() => movesByDay(activity), [activity]);
  const moveTotals = moves.reduce((t, d) => ({ drops: t.drops + d.drops, rises: t.rises + d.rises }), { drops: 0, rises: 0 });

  if (error && !products) return <ErrorState message={`We couldn't load the overview: ${error}`} onRetry={load} />;
  if (products === null) {
    return (
      <div className="space-y-10" aria-busy="true" aria-label="Loading overview">
        <Skeleton className="h-[260px] rounded-[14px]" />
        <div className="grid grid-cols-2 gap-6 md:grid-cols-4">{[0, 1, 2, 3].map((i) => <div key={i} className="space-y-2"><Skeleton className="h-3 w-24" /><Skeleton className="h-7 w-14" /><Skeleton className="h-3 w-32" /></div>)}</div>
        <div className="space-y-2"><Skeleton className="h-4 w-40" /><Skeleton className="h-[72px]" /><Skeleton className="h-[72px]" /></div>
      </div>
    );
  }
  if (products.length === 0) {
    return (
      <section className="band">
        <div className="max-w-2xl p-8 sm:p-12">
          <div className="eyebrow text-on-band/60">Welcome to Price Tracker</div>
          <h1 className="display mt-4 text-[40px] leading-[1.04] sm:text-[52px]">Your pricing desk is ready. Add the first product.</h1>
          <p className="mt-4 max-w-lg text-[14px] leading-relaxed text-on-band/75">
            Find it on Amazon.in and Flipkart, set our price and floor. When a competitor moves, you'll get a recommendation to approve here and by email.
          </p>
          <Link to="/add" className="btn-band btn-lg mt-7"><Icon name="plus" className="h-4 w-4" />Add a product</Link>
        </div>
      </section>
    );
  }

  return (
    <motion.div className="space-y-10" variants={stagger} initial="hidden" animate="show">
      <motion.div variants={fadeUp}>
        <CommandBand products={products} pending={pending} lastChecked={stats.lastChecked} />
      </motion.div>

      <motion.section variants={fadeUp} aria-label="This week" className="stat-band">
        <Figure
          label="Competitor moves · 7d"
          value={stats.cuts + stats.raises}
          to="/recommendations"
          sub={<><span className="text-bad">▼ {stats.cuts} cuts</span> · <span className="text-good">▲ {stats.raises} raises</span></>}
        />
        <Figure label="Recommendations · 7d" value={stats.decisions} to="/recommendations" sub={`${stats.recs} to reprice · ${stats.holds} hold`} />
        <Figure label="Our price changes · 7d" value={stats.applied} sub={`${stats.auto} automatic · ${stats.applied - stats.auto} approved`} />
        <Figure label="Listings watched" value={stats.listings} to="/monitoring" sub={`${products.length} product${products.length === 1 ? "" : "s"} · Amazon.in & Flipkart`} />
      </motion.section>

      <motion.section variants={fadeUp} aria-labelledby="attention-title" className="space-y-3">
        <SectionHeader
          id="attention-title"
          title={<>Needs attention {attention.length > 0 && <span className="num ml-1 rounded-full bg-warn-fill/20 px-2 py-0.5 align-middle text-[12px] font-semibold text-warn">{attention.length}</span>}</>}
          sub="Approvals first, then products priced above the lowest competitor."
          action={<Link to="/products" className="link-quiet">All products<Icon name="arrowRight" className="h-3 w-3" /></Link>}
        />
        <div className="card overflow-hidden">
          {attention.length === 0 ? (
            <EmptyState compact icon="done" title="Nothing needs you right now">Every product is at or below the lowest competitor, and nothing is waiting for approval.</EmptyState>
          ) : (
            <ul className="divide-y divide-line">
              {attention.map((p) => <AttentionRow key={p.id} product={p} proposal={pendingByProduct.get(p.id)} />)}
            </ul>
          )}
        </div>
      </motion.section>

      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1.45fr)_minmax(0,1fr)]">
        <motion.section variants={fadeUp} aria-labelledby="moves-title" className="card">
          <div className="flex flex-wrap items-start justify-between gap-3 px-5 pt-4">
            <div>
              <h2 id="moves-title" className="card-title">Market movement</h2>
              <p className="card-sub">Competitor price changes per day, both platforms, last {DAYS} days</p>
            </div>
            <div className="flex gap-4 text-[12px] text-muted">
              <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-[2px] bg-bad-fill" />▼ Cuts <b className="num text-ink">{moveTotals.drops}</b></span>
              <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-[2px] bg-good-fill" />▲ Raises <b className="num text-ink">{moveTotals.rises}</b></span>
            </div>
          </div>
          <div className="px-5 pb-4 pt-6">
            {activity.length === 0 ? (
              <EmptyState compact icon="zap" title="No competitor moves yet">Moves appear here as the scheduler checks each listing.</EmptyState>
            ) : (
              <MovesStrip days={moves} />
            )}
          </div>
        </motion.section>

        <motion.section variants={fadeUp} aria-labelledby="position-title" className="card">
          <div className="px-5 pt-4">
            <h2 id="position-title" className="card-title">Price position</h2>
            <p className="card-sub">Our price against the lowest competitor, per product</p>
          </div>
          <PositionList products={products.filter((p) => p.active)} />
        </motion.section>
      </div>

      <motion.section variants={fadeUp} aria-labelledby="activity-title" className="space-y-3">
        <SectionHeader
          id="activity-title"
          title="Recent activity"
          sub="What changed, what we recommended, what happened next."
          action={<Link to="/recommendations" className="link-quiet">All recommendations<Icon name="arrowRight" className="h-3 w-3" /></Link>}
        />
        <div className="card overflow-hidden">
          {activity.length === 0 ? (
            <EmptyState compact icon="activity" title="No activity yet">Recommendations are made only when a competitor's listing changes.</EmptyState>
          ) : (
            <ul className="divide-y divide-line">{activity.slice(0, 8).map((a) => <ActivityRow key={a.id} a={a} />)}</ul>
          )}
        </div>
      </motion.section>
    </motion.div>
  );
}
