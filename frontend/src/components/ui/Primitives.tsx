import { useEffect, useRef, useState, type ReactNode } from "react";
import type { Marketplace, PriceAction } from "../../types";
import { ACTION_LABEL, MARKETPLACE_LABEL, formatInr, formatPct } from "../../lib/format";
import Icon, { type IconName } from "../Icon";

/** A tiny trend line of competitor prices. A fall is pressure on us (vermilion), a rise is room (jade). */
export function Sparkline({ values, className = "h-7 w-24" }: { values: number[]; className?: string }) {
  if (values.length < 2) return <div className={`${className} grid place-items-center text-[11px] text-faint`}>—</div>;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const w = 96;
  const h = 28;
  const pts = values.map((v, i) => [(i / (values.length - 1)) * w, h - 3 - ((v - min) / span) * (h - 6)]);
  const d = pts.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join("");
  const last = values[values.length - 1];
  const tone = last < values[0] ? "text-bad" : last > values[0] ? "text-good" : "text-faint";
  const [lx, ly] = pts[pts.length - 1];
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className={`${className} ${tone}`} preserveAspectRatio="none" aria-hidden>
      <path d={`${d}L${w},${h}L0,${h}Z`} fill="currentColor" opacity={0.08} />
      <path d={d} fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
      <circle cx={lx} cy={ly} r={2} fill="currentColor" />
    </svg>
  );
}

/**
 * Price change badge: arrow + percent. tone="impact" (competitor prices): a cut is pressure on us
 * (vermilion), a rise is opportunity (jade). tone="neutral": direction only, no judgement.
 */
export function Delta({ from, to, size = "sm", tone = "impact" }: { from: number | null | undefined; to: number | null | undefined; size?: "sm" | "xs"; tone?: "impact" | "neutral" }) {
  if (from == null || to == null || from === 0) return <span className="text-[12px] text-faint">—</span>;
  const pct = ((to - from) / from) * 100;
  if (Math.abs(pct) < 0.05) return <span className="text-[11px] text-faint">No change</span>;
  const down = pct < 0;
  return (
    <span
      className={`num inline-flex items-center gap-0.5 rounded-[4px] px-1 font-medium ${size === "xs" ? "text-[11px]" : "text-[12px]"} ${
        tone === "neutral" ? "bg-sunken text-muted" : down ? "bg-bad/10 text-bad" : "bg-good/10 text-good"
      }`}
    >
      <Icon name={down ? "arrowDown" : "arrowUp"} className="h-3 w-3" />
      {formatPct(Math.abs(pct), false)}
      <span className="sr-only">{down ? "down" : "up"}</span>
    </span>
  );
}

const MARK: Record<Marketplace, string> = { amazon_in: "bg-amazon", flipkart: "bg-flipkart" };

/** A platform's colour mark (the same colour as its chart line; used nowhere else). */
export function PlatformDot({ marketplace, className = "" }: { marketplace: Marketplace; className?: string }) {
  return <span className={`inline-block h-2 w-2 shrink-0 rounded-[2px] ${MARK[marketplace]} ${className}`} aria-hidden />;
}

/** Marketplace identity: colour mark + name. */
export function SourceChip({ marketplace, price, lowest, muted }: { marketplace: Marketplace; price?: number | null; lowest?: boolean; muted?: boolean }) {
  return (
    <span className={`chip ${lowest ? "border-good/40 text-ink" : ""} ${muted ? "opacity-60" : ""}`} title={lowest ? "Lowest in-stock competitor" : undefined}>
      <PlatformDot marketplace={marketplace} />
      {MARKETPLACE_LABEL[marketplace]}
      {price !== undefined && <span className="mono text-ink">{formatInr(price)}</span>}
      {lowest && <span className="sr-only"> (lowest)</span>}
    </span>
  );
}

const DIGITS = ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9"];

/**
 * A figure that is right on first paint and rolls digit by digit when it changes on refresh,
 * tinted once by direction (down = vermilion, up = jade). Reduced motion: it simply updates.
 */
