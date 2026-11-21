import { useReducedMotion } from "motion/react";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { getMonitoring, listProducts, listProposals } from "../../api/client";
import type { Marketplace, Monitoring, Product, Proposal } from "../../types";
import { MARKETPLACE_SHORT, formatInr, shortTitle, timeAgo } from "../../lib/format";
import Icon from "../Icon";
import Popover from "../ui/Popover";
import { ActionBadge, Kbd, PlatformDot, Status, type StatusTone } from "../ui/Primitives";
import { Logo } from "./Sidebar";

function useMonitoring(): Monitoring | null {
  const [m, setM] = useState<Monitoring | null>(null);
  useEffect(() => {
    let alive = true;
    const load = () => getMonitoring().then((x) => alive && setM(x)).catch(() => {});
    load();
    const t = window.setInterval(load, 60_000);
    return () => {
      alive = false;
      window.clearInterval(t);
    };
  }, []);
  return m;
}

function monitoringState(m: Monitoring | null): { tone: StatusTone; text: string; live: boolean; title: string } {
  if (!m) return { tone: "muted", text: "Monitoring", live: false, title: "Monitoring status" };
  // "Last check" is the freshest listing reading (the same figure the Overview shows), whether it
  // came from the scheduler, a manual recheck or a newly added product.
  const checks = m.listings.map((l) => l.last_checked_at).filter((t): t is string => !!t).sort();
  const freshest = checks.length ? checks[checks.length - 1] : m.last_run_at;
  if (!freshest) return { tone: "muted", text: "Not checked yet", live: false, title: "No listing has been checked yet" };
  const title = m.last_run_at ? `Scheduler last ran ${timeAgo(m.last_run_at)}` : "The scheduler hasn't run yet";
  const failing = m.listings.filter((l) => l.status === "failing").length;
  const idle = !m.last_run_at || Date.now() - new Date(m.last_run_at).getTime() > 2 * 3600_000;
  if (failing) return { tone: "warn", text: `${failing} listing${failing === 1 ? "" : "s"} failing`, live: false, title };
  if (idle) return { tone: "warn", text: `Last check ${timeAgo(freshest)}`, live: false, title: `${title}: check the cron job` };
  return { tone: "teal", text: `Live · checked ${timeAgo(freshest)}`, live: true, title };
}

// ---------------------------------------------------------------------------------------------
// Movement tape: the latest competitor move on every listing, like a desk ticker.

interface Move {
  key: string;
  productId: number;
  product: string;
  marketplace: Marketplace;
  delta: number | null; // null = stock change
  price: number | null;
  inStock: boolean | null;
  at: string | null;
}

function movesOf(products: Product[]): Move[] {
  const out: Move[] = [];
  for (const p of products) {
    if (!p.active) continue;
    for (const l of p.listings) {
      if (!l.active || !l.latest) continue;
      const price = l.latest.price_inr;
      const out_of_stock = l.latest.in_stock === false;
      const delta = !out_of_stock && price != null && l.previous_price_inr != null ? price - l.previous_price_inr : null;
      if (!out_of_stock && (delta == null || Math.abs(delta) < 0.5)) continue;
      out.push({ key: `${l.id}`, productId: p.id, product: shortTitle(p.title, 4, 26), marketplace: l.marketplace, delta, price, inStock: l.latest.in_stock, at: l.last_checked_at });
    }
  }
  return out.sort((a, b) => (b.at ?? "").localeCompare(a.at ?? "")).slice(0, 14);
}

function TapeItems({ moves, hidden = false }: { moves: Move[]; hidden?: boolean }) {
  return (
    <ul className="flex shrink-0 items-center" aria-hidden={hidden || undefined}>
      {moves.map((m) => (
        <li key={m.key} className="flex items-center">
          <Link
            to={`/products/${m.productId}`}
            tabIndex={hidden ? -1 : undefined}
            className="flex h-8 items-center gap-2 whitespace-nowrap px-4 text-[12px] text-muted transition-colors duration-150 hover:text-ink"
          >
            <PlatformDot marketplace={m.marketplace} />
            <span>{MARKETPLACE_SHORT[m.marketplace]}</span>
            <span className="font-medium text-ink">{m.product}</span>
            {m.inStock === false ? (
              <span className="text-warn">out of stock</span>
            ) : (
              <>
                <span className={`mono inline-flex items-center gap-0.5 font-medium ${m.delta! < 0 ? "text-bad" : "text-good"}`}>
                  <span aria-hidden>{m.delta! < 0 ? "▼" : "▲"}</span>
                  {formatInr(Math.abs(m.delta!))}
                  <span className="sr-only">{m.delta! < 0 ? " cut" : " raise"}</span>
                </span>
                <span className="mono text-ink">{formatInr(m.price)}</span>
              </>
            )}
            <span className="text-faint">{timeAgo(m.at)}</span>
          </Link>
          <span className="h-3 w-px bg-line-strong" aria-hidden />
        </li>
      ))}
    </ul>
  );
}

