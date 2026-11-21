import type { EventType, MarketRead, Position, PriceAction, ProposalStatus } from "../types";

const inr = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 2, minimumFractionDigits: 0 });

export const formatInr = (v: number | null | undefined) => (v == null ? "—" : inr.format(v));

export const formatPct = (v: number | null | undefined, signed = true) =>
  v == null ? "—" : `${signed && v > 0 ? "+" : ""}${v.toFixed(Math.abs(v) < 10 ? 1 : 0)}%`;

/** Compact rupees for axes and tight spots: ₹899, ₹1.2k, ₹1.9L. */
export const compactInr = (v: number) =>
  v >= 1e5 ? `₹${(v / 1e5).toFixed(v % 1e5 ? 1 : 0)}L` : v >= 1e3 ? `₹${(v / 1e3).toFixed(v % 1e3 ? 1 : 0)}k` : `₹${Math.round(v)}`;

/**
 * A short display name for a marketplace title ("boAt Airdopes 141 Gen 2, 4 Mics ENx Tech, 48 Hrs…"
 * → "boAt Airdopes 141 Gen 2"). Display only: the full title stays in a tooltip.
 */
export function shortTitle(title: string, maxWords = 7, maxChars = 44): string {
  const t = title.replace(/\s+/g, " ").trim();
  // Cut at the first clause break when what comes before it is already a name.
  const head = t.split(/\s*(?:,|\||\s[-–—]\s|\(|\[|:)\s*/)[0];
  const base = head.split(" ").length >= 2 ? head : t;
  const words = base.split(" ");
  let out = "";
  for (const w of words.slice(0, maxWords)) {
    if ((out ? out.length + 1 : 0) + w.length > maxChars) break;
    out = out ? `${out} ${w}` : w;
  }
  return out || t.slice(0, maxChars);
}

export const MARKETPLACE_LABEL = { amazon_in: "Amazon.in", flipkart: "Flipkart" } as const;
export const MARKETPLACE_SHORT = { amazon_in: "Amazon", flipkart: "Flipkart" } as const;

/** Chart colour per marketplace (our own price uses --chart-series-2). */
export const MARKETPLACE_COLOR = { amazon_in: "var(--chart-amazon)", flipkart: "var(--chart-flipkart)" } as const;

export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return "never";
  const s = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return "just now";
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 48) return `${h}h ago`;
  return `${Math.round(h / 24)}d ago`;
}

export const formatDateTime = (iso: string) =>
  new Date(iso).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });

export const EVENT_LABEL: Record<EventType | string, string> = {
  price_drop: "Competitor price drop",
  price_increase: "Competitor price increase",
  out_of_stock: "Competitor out of stock",
  back_in_stock: "Competitor back in stock",
  needs_attention: "Needs a check",
  none: "No event",
  // Decisions recorded by the earlier consumer deal-alert version.
  target_hit: "Legacy deal alert",
  real_drop: "Legacy deal alert",
  all_time_low: "Legacy deal alert",
};

export const ACTION_LABEL: Record<PriceAction, string> = {
  lower_price: "Lower price",
  raise_price: "Raise price",
  hold: "Hold price",
  investigate: "Investigate",
};

/** Our own actions are decisions, not alarms: only "investigate" asks for attention. */
export const ACTION_TONE: Record<PriceAction, string> = {
  lower_price: "text-ink",
  raise_price: "text-ink",
  hold: "text-muted",
  investigate: "text-warn",
};

export function freqLabel(hours: number): string {
  return hours === 1 ? "Hourly" : hours === 24 ? "Daily" : hours % 24 === 0 ? `Every ${hours / 24} days` : `Every ${hours}h`;
}

export function timeUntil(iso: string | null | undefined): string {
  if (!iso) return "—";
  const s = Math.round((new Date(iso).getTime() - Date.now()) / 1000);
  if (s <= 0) return "due now";
  const m = Math.round(s / 60);
  if (m < 60) return `in ${m}m`;
  const h = Math.round(m / 60);
  return h < 48 ? `in ${h}h` : `in ${Math.round(h / 24)}d`;
}

export const MARKET_READ_LABEL: Record<MarketRead, string> = {
  sustained_change: "Sustained change",
  flash_sale: "Likely flash sale",
  data_glitch: "Data glitch",
  stock_change: "Stock change",
  minor_fluctuation: "Minor fluctuation",
  unknown: "Unclear",
};

export const STATUS_LABEL: Record<ProposalStatus, string> = {
  pending: "Awaiting approval",
  approved: "Approved",
  rejected: "Rejected",
  auto_applied: "Auto-applied",
  superseded: "Superseded",
  stale: "Stale",
  failed: "Failed",
};

export function positionText(position: Position, gap: number | null, gapPct: number | null): string {
  switch (position) {
    case "we_are_pricier":
      return `${formatInr(gap)} above the lowest competitor (${formatPct(gapPct)})`;
    case "we_are_cheaper":
      return `${formatInr(gap == null ? null : -gap)} below the lowest competitor`;
    case "same_price":
      return "Matching the lowest competitor";
    case "competitor_unavailable":
      return "No competitor in stock";
    default:
      return "Our price not set";
  }
}

// Reviewer name for approvals: a per-browser convenience, not authentication.
const REVIEWER_KEY = "price-tracker.reviewer";

export function loadReviewer(): string {
  try {
    return localStorage.getItem(REVIEWER_KEY) ?? "";
  } catch {
    return "";
  }
}

export function saveReviewer(name: string) {
  try {
    localStorage.setItem(REVIEWER_KEY, name);
  } catch {
    /* storage unavailable */
  }
  window.dispatchEvent(new Event("price-tracker:reviewer-changed"));
}