export function RollingNumber<T extends number | null | undefined>({
  value,
  format = (n: T) => (n == null ? "—" : String(n)),
  className = "",
  tint = true,
}: {
  value: T;
  format?: (n: T) => string;
  className?: string;
  /** Colour the change by direction. Off for counts where "down" isn't bad news. */
  tint?: boolean;
}) {
  const text = format(value);
  const prev = useRef(value);
  const [tone, setTone] = useState("");
  useEffect(() => {
    const before = prev.current;
    prev.current = value;
    if (!tint || before == null || value == null || before === value) return;
    setTone(value < before ? "flash-down" : "flash-up");
    const t = window.setTimeout(() => setTone(""), 1200);
    return () => window.clearTimeout(t);
  }, [value, tint]);
  const chars = [...text];
  return (
    <span className={`relative inline-flex ${tone} ${className}`}>
      <span className="sr-only">{text}</span>
      <span aria-hidden className="inline-flex">
        {chars.map((ch, i) => {
          // Keyed from the right, so "999 → 1,000" keeps the ones column in place.
          const pos = chars.length - i;
          return /\d/.test(ch) ? (
            <span key={`d${pos}`} className="roll relative">
              {/* The shown digit sizes the column, so "10" never reads as "1 0". */}
              <span className="invisible">{ch}</span>
              <span className="absolute inset-x-0 top-0 items-center" style={{ transform: `translateY(-${Number(ch) * 10}%)` }}>
                {DIGITS.map((n) => <span key={n}>{n}</span>)}
              </span>
            </span>
          ) : (
            <span key={`c${pos}${ch}`} className="roll"><span><span>{ch}</span></span></span>
          );
        })}
      </span>
    </span>
  );
}

/**
 * A product photo on a white tile (marketplace shots are shot on white, in both themes).
 * Decorative: the product's name always sits next to it. Falls back to a quiet package glyph.
 */
export function ProductThumb({ src, size = 40, className = "" }: { src: string | null | undefined; size?: number; className?: string }) {
  const [failed, setFailed] = useState<string | null>(null);
  const show = !!src && failed !== src;
  return (
    <span
      className={`relative grid shrink-0 place-items-center overflow-hidden rounded-[8px] ring-1 ring-inset ring-ink/[0.08] ${show ? "bg-white" : "bg-sunken"} ${className}`}
      style={{ width: size, height: size }}
      aria-hidden
    >
      {show ? (
        <img src={src} alt="" loading="lazy" decoding="async" referrerPolicy="no-referrer" onError={() => setFailed(src ?? null)} className="h-full w-full object-contain p-[12%]" />
      ) : (
        <Icon name="package" className="h-[45%] w-[45%] text-faint" />
      )}
    </span>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`skeleton ${className}`} aria-hidden />;
}

