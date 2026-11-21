import { useEffect, useState, type ReactNode } from "react";
import type { AlertRules, PricingRules } from "../types";
import { formatInr } from "../lib/format";

export type SettingsValue = AlertRules & PricingRules;

export const DEFAULT_SETTINGS: SettingsValue = {
  our_sku: null,
  our_price_inr: null,
  floor_price_inr: null,
  max_change_pct: 10,
  undercut_by_inr: 0,
  auto_apply: false,
  auto_apply_max_pct: 3,
  min_change_pct: null,
  alert_on_stock_change: true,
  check_every_hours: 6,
};

export function settingsOf(v: SettingsValue): SettingsValue {
  const out = {} as Record<string, unknown>;
  for (const k of Object.keys(DEFAULT_SETTINGS)) out[k] = (v as unknown as Record<string, unknown>)[k];
  return out as unknown as SettingsValue;
}

const FREQUENCIES = [
  { hours: 1, label: "Every hour" },
  { hours: 3, label: "Every 3 hours" },
  { hours: 6, label: "Every 6 hours" },
  { hours: 12, label: "Twice a day" },
  { hours: 24, label: "Daily" },
];

function parseNum(v: string, positive: boolean): number | null {
  if (v.trim() === "") return null;
  const n = Number(v);
  return Number.isFinite(n) && (positive ? n > 0 : n >= 0) ? n : null;
}

interface NumInputProps {
  id: string;
  value: number | null;
  onChange: (v: number | null) => void;
  /** Required fields keep their last valid value while the box is being edited. */
  required?: boolean;
  /** Zero is not allowed (e.g. a percentage threshold). */
  positive?: boolean;
  placeholder?: string;
  invalid?: boolean;
}

