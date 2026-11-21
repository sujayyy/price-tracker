import type { Position } from "../types";
import { formatInr, formatPct, positionText } from "../lib/format";
import Icon, { type IconName } from "./Icon";

// Amber = needs attention (we're pricier), green = competitive, gray = neutral facts.
const TONE: Record<Position, { cls: string; icon: IconName }> = {
  we_are_pricier: { cls: "border-warn-fill/50 bg-warn-fill/[0.12] text-warn", icon: "arrowUp" },
  we_are_cheaper: { cls: "border-good/30 bg-good/[0.08] text-good", icon: "arrowDown" },
  same_price: { cls: "border-line bg-sunken text-muted", icon: "minus" },
  competitor_unavailable: { cls: "border-line bg-sunken text-muted", icon: "package" },
  our_price_not_set: { cls: "border-dashed border-line-strong text-muted", icon: "pencil" },
};

function compactText(position: Position, gap: number | null, gapPct: number | null): string {
  switch (position) {
    case "we_are_pricier":
      return `+${formatInr(gap)} · ${formatPct(gapPct, false)}`;
    case "we_are_cheaper":
      return `−${formatInr(gap == null ? null : -gap)}`;
    case "same_price":
      return "Matched";
    case "competitor_unavailable":
      return "No stock";
    default:
      return "Not priced";
  }
}

/** Where our price stands against the lowest competitor. Text carries the meaning; colour reinforces it. */
export default function PositionBadge({ position, gap, gapPct, compact = false }: { position: Position; gap: number | null; gapPct: number | null; compact?: boolean }) {
  const tone = TONE[position];
  return (
    <span
      className={`inline-flex h-[22px] items-center gap-1 whitespace-nowrap rounded-[5px] border px-1.5 text-[12px] font-medium ${tone.cls}`}
      title={positionText(position, gap, gapPct)}
    >
      <Icon name={tone.icon} className="h-3 w-3" />
      <span className={compact ? "mono" : ""}>{compact ? compactText(position, gap, gapPct) : positionText(position, gap, gapPct)}</span>
      {compact && <span className="sr-only">{positionText(position, gap, gapPct)}</span>}
    </span>
  );
}