/** Empty state: a small ledger-ring illustration, one sentence, one clear action. */
export function EmptyState({ icon, title, children, action, compact = false }: { icon: IconName; title: string; children?: ReactNode; action?: ReactNode; compact?: boolean }) {
  return (
    <div className={`flex flex-col items-center px-6 text-center ${compact ? "py-8" : "py-12"}`}>
      <span className="relative grid h-14 w-14 place-items-center" aria-hidden>
        <svg viewBox="0 0 56 56" className="absolute inset-0 h-full w-full text-line-strong">
          <circle cx="28" cy="28" r="27" fill="none" stroke="currentColor" strokeDasharray="1.5 4" strokeLinecap="round" />
          <circle cx="28" cy="28" r="19" className="fill-sunken" stroke="currentColor" strokeOpacity={0.6} />
          <path d="M9 28h4M43 28h4" stroke="currentColor" strokeLinecap="round" />
        </svg>
        <Icon name={icon} className="relative h-5 w-5 text-muted" />
      </span>
      <p className="mt-4 text-[14px] font-semibold tracking-[-0.01em]">{title}</p>
      {children && <div className="mt-1 max-w-sm text-[13px] leading-relaxed text-muted">{children}</div>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex items-start gap-3 rounded-[10px] border border-bad/30 bg-bad/[0.05] p-4 text-[13px]">
      <Icon name="alert" className="mt-0.5 text-bad" />
      <div className="flex-1">
        <p className="font-medium text-ink">Something went wrong</p>
        <p className="mt-0.5 text-muted">{message}</p>
      </div>
      {onRetry && <button className="btn-ghost btn-sm" onClick={onRetry}>Try again</button>}
    </div>
  );
}

/** Page title in the editorial serif, with an optional eyebrow and actions. */
export function PageHeader({ title, description, actions, eyebrow }: { title: ReactNode; description?: ReactNode; actions?: ReactNode; eyebrow?: ReactNode }) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-x-6 gap-y-4">
      <div className="min-w-0 max-w-3xl">
        {eyebrow && <div className="eyebrow mb-2">{eyebrow}</div>}
        <h1 className="display text-[34px] leading-[1.02] text-ink sm:text-[40px]">{title}</h1>
        {description && <p className="mt-2 max-w-2xl text-[13px] leading-relaxed text-muted">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}

/** A section heading inside a page: title, one line of context, an optional link on the right. */
export function SectionHeader({ id, title, sub, action }: { id?: string; title: ReactNode; sub?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex items-end justify-between gap-4">
      <div className="min-w-0">
        <h2 id={id} className="section-title">{title}</h2>
        {sub && <p className="mt-0.5 text-[12px] text-muted">{sub}</p>}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="num inline-grid h-5 min-w-[20px] place-items-center rounded-[4px] border border-line bg-sunken px-1 font-sans text-[11px] text-muted">{children}</kbd>;
}

/** Returns a CSS class that tints a value once whenever it changes (vermilion if it fell, jade if it rose). */
export function useFlash(value: number | null | undefined): string {
  const prev = useRef(value);
  const [cls, setCls] = useState("");
  useEffect(() => {
    const before = prev.current;
    prev.current = value;
    if (before == null || value == null || before === value) return;
    setCls(value < before ? "flash-down" : "flash-up");
    const t = window.setTimeout(() => setCls(""), 1200);
    return () => window.clearTimeout(t);
  }, [value]);
  return cls;
}

// Our own recommended actions are decisions, not alarms: neutral ink with a direction glyph.
// Only "investigate" asks for attention.
const ACTION_STYLE: Record<PriceAction, { cls: string; icon: IconName }> = {
  lower_price: { cls: "border-line-strong bg-raised text-ink", icon: "arrowDown" },
  raise_price: { cls: "border-line-strong bg-raised text-ink", icon: "arrowUp" },
  hold: { cls: "border-line bg-sunken/70 text-muted", icon: "minus" },
  investigate: { cls: "border-warn-fill/50 bg-warn-fill/[0.1] text-warn", icon: "search" },
};

/** Recommended action + target price. */
export function ActionBadge({ action, price, size = "sm" }: { action: PriceAction; price?: number | null; size?: "sm" | "lg" }) {
  const st = ACTION_STYLE[action];
  return (
    <span className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-[6px] border font-medium ${st.cls} ${size === "lg" ? "h-7 px-2.5 text-[13px]" : "h-[22px] px-1.5 text-[12px]"}`}>
      <Icon name={st.icon} className={`${size === "lg" ? "h-3.5 w-3.5" : "h-3 w-3"} ${action === "investigate" ? "" : "text-muted"}`} />
      {ACTION_LABEL[action]}
      {price != null && <span className="mono font-medium">→ {formatInr(price)}</span>}
    </span>
  );
}

export type StatusTone = "good" | "bad" | "warn" | "teal" | "info" | "muted";
const DOT: Record<StatusTone, string> = { good: "text-good-fill", bad: "text-bad-fill", warn: "text-warn-fill", teal: "text-accent", info: "text-accent", muted: "text-faint" };

/** A status: coloured dot + text (never colour alone). `live` adds a soft pulse. */
export function Status({ tone, children, live = false, className = "" }: { tone: StatusTone; children: ReactNode; live?: boolean; className?: string }) {
  return (
    <span className={`inline-flex items-center gap-1.5 whitespace-nowrap text-[12px] ${className}`}>
      <span className={`h-1.5 w-1.5 shrink-0 rounded-full bg-current ${DOT[tone]} ${live ? "live-dot" : ""}`} aria-hidden />
      {children}
    </span>
  );
}

/** Model confidence as five segments (0.92 → five lit, 0.5 → three). */
export function ConfidenceBar({ value, className = "" }: { value: number; className?: string }) {
  const lit = Math.max(1, Math.round(value * 5));
  return (
    <span className={`inline-flex items-center gap-2 ${className}`} title={`${Math.round(value * 100)}% confidence`}>
      <span className="inline-flex gap-[3px]" aria-hidden>
        {[0, 1, 2, 3, 4].map((i) => (
          <span key={i} className={`h-2.5 w-1.5 rounded-[1.5px] ${i < lit ? "bg-ink" : "bg-line-strong"}`} />
        ))}
      </span>
      <span className="num text-[12px] text-muted">{Math.round(value * 100)}%<span className="sr-only"> confidence</span></span>
    </span>
  );
}

/** Copy a value (e.g. a SKU) with a brief confirmation. */
export function CopyButton({ value, label }: { value: string; label: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      className="icon-btn h-6 w-6"
      aria-label={done ? "Copied" : `Copy ${label}`}
      title={done ? "Copied" : `Copy ${label}`}
      onClick={() => {
        navigator.clipboard?.writeText(value).then(() => {
          setDone(true);
          window.setTimeout(() => setDone(false), 1400);
        });
      }}
    >
      <Icon name={done ? "check" : "copy"} className={`h-3.5 w-3.5 ${done ? "text-good" : ""}`} />
    </button>
  );
}
