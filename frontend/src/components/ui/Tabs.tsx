import { motion } from "motion/react";
import { useId, useRef } from "react";
import { SPRING } from "../../lib/motion";

export interface TabItem<T extends string> {
  id: T;
  label: string;
  count?: number;
}

/** Underline tabs with roving focus (←/→), per the WAI-ARIA tabs pattern. The underline slides. */
export default function Tabs<T extends string>({ items, value, onChange, label }: { items: TabItem<T>[]; value: T; onChange: (id: T) => void; label: string }) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const uid = useId();
  function onKey(e: React.KeyboardEvent, i: number) {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    const next = (i + (e.key === "ArrowRight" ? 1 : -1) + items.length) % items.length;
    refs.current[next]?.focus();
    onChange(items[next].id);
  }
  return (
    <div role="tablist" aria-label={label} className="flex gap-6 overflow-x-auto border-b border-line">
      {items.map((t, i) => {
        const active = t.id === value;
        return (
          <button
            key={t.id}
            ref={(el) => { refs.current[i] = el; }}
            role="tab"
            id={`${uid}-${t.id}`}
            aria-selected={active}
            tabIndex={active ? 0 : -1}
            onClick={() => onChange(t.id)}
            onKeyDown={(e) => onKey(e, i)}
            className={`relative flex h-10 cursor-pointer items-center gap-1.5 whitespace-nowrap text-[13px] font-medium transition-colors duration-150 ${
              active ? "text-ink" : "text-muted hover:text-ink"
            }`}
          >
            {t.label}
            {t.count != null && t.count > 0 && (
              <span className={`num rounded-[4px] px-1 text-[11px] ${active ? "bg-brand text-on-brand" : "bg-sunken text-muted"}`}>{t.count}</span>
            )}
            {active && <motion.span layoutId={`${uid}-underline`} transition={SPRING} className="absolute inset-x-0 -bottom-px h-[2px] rounded-full bg-brand" />}
          </button>
        );
      })}
    </div>
  );
}

/** Compact segmented control (chart range, filters). The thumb slides to the chosen option. */
export function Segmented<T extends string | number>({ options, value, onChange, label }: { options: { value: T; label: string }[]; value: T; onChange: (v: T) => void; label: string }) {
  const uid = useId();
  return (
    <div role="group" aria-label={label} className="inline-flex rounded-[8px] border border-line bg-sunken p-0.5">
      {options.map((o) => {
        const on = o.value === value;
        return (
          <button
            key={String(o.value)}
            aria-pressed={on}
            onClick={() => onChange(o.value)}
            className={`relative h-7 shrink-0 cursor-pointer whitespace-nowrap rounded-[6px] px-2.5 text-[12px] font-medium transition-colors duration-150 ${
              on ? "text-ink" : "text-muted hover:text-ink"
            }`}
          >
            {on && <motion.span layoutId={`${uid}-thumb`} transition={SPRING} className="absolute inset-0 rounded-[6px] bg-raised shadow-xs ring-1 ring-line" />}
            <span className="relative">{o.label}</span>
          </button>
        );
      })}
    </div>
  );
}
