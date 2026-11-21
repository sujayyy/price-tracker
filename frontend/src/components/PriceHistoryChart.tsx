import { motion } from "motion/react";
import { useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { HistorySeries, Marketplace, OurPriceChange } from "../types";
import { MARKETPLACE_COLOR, MARKETPLACE_LABEL, compactInr, formatDateTime, formatInr } from "../lib/format";
import { EASE_OUT } from "../lib/motion";

interface Props {
  series: HistorySeries[];
  ourChanges: OurPriceChange[];
  ourPrice: number | null;
  floorPrice: number | null;
  /** The selected range; the time axis always spans exactly this many days up to now. */
  days: number;
}

type Step = { t: number; v: number | null };
type Seg = { t0: number; t1: number; v: number | null };
interface Line {
  key: string;
  label: string;
  color: string;
  marketplace?: Marketplace;
  ours?: boolean;
  dashed?: boolean;
  segs: Seg[];
}

const H = 300;
const M = { top: 16, right: 84, bottom: 30, left: 52 };

/** Round a raw step up to 1, 2, 2.5 or 5 × 10^n so axis ticks land on readable prices. */
function niceStep(raw: number): number {
  const mag = 10 ** Math.floor(Math.log10(Math.max(raw, 1e-6)));
  return ([1, 2, 2.5, 5, 10].find((m) => m * mag >= raw) ?? 10) * mag;
}

/** A step series cut to [start, end] as horizontal segments (value carried forward). */
function segmentsOf(steps: Step[], start: number, end: number): Seg[] {
  const sorted = [...steps].sort((a, b) => a.t - b.t);
  const before = sorted.filter((s) => s.t <= start);
  const inRange = sorted.filter((s) => s.t > start && s.t <= end);
  const segs: Seg[] = [];
  let t0: number;
  let v: number | null;
  if (before.length) {
    t0 = start;
    v = before[before.length - 1].v;
  } else if (inRange.length) {
    const first = inRange.shift() as Step;
    t0 = first.t;
    v = first.v;
  } else {
    return [];
  }
  for (const s of inRange) {
    if (s.t > t0) segs.push({ t0, t1: s.t, v });
    t0 = s.t;
    v = s.v;
  }
  segs.push({ t0, t1: end, v });
  return segs;
}

const valueAt = (segs: Seg[], t: number): number | null | undefined => {
  let out: number | null | undefined;
  for (const s of segs) if (s.t0 <= t) out = s.v;
  return segs.length && t >= segs[0].t0 ? out : undefined;
};

function useWidth<T extends HTMLElement>(): [React.RefObject<T>, number] {
  const ref = useRef<T>(null);
  const [w, setW] = useState(0);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setW(el.clientWidth));
    ro.observe(el);
    setW(el.clientWidth);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}

