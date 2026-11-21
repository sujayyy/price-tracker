import { AnimatePresence, motion } from "motion/react";
import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { ApiError, listProducts, updateProduct } from "../api/client";
import Icon from "../components/Icon";
import PositionBadge from "../components/PositionBadge";
import Popover from "../components/ui/Popover";
import { ActionBadge, Delta, EmptyState, ErrorState, PageHeader, PlatformDot, ProductThumb, RollingNumber, Skeleton, Sparkline, Status } from "../components/ui/Primitives";
import { Segmented } from "../components/ui/Tabs";
import type { Product } from "../types";
import { MARKETPLACE_SHORT, formatInr, freqLabel, shortTitle, timeAgo } from "../lib/format";
import { rowLayout } from "../lib/motion";

type Filter = "all" | "attention" | "pricier" | "competitive" | "paused";
type SortKey = "title" | "ours" | "lowest" | "gap" | "checked";
type ColumnId = "ours" | "lowest" | "gap" | "stock" | "recommendation" | "trend" | "checked" | "frequency";

const FILTERS: { value: Filter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "attention", label: "Needs attention" },
  { value: "pricier", label: "Pricier" },
  { value: "competitive", label: "Competitive" },
  { value: "paused", label: "Paused" },
];

const COLUMNS: { id: ColumnId; label: string; sort?: SortKey; align?: "right"; defaultOn: boolean }[] = [
  { id: "ours", label: "Our price", sort: "ours", align: "right", defaultOn: true },
  { id: "lowest", label: "Lowest competitor", sort: "lowest", align: "right", defaultOn: true },
  { id: "gap", label: "Gap", sort: "gap", defaultOn: true },
  { id: "stock", label: "Competitor stock", defaultOn: false },
  { id: "recommendation", label: "Recommendation", defaultOn: true },
  { id: "trend", label: "Trend", defaultOn: false },
  { id: "checked", label: "Last checked", sort: "checked", defaultOn: true },
  { id: "frequency", label: "Frequency", defaultOn: false },
];

const PAGE = 25;
const COLS_KEY = "priceops.products-columns";

function readColumns(): Set<ColumnId> {
  try {
    const raw = localStorage.getItem(COLS_KEY);
    if (raw) return new Set(JSON.parse(raw) as ColumnId[]);
  } catch {
    /* ignore */
  }
  return new Set(COLUMNS.filter((c) => c.defaultOn).map((c) => c.id));
}

const matches = (p: Product, f: Filter) =>
  f === "all" ? true
  : f === "attention" ? !!p.pending_proposal || p.position === "we_are_pricier"
  : f === "pricier" ? p.position === "we_are_pricier"
  : f === "competitive" ? p.position === "we_are_cheaper" || p.position === "same_price"
  : !p.active;

const lowestListing = (p: Product) => p.listings.find((l) => l.id === p.lowest_listing_id);

function sortValue(p: Product, k: SortKey): number | string {
  switch (k) {
    case "title": return p.title.toLowerCase();
    case "ours": return p.our_price_inr ?? Infinity;
    case "lowest": return p.lowest_price_inr ?? Infinity;
    case "gap": return p.gap_pct ?? -Infinity;
    case "checked": return p.last_checked_at ? -new Date(p.last_checked_at).getTime() : Infinity;
  }
}

function LowestCell({ p }: { p: Product }) {
  const l = lowestListing(p);
  return (
    <div className="inline-flex flex-col items-end">
      <RollingNumber value={p.lowest_price_inr} format={formatInr} className="mono font-medium" />
      <span className="mt-0.5 flex items-center gap-1.5 text-[11px] text-muted">
        {l && <><PlatformDot marketplace={l.marketplace} />{MARKETPLACE_SHORT[l.marketplace]}</>}
        <Delta from={l?.previous_price_inr} to={l?.latest?.price_inr} size="xs" />
      </span>
    </div>
  );
}