function MovementTape() {
  const [moves, setMoves] = useState<Move[] | null>(null);
  const reduce = useReducedMotion();
  const wrap = useRef<HTMLDivElement>(null);
  const track = useRef<HTMLDivElement>(null);
  const [scroll, setScroll] = useState<number | null>(null); // seconds per loop, null = static

  useEffect(() => {
    let alive = true;
    const load = () => listProducts().then((ps) => alive && setMoves(movesOf(ps))).catch(() => alive && setMoves([]));
    load();
    const t = window.setInterval(load, 60_000);
    return () => {
      alive = false;
      window.clearInterval(t);
    };
  }, []);

  // Scroll only when the moves don't fit; ~32px a second, calm enough to read.
  useLayoutEffect(() => {
    const measure = () => {
      const w = wrap.current?.clientWidth ?? 0;
      const content = track.current?.scrollWidth ?? 0;
      setScroll(!reduce && content > w ? content / 32 : null);
    };
    measure();
    const ro = new ResizeObserver(measure);
    if (wrap.current) ro.observe(wrap.current);
    return () => ro.disconnect();
  }, [moves, reduce]);

  return (
    <div className="flex h-8 items-center border-t border-line/70">
      <span className="flex shrink-0 items-center gap-2 border-r border-line/70 pl-4 pr-3 sm:pl-6 lg:pl-8">
        <span className="h-1.5 w-1.5 rounded-full bg-accent live-dot text-accent" aria-hidden />
        <span className="eyebrow text-[10px]">Market</span>
      </span>
      <div
        ref={wrap}
        className="group relative min-w-0 flex-1 overflow-hidden [mask-image:linear-gradient(90deg,transparent,black_20px,black_calc(100%-40px),transparent)]"
        aria-label="Latest competitor moves"
        role="region"
      >
        {moves === null ? null : moves.length === 0 ? (
          <p className="px-4 text-[12px] text-muted">No competitor moves yet. Each listing is checked on its product's schedule.</p>
        ) : (
          <div
            className="flex w-max group-hover:[animation-play-state:paused] group-focus-within:[animation-play-state:paused]"
            style={scroll ? { animation: `tape ${scroll}s linear infinite` } : undefined}
          >
            <div ref={track} className="flex">
              <TapeItems moves={moves} />
            </div>
            {scroll && <TapeItems moves={moves} hidden />}
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------

export default function TopBar({ pending, onMenu, onSearch }: { pending: number; onMenu: () => void; onSearch: () => void }) {
  const monitoring = useMonitoring();
  const state = monitoringState(monitoring);
  const [queue, setQueue] = useState<Proposal[] | null>(null);
  const loadQueue = useCallback(() => {
    listProposals("pending").then(setQueue).catch(() => setQueue([]));
  }, []);
  const failing = monitoring?.listings.filter((l) => l.status === "failing") ?? [];
  const count = pending + failing.length;

  return (
    <header className="sticky top-0 z-20 border-b border-line bg-surface/90 backdrop-blur-md">
      <div className="flex h-14 w-full items-center gap-3 px-4 sm:px-6 lg:px-8">
        <button className="icon-btn -ml-1 lg:hidden" onClick={onMenu} aria-label="Open navigation">
          <Icon name="menu" className="h-5 w-5" />
        </button>
        <span className="lg:hidden"><Logo /></span>

        <button
          onClick={onSearch}
          className="group hidden h-9 w-full max-w-[420px] cursor-pointer items-center gap-2.5 rounded-[8px] border border-line bg-raised/80 px-3 text-[13px] text-muted transition-colors duration-150 hover:border-line-strong hover:text-ink sm:flex"
        >
          <Icon name="search" />
          <span className="flex-1 text-left">Search products, jump to a page…</span>
          <Kbd>⌘K</Kbd>
        </button>

        <div className="ml-auto flex items-center gap-1 sm:gap-2">
          <button className="icon-btn sm:hidden" onClick={onSearch} aria-label="Search"><Icon name="search" className="h-[18px] w-[18px]" /></button>

          <Link to="/monitoring" className="hidden h-8 items-center rounded-[7px] px-2.5 text-muted transition-colors duration-150 hover:bg-sunken hover:text-ink md:inline-flex" title={state.title}>
            <Status tone={state.tone} live={state.live}>{state.text}</Status>
          </Link>

          <Popover
            label="Needs your attention"
            trigger={({ open, toggle, ref }) => (
              <button
                ref={ref}
                className={`icon-btn relative ${open ? "bg-sunken text-ink" : ""}`}
                aria-label={`Notifications${count ? `: ${count}` : ""}`}
                aria-expanded={open}
                onClick={() => {
                  if (!open) loadQueue();
                  toggle();
                }}
              >
                <Icon name="bell" className="h-[18px] w-[18px]" />
                {count > 0 && <span className="absolute right-1.5 top-1.5 h-2 w-2 rounded-full border-2 border-surface bg-warn-fill" aria-hidden />}
              </button>
            )}
          >
            {(close) => (
              <div>
                <div className="flex items-center justify-between border-b border-line px-4 py-3">
                  <span className="text-[13px] font-semibold">Needs your attention</span>
                  <span className="num rounded-full bg-sunken px-2 py-0.5 text-[11px] font-medium text-muted">{count}</span>
                </div>
                <div className="max-h-[360px] overflow-y-auto">
                  {queue === null && <div className="px-4 py-6 text-center text-[12px] text-muted">Loading…</div>}
                  {queue?.map((p) => (
                    <Link key={p.id} to={`/approvals?id=${p.id}`} onClick={close} className="flex items-start gap-3 border-b border-line px-4 py-3 last:border-0 hover:bg-sunken/60">
                      <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-warn-fill" aria-hidden />
                      <span className="min-w-0 flex-1">
                        <span className="line-clamp-1 text-[13px] font-medium" title={p.product_title}>{shortTitle(p.product_title)}</span>
                        <span className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[12px] text-muted">
                          <ActionBadge action={p.action} price={p.to_price_inr} />
                          <span>from <span className="mono">{formatInr(p.from_price_inr)}</span> · {timeAgo(p.created_at)}</span>
                        </span>
                      </span>
                    </Link>
                  ))}
                  {failing.map((l) => (
                    <Link key={`f${l.listing_id}`} to="/monitoring" onClick={close} className="flex items-start gap-3 border-b border-line px-4 py-3 last:border-0 hover:bg-sunken/60">
                      <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-bad-fill" aria-hidden />
                      <span className="min-w-0 flex-1">
                        <span className="line-clamp-1 text-[13px] font-medium" title={l.product_title}>{shortTitle(l.product_title)}</span>
                        <span className="mt-0.5 block text-[12px] text-muted">Listing failing {l.consecutive_failures}× · {l.last_error ?? "fetch error"}</span>
                      </span>
                    </Link>
                  ))}
                  {queue?.length === 0 && failing.length === 0 && (
                    <div className="flex flex-col items-center px-4 py-8 text-center">
                      <Icon name="done" className="h-5 w-5 text-good" />
                      <p className="mt-2 text-[13px] font-medium">You're all caught up</p>
                      <p className="mt-0.5 text-[12px] text-muted">No approvals waiting and every listing is healthy.</p>
                    </div>
                  )}
                </div>
                <Link to="/approvals" onClick={close} className="flex items-center justify-center gap-1 border-t border-line px-4 py-2.5 text-[12px] font-medium text-muted hover:bg-sunken/60 hover:text-ink">
                  Open approvals<Icon name="arrowRight" className="h-3 w-3" />
                </Link>
              </div>
            )}
          </Popover>

        </div>
      </div>
      <div className="hidden md:block">
        <MovementTape />
      </div>
    </header>
  );
}
