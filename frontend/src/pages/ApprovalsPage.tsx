import { AnimatePresence, motion } from "motion/react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ApiError, listProposals } from "../api/client";
import Icon from "../components/Icon";
import RecommendationCard from "../components/RecommendationCard";
import { ActionBadge, EmptyState, ErrorState, PageHeader, PlatformDot, ProductThumb, Skeleton, Status } from "../components/ui/Primitives";
import { Segmented } from "../components/ui/Tabs";
import type { Proposal } from "../types";
import { STATUS_LABEL, formatInr, formatPct, shortTitle, timeAgo } from "../lib/format";
import { notifyProposalsChanged } from "../lib/events";
import { EASE_OUT } from "../lib/motion";

type View = "pending" | "resolved";

function QueueItem({ p, selected, onSelect }: { p: Proposal; selected: boolean; onSelect: () => void }) {
  return (
    <li>
      <button
        onClick={onSelect}
        aria-current={selected ? "true" : undefined}
        className={`relative flex w-full cursor-pointer gap-3 border-b border-line px-4 py-3.5 text-left transition-colors duration-150 ${selected ? "bg-raised" : "hover:bg-sunken/60"}`}
      >
        {selected && <span className="absolute inset-y-2 left-0 w-[3px] rounded-r-full bg-brand" aria-hidden />}
        <ProductThumb src={p.product_image_url} size={40} />
        <span className="flex min-w-0 flex-1 flex-col gap-2">
        <span className="flex items-start justify-between gap-3">
          <span className="line-clamp-1 text-[13px] font-semibold leading-snug" title={p.product_title}>{shortTitle(p.product_title)}</span>
          <span className="shrink-0 text-[11px] text-muted">{timeAgo(p.resolved_at ?? p.created_at)}</span>
        </span>
        <span className="flex flex-wrap items-center gap-x-2 gap-y-1.5 text-[12px] text-muted">
          {p.marketplace && <PlatformDot marketplace={p.marketplace} />}
          <span className="mono">
            {formatInr(p.from_price_inr)} → <span className="font-semibold text-ink">{formatInr(p.final_price_inr ?? p.to_price_inr)}</span>
          </span>
          <span className="mono text-faint">{formatPct(p.change_pct)}</span>
          <span className="ml-auto"><ActionBadge action={p.action} /></span>
        </span>
        {p.status !== "pending" ? (
          <Status tone={p.status === "approved" || p.status === "auto_applied" ? "good" : p.status === "rejected" || p.status === "failed" ? "bad" : "muted"} className="text-muted">
            {STATUS_LABEL[p.status]}{p.resolved_by ? ` · ${p.resolved_by}` : ""}
          </Status>
        ) : (p.competitor_changed || p.our_price_changed) ? (
          <Status tone="warn" className="text-warn">Data changed since recommended</Status>
        ) : null}
        </span>
      </button>
    </li>
  );
}

export default function ApprovalsPage() {
  const [params, setParams] = useSearchParams();
  const [all, setAll] = useState<Proposal[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<View>("pending");

  const load = useCallback(async () => {
    try {
      setAll(await listProposals());
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const pending = useMemo(() => (all ?? []).filter((p) => p.status === "pending"), [all]);
  const resolved = useMemo(() => (all ?? []).filter((p) => p.status !== "pending").slice(0, 40), [all]);
  const list = view === "pending" ? pending : resolved;
  const requested = Number(params.get("id")) || null;

  // A linked id decides which list is shown.
  useEffect(() => {
    if (requested && all) {
      const found = all.find((p) => p.id === requested);
      if (found) setView(found.status === "pending" ? "pending" : "resolved");
    }
  }, [requested, all]);

  const selected = list.find((p) => p.id === requested) ?? null;
  const desktopSelected = selected ?? list[0] ?? null;
  const select = (id: number | null) => setParams(id ? { id: String(id) } : {}, { replace: true });

  function resolvedOne() {
    notifyProposalsChanged();
    load();
  }

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow={all ? (pending.length ? `${pending.length} waiting for a decision` : "Inbox zero") : undefined}
        title="Approvals"
        description="Every proposed change is already held to its product's floor and max move, and is re-checked against the latest data the moment you approve."
      />

      {error && <ErrorState message={error} onRetry={load} />}

      {all === null && !error ? (
        <div className="grid gap-4 lg:grid-cols-[360px_1fr]">
          <div className="space-y-2"><Skeleton className="h-10" /><Skeleton className="h-[76px]" /><Skeleton className="h-[76px]" /><Skeleton className="h-[76px]" /></div>
          <Skeleton className="hidden h-[460px] rounded-[10px] lg:block" />
        </div>
      ) : all && (
        <div className="card grid overflow-hidden bg-surface lg:grid-cols-[360px_1fr]">
          {/* Queue */}
          <section className={`border-line lg:border-r ${selected ? "hidden lg:block" : ""}`} aria-label="Queue">
            <div className="flex items-center justify-between border-b border-line bg-raised px-4 py-2.5">
              <Segmented
                label="Show"
                value={view}
                onChange={(v) => { setView(v); select(null); }}
                options={[
                  { value: "pending", label: `Pending ${pending.length}` },
                  { value: "resolved", label: "Resolved" },
                ]}
              />
            </div>
            {list.length === 0 ? (
              <EmptyState icon="done" title={view === "pending" ? "You're all caught up" : "Nothing resolved yet"}>
                {view === "pending" ? "New recommendations appear here, and in the ops team's inbox, when a competitor moves." : "Approved and rejected changes will be listed here."}
              </EmptyState>
            ) : (
              <ul className="max-h-[72vh] overflow-y-auto">
                <AnimatePresence initial={false}>
                  {list.map((p) => (
                    <motion.div key={p.id} layout="position" exit={{ opacity: 0, transition: { duration: 0.12 } }}>
                      <QueueItem p={p} selected={desktopSelected?.id === p.id} onSelect={() => select(p.id)} />
                    </motion.div>
                  ))}
                </AnimatePresence>
              </ul>
            )}
          </section>

          {/* Decision */}
          <section className={`min-w-0 bg-raised ${selected ? "" : "hidden lg:block"}`} aria-label="Decision">
            {selected && (
              <div className="border-b border-line px-3 py-2 lg:hidden">
                <button className="btn-quiet btn-sm" onClick={() => select(null)}>
                  <Icon name="back" className="h-3.5 w-3.5" />Queue
                </button>
              </div>
            )}
            {desktopSelected ? (
              <motion.div key={desktopSelected.id} initial={{ opacity: 0 }} animate={{ opacity: 1, transition: { duration: 0.18, ease: EASE_OUT } }}>
                <RecommendationCard proposal={desktopSelected} onResolved={resolvedOne} showProduct flush />
              </motion.div>
            ) : (
              <div className="grid h-full min-h-[240px] place-items-center text-[13px] text-muted">Select a recommendation to review it.</div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