/** A number box that keeps what you type (so it can be cleared and retyped) and reports parsed values. */
function NumInput({ id, value, onChange, required = false, positive = true, placeholder, invalid }: NumInputProps) {
  const [text, setText] = useState(value == null ? "" : String(value));
  // Follow outside changes (save, reset) without fighting the user's typing ("2." is still 2).
  useEffect(() => {
    if (parseNum(text, positive) !== value) setText(value == null ? "" : String(value));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);
  return (
    <input
      id={id}
      className={`input tabular-nums ${invalid ? "border-bad" : ""}`}
      inputMode="decimal"
      placeholder={placeholder}
      aria-invalid={invalid}
      value={text}
      onChange={(e) => {
        setText(e.target.value);
        const n = parseNum(e.target.value, positive);
        if (n !== null || !required) onChange(n);
      }}
      onBlur={() => {
        if (required && parseNum(text, positive) === null) setText(value == null ? "" : String(value));
      }}
    />
  );
}

/** On/off control with the WAI-ARIA switch role. */
export function Switch({ checked, onChange, label, id }: { checked: boolean; onChange: (v: boolean) => void; label: string; id?: string }) {
  return (
    <button
      id={id}
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full transition-colors duration-150 ${checked ? "bg-brand" : "bg-line-strong"}`}
    >
      <span
        className="inline-block h-4 w-4 rounded-full bg-raised shadow-xs"
        style={{ transform: `translateX(${checked ? 18 : 2}px)`, transition: "transform 160ms cubic-bezier(0.23, 1, 0.32, 1)" }}
      />
    </button>
  );
}

/** A setting that is either on or off: text on the left, switch on the right. */
function SwitchRow({ id, title, description, checked, onChange }: { id: string; title: string; description: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <div className="flex items-start justify-between gap-4">
      <label htmlFor={id} className="cursor-pointer">
        <span className="block text-[13px] font-medium">{title}</span>
        <span className="mt-0.5 block text-[12px] text-muted">{description}</span>
      </label>
      <Switch id={id} checked={checked} onChange={onChange} label={title} />
    </div>
  );
}

interface SectionProps {
  title: string;
  description: string;
  variant: "stacked" | "sections";
  children: ReactNode;
}

/** "sections": settings-page layout (explanation left, fields right). "stacked": compact, for forms. */
function Section({ title, description, variant, children }: SectionProps) {
  if (variant === "stacked") {
    return (
      <fieldset className="space-y-4">
        <legend className="eyebrow mb-2">{title}</legend>
        {children}
      </fieldset>
    );
  }
  return (
    <fieldset className="grid gap-x-10 gap-y-4 border-t border-line py-6 first:border-t-0 first:pt-0 last:pb-0 lg:grid-cols-[minmax(200px,260px)_1fr]">
      <div>
        <legend className="text-[14px] font-semibold tracking-[-0.01em]">{title}</legend>
        <p className="mt-1 text-[12px] leading-relaxed text-muted">{description}</p>
      </div>
      <div className="space-y-4">{children}</div>
    </fieldset>
  );
}

interface Props {
  value: SettingsValue;
  onChange: (next: SettingsValue) => void;
  competitorPrice?: number | null;
  variant?: "stacked" | "sections";
  /** Extra fields rendered at the end of the Alerts section (e.g. an extra recipient). */
  alertsExtra?: ReactNode;
  /** Render only these sections (default: all). */
  only?: ("product" | "repricing" | "alerts")[];
}

/** Our side of the listing (price + limits) and when the ops team is alerted. */
export default function PricingForm({ value, onChange, competitorPrice, variant = "stacked", alertsExtra, only }: Props) {
  const show = (k: "product" | "repricing" | "alerts") => !only || only.includes(k);
  const set = <K extends keyof SettingsValue>(key: K, v: SettingsValue[K]) => onChange({ ...value, [key]: v });
  const floorError = value.floor_price_inr != null && value.our_price_inr != null && value.floor_price_inr > value.our_price_inr;
  const autoError = value.auto_apply && value.auto_apply_max_pct > value.max_change_pct;

  return (
    <div className={variant === "stacked" ? "space-y-6" : ""}>
      {show("product") && <Section variant={variant} title="Our product" description="What we sell and the lowest price we'll ever accept. Leave our price empty to only watch competitors.">
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="sm:col-span-2 lg:col-span-1">
            <label className="label" htmlFor="sku">SKU</label>
            <input id="sku" className="input num" placeholder="e.g. EARBUDS-BLK-01" value={value.our_sku ?? ""} onChange={(e) => set("our_sku", e.target.value.trim() || null)} />
          </div>
          <div className="hidden lg:block" />
          <div>
            <label className="label" htmlFor="our">Our price (₹)</label>
            <NumInput id="our" placeholder="Not set" value={value.our_price_inr} onChange={(v) => set("our_price_inr", v)} />
            <p className="hint">{competitorPrice != null ? <>Lowest competitor is at <span className="num">{formatInr(competitorPrice)}</span>.</> : "Changes are recorded in the price log."}</p>
          </div>
          <div>
            <label className="label" htmlFor="floor">Floor price (₹)</label>
            <NumInput id="floor" placeholder="Cost + minimum margin" invalid={floorError} value={value.floor_price_inr} onChange={(v) => set("floor_price_inr", v)} />
            <p className={`hint ${floorError ? "text-bad" : ""}`}>{floorError ? "Must not be above our price." : "Never go below this, whoever approves."}</p>
          </div>
        </div>
      </Section>}

      {show("repricing") && <Section variant={variant} title="Repricing" description="How far a single change may move our price, and which changes can skip approval.">
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="label" htmlFor="undercut">Undercut by (₹)</label>
            <NumInput id="undercut" required positive={false} value={value.undercut_by_inr} onChange={(v) => set("undercut_by_inr", v ?? 0)} />
            <p className="hint">0 matches the lowest competitor.</p>
          </div>
          <div>
            <label className="label" htmlFor="maxmove">Max move per change (%)</label>
            <NumInput id="maxmove" required value={value.max_change_pct} onChange={(v) => v != null && set("max_change_pct", v)} />
            <p className="hint">Caps any single change, up or down.</p>
          </div>
        </div>
        <div className="rounded-[10px] border border-line p-4">
          <SwitchRow
            id="autoapply"
            title="Auto-apply small, confident changes"
            description="Everything else waits for approval. Never at the floor, never on a likely flash sale."
            checked={value.auto_apply}
            onChange={(v) => set("auto_apply", v)}
          />
          {value.auto_apply && (
            <div className="mt-3.5 max-w-[16rem] border-t border-line pt-3.5">
              <label className="label" htmlFor="automax">Auto-apply up to (%)</label>
              <NumInput id="automax" required invalid={autoError} value={value.auto_apply_max_pct} onChange={(v) => v != null && set("auto_apply_max_pct", v)} />
              <p className={`hint ${autoError ? "text-bad" : ""}`}>{autoError ? "Can't be more than the max move." : "Largest change applied without approval."}</p>
            </div>
          )}
        </div>
      </Section>}

      {show("alerts") && <Section variant={variant} title="Alerts" description="When the ops team is emailed about a competitor change, and how often competitors are checked.">
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="label" htmlFor="minchange">Alert on moves of at least (%)</label>
            <NumInput id="minchange" placeholder="Any change" value={value.min_change_pct} onChange={(v) => set("min_change_pct", v)} />
            <p className="hint">Up or down, vs the previous reading.</p>
          </div>
          <div>
            <label className="label" htmlFor="freq">Check competitors</label>
            <select id="freq" className="input" value={value.check_every_hours} onChange={(e) => set("check_every_hours", Number(e.target.value))}>
              {FREQUENCIES.map((f) => <option key={f.hours} value={f.hours}>{f.label}</option>)}
            </select>
          </div>
        </div>
        <SwitchRow
          id="stockalerts"
          title="Stock changes"
          description="Alert when a competitor goes out of stock or comes back."
          checked={value.alert_on_stock_change}
          onChange={(v) => set("alert_on_stock_change", v)}
        />
        {alertsExtra}
      </Section>}
    </div>
  );
}