export default function PriceHistoryChart({ series, ourChanges, ourPrice, floorPrice, days }: Props) {
  const uid = useId().replace(/:/g, "");
  const [showTable, setShowTable] = useState(false);
  const [box, width] = useWidth<HTMLDivElement>();
  const [hoverT, setHoverT] = useState<number | null>(null);
  // Recomputed with the data (which reloads on every range change), so "now" stays current.
  const end = useMemo(() => Date.now(), [series, ourChanges, days]); // eslint-disable-line react-hooks/exhaustive-deps
  const start = end - days * 86_400_000;

  const lines = useMemo<Line[]>(() => {
    const perMarket = new Map<Marketplace, number>();
    const comp: Line[] = series.map((s) => {
      const n = perMarket.get(s.marketplace) ?? 0;
      perMarket.set(s.marketplace, n + 1);
      const steps = s.points.map((p) => ({ t: new Date(p.fetched_at).getTime(), v: p.in_stock === false ? null : p.price_inr }));
      return {
        key: `l${s.listing_id}`,
        label: `${MARKETPLACE_LABEL[s.marketplace]}${n ? ` #${n + 1}` : ""}`,
        color: MARKETPLACE_COLOR[s.marketplace],
        marketplace: s.marketplace,
        dashed: n > 0,
        segs: segmentsOf(steps, start, end),
      };
    });
    // Our price: the last change before the range (or the first change's old price), then every change.
    const asc = [...ourChanges].sort((a, b) => a.changed_at.localeCompare(b.changed_at));
    const ourSteps: Step[] = asc.length
      ? [{ t: new Date(asc[0].changed_at).getTime() - 1, v: asc[0].old_price_inr ?? asc[0].new_price_inr }, ...asc.map((c) => ({ t: new Date(c.changed_at).getTime(), v: c.new_price_inr }))]
      : ourPrice != null ? [{ t: start - 1, v: ourPrice }] : [];
    const ours: Line = { key: "ours", label: "Our price", color: "var(--chart-ours)", ours: true, segs: segmentsOf(ourSteps, start, end) };
    return [...comp, ours].filter((l) => l.segs.some((s) => s.v != null));
  }, [series, ourChanges, ourPrice, start, end]);

  const readings = series.flatMap((s) => s.points);
  const values = lines.flatMap((l) => l.segs.map((s) => s.v)).filter((v): v is number => v != null);
  if (readings.length === 0 || values.length === 0) {
    return <p className="py-16 text-center text-[13px] text-muted">No price readings in this period yet.</p>;
  }

  // Glitch readings (far outside the typical price, e.g. ₹38 for a ₹799 product) never set the
  // scale: they would flatten every real move. They're drawn clipped to the edge and named below.
  const sorted = [...values].sort((a, b) => a - b);
  const median = sorted[Math.floor(sorted.length / 2)];
  const isOutlier = (v: number) => v < median * 0.5 || v > median * 2;
  const scaled = values.filter((v) => !isOutlier(v));

  // Lowest competitor over the range (what we price against), ignoring glitches.
  const compLines = lines.filter((l) => !l.ours);
  const compValues = compLines.flatMap((l) => l.segs.map((s) => s.v)).filter((v): v is number => v != null);
  const outliers = [...new Set(compValues.filter(isOutlier))];
  const realComp = compValues.filter((v) => !isOutlier(v));
  const low = realComp.length ? Math.min(...realComp) : null;
  const high = realComp.length ? Math.max(...realComp) : null;

  // Y: fit the data and the floor, ~10% breathing room, readable ticks.
  const basis = scaled.length ? scaled : values;
  const lo = Math.min(...basis, floorPrice ?? Infinity);
  const hi = Math.max(...basis, floorPrice ?? -Infinity);
  const pad = Math.max((hi - lo) * 0.12, hi * 0.02);
  const step = niceStep((hi - lo + 2 * pad) / 4);
  const y0 = Math.max(0, Math.floor((lo - pad) / step) * step);
  const y1 = Math.ceil((hi + pad) / step) * step;
  const yTicks = Array.from({ length: Math.round((y1 - y0) / step) + 1 }, (_, i) => y0 + i * step);

  const iw = Math.max(0, width - M.left - M.right);
  const ih = H - M.top - M.bottom;
  const x = (t: number) => M.left + ((t - start) / (end - start)) * iw;
  const y = (v: number) => Math.min(M.top + ih, Math.max(M.top, M.top + (1 - (v - y0) / (y1 - y0)) * ih));
  const nx = iw < 420 ? 3 : 6; // fewer date labels on phones so they never collide
  const xTicks = Array.from({ length: nx }, (_, i) => start + ((end - start) * i) / (nx - 1));
  // 1D: hours · 3D: day + hour · longer: day + month.
  const tickFmt = (t: number) =>
    new Date(t).toLocaleString(
      "en-IN",
      days <= 1 ? { hour: "numeric" } : days <= 3 ? { day: "numeric", month: "short", hour: "numeric" } : { day: "numeric", month: "short" },
    );

  const pathOf = (segs: Seg[]) => {
    let d = "";
    let prev: Seg | null = null;
    for (const s of segs) {
      if (s.v == null) {
        prev = null;
        continue;
      }
      d += prev && prev.v != null ? `V${y(s.v).toFixed(1)}H${x(s.t1).toFixed(1)}` : `M${x(s.t0).toFixed(1)},${y(s.v).toFixed(1)}H${x(s.t1).toFixed(1)}`;
      prev = s;
    }
    return d;
  };
  const ours = lines.find((l) => l.ours);
  const oursPath = ours ? pathOf(ours.segs) : "";
  const oursArea = ours && oursPath ? (() => {
    const pts = ours.segs.filter((s) => s.v != null);
    if (!pts.length) return "";
    return `${oursPath}V${(M.top + ih).toFixed(1)}H${x(pts[0].t0).toFixed(1)}Z`;
  })() : "";

  // Right-edge labels: each line's latest value, nudged apart so they never collide.
  const ends = lines
    .map((l) => ({ l, v: l.segs[l.segs.length - 1]?.v }))
    .filter((e): e is { l: Line; v: number } => e.v != null)
    .map((e) => ({ ...e, yy: y(e.v) }))
    .sort((a, b) => a.yy - b.yy);
  for (let i = 1; i < ends.length; i++) if (ends[i].yy - ends[i - 1].yy < 16) ends[i].yy = ends[i - 1].yy + 16;

  const firstReading = Math.min(...readings.map((p) => new Date(p.fetched_at).getTime()));
  const startsLate = firstReading - start > 86_400_000;

  // Crosshair
  const hover = hoverT != null ? lines.map((l) => ({ l, v: valueAt(l.segs, hoverT) })).filter((e) => e.v !== undefined) : [];
  const hx = hoverT != null ? x(hoverT) : 0;
  const tipLeft = hx > M.left + iw * 0.6;

  function onMove(e: React.PointerEvent<SVGRectElement>) {
    const r = (e.currentTarget as SVGRectElement).getBoundingClientRect();
    const px = Math.min(Math.max(e.clientX - r.left, 0), iw);
    setHoverT(start + (px / iw) * (end - start));
  }

  return (
    <div>
      {/* Legend + range summary */}
      <div className="mb-3 flex flex-wrap items-center justify-between gap-x-6 gap-y-2 text-[12px]">
        <ul className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
          {lines.map((l) => (
            <li key={l.key} className="flex items-center gap-1.5 text-muted">
              {l.ours ? <span className="h-[3px] w-4 rounded-full bg-ink" /> : <span className="h-[2px] w-4 rounded-full" style={{ background: l.color, opacity: l.dashed ? 0.7 : 1 }} />}
              <span className={l.ours ? "font-medium text-ink" : ""}>{l.label}</span>
            </li>
          ))}
          {floorPrice != null && (
            <li className="flex items-center gap-1.5 text-muted">
              <span className="w-4 border-t-[1.5px] border-dashed border-muted" />Floor
            </li>
          )}
        </ul>
        {low != null && high != null && (
          <p className="text-muted">
            Lowest competitor this period: <span className="mono text-ink">{formatInr(low)}</span>
            {high !== low && <> · high <span className="mono text-ink">{formatInr(high)}</span></>}
          </p>
        )}
      </div>

      <div ref={box} className="relative w-full select-none" style={{ height: H }}>
        {width > 0 && (
          <svg width={width} height={H} role="img" aria-label={`Competitor prices on ${series.length} listing(s) and our price over the last ${days} days, between ${formatInr(lo)} and ${formatInr(hi)}.`}>
            <defs>
              <linearGradient id={`${uid}-ours`} x1="0" x2="0" y1="0" y2="1">
                <stop offset="0%" stopColor="var(--chart-ours)" stopOpacity={0.12} />
                <stop offset="100%" stopColor="var(--chart-ours)" stopOpacity={0} />
              </linearGradient>
              <pattern id={`${uid}-hatch`} width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
                <line x1="0" y1="0" x2="0" y2="6" stroke="var(--chart-floor)" strokeWidth={1} strokeOpacity={0.22} />
              </pattern>
              <clipPath id={`${uid}-reveal`}>
                <motion.rect x={M.left} y={0} height={H} initial={{ width: 0 }} animate={{ width: iw + 2, transition: { duration: 0.8, ease: EASE_OUT } }} />
              </clipPath>
            </defs>

            {/* Grid + y axis */}
            {yTicks.map((t) => (
              <g key={t}>
                <line x1={M.left} x2={M.left + iw} y1={y(t)} y2={y(t)} stroke="var(--chart-grid)" />
                <text x={M.left - 10} y={y(t)} dy="0.32em" textAnchor="end" className="fill-[var(--chart-axis)] text-[11px] tabular-nums">{compactInr(t)}</text>
              </g>
            ))}
            {xTicks.map((t, i) => (
              <text key={t} x={x(t)} y={H - 8} textAnchor={i === 0 ? "start" : i === xTicks.length - 1 ? "end" : "middle"} className="fill-[var(--chart-axis)] text-[11px]">
                {i === xTicks.length - 1 ? "Now" : tickFmt(t)}
              </text>
            ))}

            {/* Floor: never price below this line */}
            {floorPrice != null && floorPrice >= y0 && (
              <g>
                <rect x={M.left} y={y(floorPrice)} width={iw} height={M.top + ih - y(floorPrice)} fill={`url(#${uid}-hatch)`} />
                <line x1={M.left} x2={M.left + iw} y1={y(floorPrice)} y2={y(floorPrice)} stroke="var(--chart-floor)" strokeWidth={1.25} strokeDasharray="5 4" />
                <text x={M.left + 8} y={y(floorPrice) + 14} className="fill-[var(--chart-floor)] text-[11px] font-medium">Floor {formatInr(floorPrice)}</text>
              </g>
            )}

            <g clipPath={`url(#${uid}-reveal)`}>
              {oursArea && <path d={oursArea} fill={`url(#${uid}-ours)`} />}
              {lines.filter((l) => !l.ours).map((l) => (
                <path key={l.key} d={pathOf(l.segs)} fill="none" stroke={l.color} strokeWidth={1.75} strokeDasharray={l.dashed ? "3 3" : undefined} strokeLinejoin="round" strokeLinecap="round" />
              ))}
              {ours && <path d={oursPath} fill="none" stroke="var(--chart-ours)" strokeWidth={2.5} strokeLinejoin="round" strokeLinecap="round" />}
            </g>

            {/* Latest values, on the right edge */}
            {ends.map((e) => (
              <g key={e.l.key}>
                <circle cx={M.left + iw} cy={y(e.v)} r={3.5} fill={e.l.color} stroke="rgb(var(--raised))" strokeWidth={2} />
                <text x={M.left + iw + 10} y={e.yy} dy="0.32em" className={`text-[11px] ${e.l.ours ? "fill-ink font-semibold" : "fill-[var(--chart-axis)]"}`} style={{ fontFamily: "'Geist Mono', ui-monospace, monospace" }}>
                  {formatInr(e.v)}
                </text>
              </g>
            ))}

            {/* Crosshair */}
            {hoverT != null && (
              <g pointerEvents="none">
                <line x1={hx} x2={hx} y1={M.top} y2={M.top + ih} stroke="var(--chart-axis)" strokeWidth={1} strokeDasharray="2 3" />
                {hover.map((h) => h.v != null && <circle key={h.l.key} cx={hx} cy={y(h.v)} r={4} fill={h.l.color} stroke="rgb(var(--raised))" strokeWidth={2} />)}
              </g>
            )}
            <rect x={M.left} y={M.top} width={iw} height={ih} fill="transparent" onPointerMove={onMove} onPointerLeave={() => setHoverT(null)} />
          </svg>
        )}

        {hoverT != null && (
          <div
            className="pointer-events-none absolute top-2 z-10 w-52 rounded-[10px] border border-line bg-raised px-3 py-2.5 text-[12px] shadow-pop"
            style={tipLeft ? { left: hx - 216 } : { left: hx + 16 }}
          >
            <div className="mb-1.5 text-muted">{formatDateTime(new Date(hoverT).toISOString())}</div>
            {hover.map((h) => (
              <div key={h.l.key} className="mt-1 flex items-center gap-2">
                <span className="h-2 w-2 rounded-full" style={{ background: h.l.color }} />
                <span className={h.l.ours ? "font-medium text-ink" : "text-muted"}>{h.l.label}</span>
                <span className="mono ml-auto font-medium text-ink">{h.v == null ? "out of stock" : formatInr(h.v)}</span>
              </div>
            ))}
            {floorPrice != null && <div className="mt-1.5 border-t border-line pt-1.5 text-muted">Floor <span className="mono float-right text-ink">{formatInr(floorPrice)}</span></div>}
          </div>
        )}
      </div>

      <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
        {outliers.length > 0 ? (
          <p className="text-[12px] text-muted">
            {outliers.length === 1 ? "1 glitch reading" : `${outliers.length} glitch readings`} ({outliers.map((v) => formatInr(v)).join(", ")}) kept off the scale; see every reading for details.
          </p>
        ) : startsLate ? (
          <p className="text-[12px] text-muted">Monitoring started {formatDateTime(new Date(firstReading).toISOString())}: no readings before that.</p>
        ) : <span />}
        <button className="cursor-pointer text-[12px] text-muted underline-offset-2 hover:text-ink hover:underline" onClick={() => setShowTable((s) => !s)} aria-expanded={showTable}>
          {showTable ? "Hide" : "Show"} every reading
        </button>
      </div>
      {showTable && (
        <div className="mt-2 max-h-56 overflow-auto rounded-[8px] border border-line">
          <table className="w-full text-left text-[12px]">
            <thead className="thead sticky top-0 bg-sunken">
              <tr><th className="px-3 py-2 font-medium">Checked</th><th className="px-3 py-2 font-medium">Platform</th><th className="px-3 py-2 text-right font-medium">Price</th><th className="px-3 py-2 font-medium">Stock</th></tr>
            </thead>
            <tbody>
              {series
                .flatMap((s) => s.points.map((p) => ({ ...p, marketplace: s.marketplace, id: s.listing_id })))
                .sort((a, b) => b.fetched_at.localeCompare(a.fetched_at))
                .map((p, i) => (
                  <tr key={`${p.id}-${p.fetched_at}-${i}`} className="border-t border-line">
                    <td className="px-3 py-1.5">{formatDateTime(p.fetched_at)}</td>
                    <td className="px-3 py-1.5">{MARKETPLACE_LABEL[p.marketplace]}</td>
                    <td className="mono px-3 py-1.5 text-right">{formatInr(p.price_inr)}</td>
                    <td className="px-3 py-1.5">{p.in_stock == null ? "—" : p.in_stock ? "In stock" : "Out of stock"}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
