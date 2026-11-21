import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, getMonitoring } from "../api/client";
import Icon from "../components/Icon";
import { EmptyState, ErrorState, PageHeader, PlatformDot, SectionHeader, Skeleton, Status, type StatusTone } from "../components/ui/Primitives";
import type { ListingHealth, Monitoring } from "../types";
import { MARKETPLACE_LABEL, formatDateTime, formatInr, freqLabel, shortTitle, timeAgo, timeUntil } from "../lib/format";

const HEALTH: Record<ListingHealth["status"], { tone: StatusTone; label: string }> = {
  ok: { tone: "good", label: "Healthy" },
  failing: { tone: "bad", label: "Failing" },
  paused: { tone: "muted", label: "Paused" },
  not_checked: { tone: "muted", label: "Not checked yet" },
};
const ORDER = { failing: 0, ok: 1, not_checked: 2, paused: 3 } as const;

function duration(a: string, b: string | null): string {
  if (!b) return "running";
  const s = Math.max(0, Math.round((new Date(b).getTime() - new Date(a).getTime()) / 1000));
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`;
}

function Stat({ label, children, sub }: { label: string; children: React.ReactNode; sub?: React.ReactNode }) {
  return (
    <div>
      <div className="eyebrow">{label}</div>
      <div className="mt-2 text-[24px] font-semibold leading-none tracking-[-0.03em]">{children}</div>
      {sub && <div className="mt-1.5 text-[12px] text-muted">{sub}</div>}
    </div>
  );
}

export default function MonitoringPage() {
  const [data, setData] = useState<Monitoring | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await getMonitoring());
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    }
  }, []);
  useEffect(() => {
    load();
    const t = window.setInterval(load, 60_000);
    return () => window.clearInterval(t);
  }, [load]);

  if (error && !data) return <ErrorState message={`We couldn't load monitoring status: ${error}`} onRetry={load} />;
  if (!data) return <div className="space-y-8"><div className="space-y-3"><Skeleton className="h-10 w-56" /><Skeleton className="h-3 w-96 max-w-full" /></div><div className="grid grid-cols-2 gap-6 md:grid-cols-4">{[0, 1, 2, 3].map((i) => <div key={i} className="space-y-2"><Skeleton className="h-3 w-24" /><Skeleton className="h-6 w-20" /></div>)}</div><div className="space-y-1.5"><Skeleton className="h-11" /><Skeleton className="h-14" /><Skeleton className="h-14" /></div></div>;

  const listings = [...data.listings].sort((a, b) => ORDER[a.status] - ORDER[b.status] || a.product_title.localeCompare(b.product_title));
  const failing = listings.filter((l) => l.status === "failing").length;
  const idle = !data.last_run_at || Date.now() - new Date(data.last_run_at).getTime() > 2 * 3600_000;
  const aiPct = data.ai_daily_limit ? Math.min(100, (data.ai_runs_today / data.ai_daily_limit) * 100) : 0;

  return (
    <div className="space-y-9">
      <PageHeader
        title="Monitoring"
        description="Every competitor listing is re-checked on its product's schedule. The scheduler runs hourly and only fetches listings that are due."
        actions={<button className="btn-ghost btn-sm" onClick={load}><Icon name="refresh" className="h-3.5 w-3.5" />Refresh</button>}
      />

      {/* Status band */}
      <section aria-label="Scheduler status" className="stat-band">
        <Stat label="Scheduler" sub={data.last_run_at ? formatDateTime(data.last_run_at) : "No run recorded"}>
          <Status tone={!data.last_run_at ? "muted" : idle ? "warn" : "good"} live={!idle} className="text-[20px]">
            <span className="text-[20px] font-semibold tracking-[-0.02em]">{data.last_run_at ? `Ran ${timeAgo(data.last_run_at)}` : "Idle"}</span>
          </Status>
        </Stat>
        <Stat label="Checks · 24h" sub={`${data.errors_24h} error${data.errors_24h === 1 ? "" : "s"}`}>
          <span className="num">{data.runs_24h}</span>
        </Stat>
        <Stat label="Listings" sub={failing ? <span className="text-bad">{failing} failing</span> : "All healthy"}>
          <span className="num">{listings.filter((l) => l.status !== "paused").length}</span>
          <span className="ml-1 text-[13px] font-normal text-muted">active</span>
        </Stat>
        <Stat label="Recommendation runs · today" sub={<span className="mt-1 block h-1 w-28 overflow-hidden rounded-full bg-sunken"><span className={`block h-full rounded-full ${aiPct >= 90 ? "bg-warn-fill" : "bg-brand"}`} style={{ width: `${aiPct}%` }} /></span>}>
          <span className="num">{data.ai_runs_today}</span>
          <span className="ml-1 text-[13px] font-normal text-muted">/ {data.ai_daily_limit}</span>
        </Stat>
      </section>

      {/* Listing health */}
      <section aria-labelledby="health-title" className="space-y-3">
        <SectionHeader id="health-title" title="Listing health" sub="Failing listings first. A listing fails when the marketplace blocks the request or the page can't be read." />
        {listings.length === 0 ? (
          <div className="card"><EmptyState icon="monitoring" title="Nothing to monitor yet" action={<Link to="/add" className="btn-primary">Add product</Link>}>Add a product and its competitor listings to start monitoring.</EmptyState></div>
        ) : (
          <div className="card relative overflow-x-auto">
            <table className="w-full min-w-[820px] text-left text-[13px]">
              <thead className="thead">
                <tr className="border-b border-line">
                  <th scope="col" className="px-4 py-2.5 font-medium">Listing</th>
                  <th scope="col" className="px-3 py-2 font-medium">Status</th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">Price</th>
                  <th scope="col" className="px-3 py-2 font-medium">Last check</th>
                  <th scope="col" className="px-3 py-2 font-medium">Next due</th>
                  <th scope="col" className="px-3 py-2 font-medium">Frequency</th>
                </tr>
              </thead>
              <tbody>
                {listings.map((l) => (
                  <tr key={l.listing_id} className="border-b border-line last:border-0 hover:bg-sunken/40">
                    <td className="max-w-[320px] px-4 py-2.5">
                      <Link to={`/products/${l.product_id}`} className="line-clamp-1 font-medium hover:underline" title={l.product_title}>{shortTitle(l.product_title)}</Link>
                      <span className="mt-0.5 flex items-center gap-1.5 text-[12px] text-muted"><PlatformDot marketplace={l.marketplace} />{MARKETPLACE_LABEL[l.marketplace]}</span>
                    </td>
                    <td className="px-3 py-2.5">
                      <Status tone={HEALTH[l.status].tone}>{HEALTH[l.status].label}{l.status === "failing" ? ` · ${l.consecutive_failures}×` : ""}</Status>
                      {l.last_error && <span className="mt-0.5 block max-w-[240px] truncate text-[11px] text-muted" title={l.last_error}>{l.last_error}</span>}
                    </td>
                    <td className="mono px-3 py-2.5 text-right font-medium">{l.in_stock === false ? <span className="text-[12px] font-normal text-warn">Out of stock</span> : formatInr(l.price_inr)}</td>
                    <td className="px-3 py-2.5 text-[12px] text-muted" title={l.last_checked_at ? formatDateTime(l.last_checked_at) : undefined}>{timeAgo(l.last_checked_at)}</td>
                    <td className="px-3 py-2.5 text-[12px]" title={l.next_due_at ? formatDateTime(l.next_due_at) : undefined}>{l.status === "paused" ? <span className="text-muted">—</span> : timeUntil(l.next_due_at)}</td>
                    <td className="px-3 py-2.5 text-[12px]">
                      <Link to={`/products/${l.product_id}?tab=settings`} className="text-muted underline-offset-2 hover:text-ink hover:underline" title="Change in the product's settings">{freqLabel(l.check_every_hours)}</Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Recent runs */}
      <section aria-labelledby="runs-title" className="space-y-3">
        <SectionHeader id="runs-title" title="Recent runs" sub="Scheduled checks, manual rechecks and demo simulations." />
        {data.runs.length === 0 ? (
          <p className="text-[13px] text-muted">No runs recorded yet.</p>
        ) : (
          <div className="card relative overflow-x-auto">
            <table className="w-full min-w-[640px] text-left text-[13px]">
              <thead className="thead">
                <tr className="border-b border-line">
                  <th scope="col" className="px-4 py-2.5 font-medium">Started</th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">Listings</th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">Recommendations</th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">Errors</th>
                  <th scope="col" className="px-3 py-2 font-medium">Duration</th>
                  <th scope="col" className="px-3 py-2 font-medium">Notes</th>
                </tr>
              </thead>
              <tbody>
                {data.runs.map((r) => (
                  <tr key={r.id} className="border-b border-line last:border-0">
                    <td className="px-4 py-2 text-[12px]" title={formatDateTime(r.started_at)}>{timeAgo(r.started_at)}</td>
                    <td className="num px-3 py-2 text-right">{r.items_checked}</td>
                    <td className="num px-3 py-2 text-right">{r.agent_invocations}</td>
                    <td className={`num px-3 py-2 text-right ${r.errors ? "font-medium text-bad" : "text-muted"}`}>{r.errors}</td>
                    <td className="px-3 py-2 text-[12px] text-muted">{duration(r.started_at, r.finished_at)}</td>
                    <td className="max-w-[320px] truncate px-3 py-2 text-[12px] text-muted" title={r.notes ?? undefined}>{r.notes?.split("\n")[0] ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