function Cell({ id, p }: { id: ColumnId; p: Product }) {
  const active = p.listings.filter((l) => l.active);
  switch (id) {
    case "ours":
      return <RollingNumber value={p.our_price_inr} format={formatInr} tint={false} className="mono font-medium" />;
    case "lowest":
      return <LowestCell p={p} />;
    case "gap":
      return <PositionBadge position={p.position} gap={p.gap_inr} gapPct={p.gap_pct} compact />;
    case "stock": {
      const out = active.filter((l) => l.latest?.in_stock === false).length;
      return active.length ? (
        <Status tone={out === active.length ? "good" : out ? "warn" : "muted"} className="text-muted">
          {out === 0 ? `All ${active.length} in stock` : out === active.length ? "All out of stock" : `${out} of ${active.length} out`}
        </Status>
      ) : <span className="text-faint">—</span>;
    }
    case "recommendation":
      return p.pending_proposal ? <ActionBadge action={p.pending_proposal.action} price={p.pending_proposal.to_price_inr} /> : <span className="text-[12px] text-faint">—</span>;
    case "trend":
      return <Sparkline values={p.sparkline} />;
    case "checked":
      return <span className="text-[12px] text-muted">{timeAgo(p.last_checked_at)}</span>;
    case "frequency":
      return <span className="text-[12px] text-muted">{freqLabel(p.check_every_hours)}</span>;
  }
}

export default function ProductsPage() {
  const navigate = useNavigate();
  const [items, setItems] = useState<Product[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: "gap", dir: -1 });
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);
  const [columns, setColumns] = useState<Set<ColumnId>>(readColumns);
  const [page, setPage] = useState(0);

  const load = useCallback(async () => {
    try {
      setItems(await listProducts());
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    load();
    const t = window.setInterval(load, 30_000); // new readings flash in place
    return () => window.clearInterval(t);
  }, [load]);

  useEffect(() => setPage(0), [filter, query, sort]);

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    const xs = (items ?? []).filter((p) => matches(p, filter) && (!q || `${p.title} ${p.our_sku ?? ""}`.toLowerCase().includes(q)));
    return xs.sort((a, b) => {
      const va = sortValue(a, sort.key);
      const vb = sortValue(b, sort.key);
      return (va < vb ? -1 : va > vb ? 1 : 0) * sort.dir;
    });
  }, [items, filter, query, sort]);
  const pageItems = shown.slice(page * PAGE, page * PAGE + PAGE);
  const pages = Math.max(1, Math.ceil(shown.length / PAGE));
  const counts = useMemo(() => Object.fromEntries(FILTERS.map((f) => [f.value, (items ?? []).filter((p) => matches(p, f.value)).length])), [items]);
  const visible = COLUMNS.filter((c) => columns.has(c.id));

  function toggleColumn(id: ColumnId) {
    setColumns((cs) => {
      const next = new Set(cs);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      try {
        localStorage.setItem(COLS_KEY, JSON.stringify([...next]));
      } catch {
        /* ignore */
      }
      return next;
    });
  }

  function onSort(k: SortKey) {
    setSort((s) => (s.key === k ? { key: k, dir: (s.dir * -1) as 1 | -1 } : { key: k, dir: k === "gap" ? -1 : 1 }));
  }

  function toggle(id: number) {
    setSelected((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function setActive(ids: number[], active: boolean) {
    setBusy(true);
    try {
      const updated = await Promise.all(ids.map((id) => updateProduct(id, { active })));
      setItems((xs) => xs?.map((x) => updated.find((u) => u.id === x.id) ?? x) ?? null);
      setSelected(new Set());
      toast.success(`${active ? "Resumed" : "Paused"} ${ids.length === 1 ? updated[0].title.slice(0, 40) : `${ids.length} products`}`);
    } catch (err) {
      toast.error("Couldn't update every product", { description: err instanceof ApiError ? err.message : String(err) });
    } finally {
      setBusy(false);
    }
  }

  const allSelected = pageItems.length > 0 && pageItems.every((p) => selected.has(p.id));

  const header = (label: string, key?: SortKey, align?: "right") => {
    const activeSort = key && sort.key === key;
    return (
      <th scope="col" aria-sort={activeSort ? (sort.dir === 1 ? "ascending" : "descending") : undefined} className={`whitespace-nowrap px-3 py-2.5 font-medium ${align === "right" ? "text-right" : ""}`}>
        {key ? (
          <button onClick={() => onSort(key)} className={`inline-flex cursor-pointer items-center gap-1 uppercase tracking-[0.06em] hover:text-ink ${activeSort ? "text-ink" : ""}`}>
            {label}
            <Icon name={activeSort ? (sort.dir === 1 ? "arrowUp" : "arrowDown") : "sort"} className={`h-3 w-3 ${activeSort ? "" : "opacity-40"}`} />
          </button>
        ) : label}
      </th>
    );
  };

  return (
    <div className="space-y-5">
      <PageHeader
        title="Products"
        description={items ? `${items.length} product${items.length === 1 ? "" : "s"} watched against ${items.reduce((n, p) => n + p.listings.filter((l) => l.active).length, 0)} competitor listings. We always price against the lowest in-stock competitor.` : "Our products and the lowest competitor price each one is compared against."}
        actions={<Link to="/add" className="btn-primary"><Icon name="plus" />Add product</Link>}
      />

      <div className="card overflow-hidden">
        {/* Toolbar */}
        <div className="flex flex-wrap items-center gap-2.5 border-b border-line px-3 py-2.5 sm:px-4">
          <div className="relative min-w-[200px] flex-1 sm:max-w-[280px]">
            <Icon name="search" className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-faint" />
            <input className="input h-8 pl-8" placeholder="Search by name or SKU" aria-label="Search products" value={query} onChange={(e) => setQuery(e.target.value)} />
          </div>
          <div className="max-w-full overflow-x-auto">
            <Segmented label="Filter products" value={filter} onChange={setFilter} options={FILTERS.map((f) => ({ value: f.value, label: counts[f.value] ? `${f.label} ${counts[f.value]}` : f.label }))} />
          </div>
          <div className="ml-auto hidden md:block">
            <Popover
              label="Columns"
              trigger={({ open, toggle: t, ref }) => (
                <button ref={ref} className="btn-quiet btn-sm" aria-expanded={open} onClick={t}><Icon name="sliders" className="h-3.5 w-3.5" />Columns</button>
              )}
            >
              {() => (
                <div className="w-56 p-1.5" role="group" aria-label="Visible columns">
                  {COLUMNS.map((c) => (
                    <label key={c.id} className="flex cursor-pointer items-center gap-2.5 rounded-[5px] px-2.5 py-1.5 text-[13px] hover:bg-sunken">
                      <input type="checkbox" className="h-3.5 w-3.5 accent-[rgb(var(--accent))]" checked={columns.has(c.id)} onChange={() => toggleColumn(c.id)} />
                      {c.label}
                    </label>
                  ))}
                </div>
              )}
            </Popover>
          </div>
        </div>

        <AnimatePresence initial={false}>
          {selected.size > 0 && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1, transition: { duration: 0.15 } }}
              exit={{ opacity: 0, transition: { duration: 0.1 } }}
              className="flex items-center gap-2 border-b border-line bg-brand/[0.06] px-4 py-2 text-[13px]"
              role="region"
              aria-label="Bulk actions"
            >
              <span className="font-medium">{selected.size} selected</span>
              <span className="text-faint">·</span>
              <button className="btn-quiet btn-sm" disabled={busy} onClick={() => setActive([...selected], false)}><Icon name="pause" className="h-3.5 w-3.5" />Pause</button>
              <button className="btn-quiet btn-sm" disabled={busy} onClick={() => setActive([...selected], true)}><Icon name="play" className="h-3.5 w-3.5" />Resume</button>
              <button className="btn-quiet btn-sm ml-auto" onClick={() => setSelected(new Set())}>Clear</button>
            </motion.div>
          )}
        </AnimatePresence>

        {error && <div className="p-4"><ErrorState message={`We couldn't load products: ${error}`} onRetry={load} /></div>}

        {items === null && !error && (
          <div className="divide-y divide-line" aria-busy="true" aria-label="Loading products">
            {[0, 1, 2, 3, 4].map((i) => (
              <div key={i} className="flex items-center gap-4 px-4 py-3.5">
                <Skeleton className="h-4 w-4" />
                <div className="flex-1 space-y-1.5"><Skeleton className="h-3.5 w-2/3" /><Skeleton className="h-3 w-1/4" /></div>
                <Skeleton className="hidden h-4 w-16 md:block" /><Skeleton className="hidden h-4 w-20 md:block" /><Skeleton className="h-4 w-14" />
              </div>
            ))}
          </div>
        )}

        {items?.length === 0 && (
          <EmptyState icon="package" title="Start monitoring your first product" action={<Link to="/add" className="btn-primary"><Icon name="plus" />Add product</Link>}>
            Add one of our products and its listings on Amazon.in and Flipkart.
          </EmptyState>
        )}

        {items && items.length > 0 && shown.length === 0 && (
          <EmptyState icon="search" title="No products match" action={<button className="btn-ghost" onClick={() => { setQuery(""); setFilter("all"); }}>Clear filters</button>} />
        )}

        {pageItems.length > 0 && (
          <>
            <div className="relative hidden overflow-x-auto md:block">
              <table className="w-full text-left text-[13px]">
                <thead className="thead">
                  <tr className="border-b border-line">
                    <th scope="col" className="w-10 py-2 pl-4 pr-2">
                      <input type="checkbox" aria-label="Select all on this page" className="h-4 w-4 cursor-pointer accent-[rgb(var(--accent))]" checked={allSelected}
                        onChange={() => setSelected(allSelected ? new Set() : new Set(pageItems.map((p) => p.id)))} />
                    </th>
                    {header("Product", "title")}
                    {visible.map((c) => <Fragment key={c.id}>{header(c.label, c.sort, c.align)}</Fragment>)}
                    <th scope="col" className="w-[96px] px-3 py-2"><span className="sr-only">Actions</span></th>
                  </tr>
                </thead>
                <tbody>
                  <AnimatePresence initial={false}>
                    {pageItems.map((p) => (
                      <motion.tr
                        key={p.id}
                        layout="position"
                        transition={rowLayout}
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0, transition: { duration: 0.12 } }}
                        onClick={() => navigate(`/products/${p.id}`)}
                        className={`group cursor-pointer border-b border-line last:border-0 transition-colors duration-150 hover:bg-sunken/50 ${selected.has(p.id) ? "bg-brand/[0.05]" : ""} ${p.active ? "" : "text-muted"}`}
                      >
                        <td className="py-3 pl-4 pr-2" onClick={(e) => e.stopPropagation()}>
                          <input type="checkbox" aria-label={`Select ${p.title}`} className="h-4 w-4 cursor-pointer accent-[rgb(var(--accent))]" checked={selected.has(p.id)} onChange={() => toggle(p.id)} />
                        </td>
                        <td className="min-w-[320px] px-3 py-3">
                          <div className="flex items-center gap-3">
                          <ProductThumb src={p.image_url} size={44} />
                          <div className="min-w-0">
                          <Link to={`/products/${p.id}`} onClick={(e) => e.stopPropagation()} className="line-clamp-1 text-[14px] font-medium text-ink hover:underline" title={p.title}>{shortTitle(p.title)}</Link>
                          <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[12px] text-muted">
                            {p.our_sku ? <span className="code mr-1">{p.our_sku}</span> : <span className="mr-1 text-faint">No SKU</span>}
                            {p.listings.map((l) => (
                              <span key={l.id} className={`inline-flex items-center gap-1 ${l.active ? "" : "opacity-50"} ${l.is_lowest && p.listings.filter((x) => x.active).length > 1 ? "font-medium text-ink" : ""}`} title={l.is_lowest ? "Lowest in-stock competitor" : undefined}>
                                <PlatformDot marketplace={l.marketplace} />{MARKETPLACE_SHORT[l.marketplace]}
                              </span>
                            ))}
                            {!p.active && <span className="chip">Paused</span>}
                          </div>
                          </div>
                          </div>
                        </td>
                        {visible.map((c) => (
                          <td key={c.id} className={`whitespace-nowrap px-3 py-3.5 ${c.align === "right" ? "text-right" : ""}`}><Cell id={c.id} p={p} /></td>
                        ))}
                        <td className="px-3 py-3 text-right" onClick={(e) => e.stopPropagation()}>
                          <div className="flex justify-end gap-1 opacity-0 transition-opacity duration-150 focus-within:opacity-100 group-hover:opacity-100">
                            {p.pending_proposal && <Link to={`/approvals?id=${p.pending_proposal.id}`} className="btn-primary btn-sm">Review</Link>}
                            <button className="icon-btn" aria-label={p.active ? `Pause ${p.title}` : `Resume ${p.title}`} title={p.active ? "Pause" : "Resume"} disabled={busy} onClick={() => setActive([p.id], !p.active)}>
                              <Icon name={p.active ? "pause" : "play"} className="h-3.5 w-3.5" />
                            </button>
                            <Link to={`/products/${p.id}`} className="icon-btn" aria-label={`Open ${p.title}`} title="Open"><Icon name="chevronRight" /></Link>
                          </div>
                        </td>
                      </motion.tr>
                    ))}
                  </AnimatePresence>
                </tbody>
              </table>
            </div>

            {/* Phones: stacked rows */}
            <ul className="divide-y divide-line md:hidden">
              {pageItems.map((p) => (
                <li key={p.id} className="flex gap-3 px-4 py-3.5">
                  <input type="checkbox" aria-label={`Select ${p.title}`} className="mt-1 h-4 w-4 accent-[rgb(var(--accent))]" checked={selected.has(p.id)} onChange={() => toggle(p.id)} />
                  <ProductThumb src={p.image_url} size={48} />
                  <Link to={`/products/${p.id}`} className="min-w-0 flex-1">
                    <span className="line-clamp-2 text-[14px] font-medium" title={p.title}>{shortTitle(p.title)}</span>
                    {p.our_sku && <span className="code mt-0.5 block text-muted">{p.our_sku}</span>}
                    <span className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1.5 text-[12px]">
                      <span className="text-muted">Ours <span className="mono font-medium text-ink">{formatInr(p.our_price_inr)}</span></span>
                      <span className="text-muted">Lowest <span className="mono font-medium text-ink">{formatInr(p.lowest_price_inr)}</span></span>
                      <span><PositionBadge position={p.position} gap={p.gap_inr} gapPct={p.gap_pct} compact /></span>
                      <span className={p.pending_proposal ? "col-span-2" : ""}>{p.pending_proposal ? <ActionBadge action={p.pending_proposal.action} price={p.pending_proposal.to_price_inr} /> : <span className="text-muted">{timeAgo(p.last_checked_at)}</span>}</span>
                    </span>
                  </Link>
                </li>
              ))}
            </ul>

            {/* Pagination */}
            <div className="flex items-center justify-between border-t border-line px-4 py-2.5 text-[12px] text-muted">
              <span className="num">{page * PAGE + 1}–{Math.min(shown.length, page * PAGE + PAGE)} of {shown.length}</span>
              <div className="flex gap-1">
                <button className="btn-quiet btn-sm" disabled={page === 0} onClick={() => setPage((x) => x - 1)}>Previous</button>
                <button className="btn-quiet btn-sm" disabled={page >= pages - 1} onClick={() => setPage((x) => x + 1)}>Next</button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
