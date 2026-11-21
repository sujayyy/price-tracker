import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { ApiError, createProduct } from "../api/client";
import Icon from "../components/Icon";
import ListingFinder, { type PickedListing } from "../components/ListingFinder";
import PricingForm, { DEFAULT_SETTINGS, type SettingsValue } from "../components/PricingForm";
import { PageHeader, ProductThumb, SourceChip } from "../components/ui/Primitives";
import { MARKETPLACE_LABEL, formatInr, freqLabel } from "../lib/format";
import { EASE_OUT } from "../lib/motion";

const STEPS = [
  { id: "listings", label: "Competitor listings" },
  { id: "product", label: "Our product" },
  { id: "rules", label: "Repricing & alerts" },
  { id: "review", label: "Review" },
] as const;

function Stepper({ step, onJump }: { step: number; onJump: (i: number) => void }) {
  return (
    <ol className="grid grid-cols-2 gap-2 sm:grid-cols-4" aria-label="Steps">
      {STEPS.map((s, i) => {
        const state = i < step ? "done" : i === step ? "current" : "todo";
        return (
          <li key={s.id}>
            <button
              type="button"
              disabled={state === "todo"}
              onClick={() => onJump(i)}
              aria-current={state === "current" ? "step" : undefined}
              className={`flex w-full flex-col items-start gap-2 border-t-2 pt-2.5 text-left text-[13px] transition-colors duration-150 ${
                state === "current" ? "border-brand text-ink" : state === "done" ? "cursor-pointer border-good-fill text-ink hover:text-muted" : "cursor-default border-line-strong text-muted"
              }`}
            >
              <span className="eyebrow flex items-center gap-1.5 text-[10px]">
                {state === "done" ? <Icon name="check" className="h-3 w-3 text-good" /> : null}Step {i + 1}
              </span>
              <span className={state === "current" ? "font-semibold" : "font-medium"}>{s.label}</span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-1 border-b border-line py-2.5 last:border-0 sm:grid-cols-[180px_1fr]">
      <dt className="text-[12px] text-muted">{label}</dt>
      <dd className="text-[13px]">{children}</dd>
    </div>
  );
}

export default function AddProductPage() {
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const [title, setTitle] = useState("");
  const [picked, setPicked] = useState<PickedListing[]>([]);
  const [email, setEmail] = useState("");
  const [settings, setSettings] = useState<SettingsValue>(DEFAULT_SETTINGS);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const known = picked.map((p) => p.price).filter((v): v is number => v != null);
  const lowestPicked = known.length ? Math.min(...known) : null;
  const floorError = settings.floor_price_inr != null && settings.our_price_inr != null && settings.floor_price_inr > settings.our_price_inr;
  const autoError = settings.auto_apply && settings.auto_apply_max_pct > settings.max_change_pct;
  const platforms = new Set(picked.map((p) => p.marketplace).filter(Boolean)).size;

  function next() {
    setError(null);
    if (step === 0 && !picked.length) return setError("Add at least one competitor listing: search above, or paste a link.");
    if (step === 1 && floorError) return setError("The floor price can't be above our price.");
    if (step === 2 && autoError) return setError("The auto-apply limit can't be more than the max move.");
    setStep((s) => Math.min(STEPS.length - 1, s + 1));
  }

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const product = await createProduct({
        title: title.trim() || null,
        listings: picked.map((p) => ({ url: p.url, title: p.title ?? null })),
        rules: { min_change_pct: settings.min_change_pct, alert_on_stock_change: settings.alert_on_stock_change, check_every_hours: settings.check_every_hours },
        pricing: {
          our_sku: settings.our_sku,
          our_price_inr: settings.our_price_inr,
          floor_price_inr: settings.floor_price_inr,
          max_change_pct: settings.max_change_pct,
          undercut_by_inr: settings.undercut_by_inr,
          auto_apply: settings.auto_apply,
          auto_apply_max_pct: settings.auto_apply_max_pct,
        },
        notify_email: email.trim() || null,
      });
      toast.success("Monitoring started", { description: `${product.title} · ${product.listings.length} listing${product.listings.length === 1 ? "" : "s"}` });
      navigate(`/products/${product.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-7">
      <div>
        <Link to="/products" className="inline-flex items-center gap-1 text-[13px] text-muted hover:text-ink"><Icon name="back" className="h-3.5 w-3.5" />Products</Link>
        <div className="mt-4">
          <PageHeader title="Add a product" description="One of our products, matched to the same product on Amazon.in and Flipkart. We always price against the lowest in-stock competitor." />
        </div>
      </div>

      <Stepper step={step} onJump={(i) => i < step && setStep(i)} />

      <section className="card overflow-hidden">
        <AnimatePresence mode="wait" initial={false}>
          <motion.div
            key={step}
            className="p-5 sm:p-6"
            initial={{ opacity: 0, transform: "translateX(8px)" }}
            animate={{ opacity: 1, transform: "translateX(0px)", transition: { duration: 0.18, ease: EASE_OUT } }}
            exit={{ opacity: 0, transition: { duration: 0.1 } }}
          >
            {step === 0 && (
              <div className="space-y-4">
                <div>
                  <h2 className="section-title">Find it on Amazon.in and Flipkart</h2>
                  <p className="mt-1 text-[13px] text-muted">Search by name (confident matches on each platform are pre-selected) or paste listing links. Check the colour and variant.</p>
                </div>
                <ListingFinder picked={picked} onChange={setPicked} />
                {picked.length > 0 && platforms < 2 && <p className="hint">Tip: add the same product from the other platform too, so we always price against the cheapest.</p>}
              </div>
            )}
            {step === 1 && (
              <div className="space-y-5">
                <div>
                  <h2 className="section-title">Our product</h2>
                  <p className="mt-1 text-[13px] text-muted">What we sell it for, and the lowest price we'll accept. Leave our price empty to only watch competitors.</p>
                </div>
                <div className="max-w-md">
                  <label className="label" htmlFor="title">Product name</label>
                  <input id="title" className="input" placeholder={picked[0]?.title ?? "Defaults to the first listing's title"} value={title} onChange={(e) => setTitle(e.target.value)} maxLength={500} />
                </div>
                <PricingForm only={["product"]} value={settings} onChange={setSettings} competitorPrice={lowestPicked} />
              </div>
            )}
            {step === 2 && (
              <div className="space-y-5">
                <div>
                  <h2 className="section-title">Repricing and alerts</h2>
                  <p className="mt-1 text-[13px] text-muted">How far one change may move our price, which changes can skip approval, and how often competitors are checked.</p>
                </div>
                <PricingForm
                  only={["repricing", "alerts"]}
                  value={settings}
                  onChange={setSettings}
                  alertsExtra={
                    <div className="max-w-md">
                      <label className="label" htmlFor="email">Extra recipient</label>
                      <input id="email" className="input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="Optional; the ops team inbox always gets alerts" />
                    </div>
                  }
                />
              </div>
            )}
            {step === 3 && (
              <div className="space-y-4">
                <div>
                  <h2 className="section-title">Review</h2>
                  <p className="mt-1 text-[13px] text-muted">Each listing is fetched once when you start. After that, it's checked {freqLabel(settings.check_every_hours).toLowerCase()}.</p>
                </div>
                <dl>
                  <Row label="Product">{title.trim() || picked[0]?.title || "—"}{settings.our_sku && <span className="code ml-2 text-muted">{settings.our_sku}</span>}</Row>
                  <Row label="Competitor listings">
                    <ul className="space-y-1.5">
                      {picked.map((p) => (
                        <li key={p.url} className="flex flex-wrap items-center gap-2.5">
                          <ProductThumb src={p.image} size={32} />
                          {p.marketplace ? <SourceChip marketplace={p.marketplace} /> : <span className="chip">Link</span>}
                          <span className="min-w-0 flex-1 truncate">{p.title ?? p.url}</span>
                          {p.price != null && <span className="num text-muted">{formatInr(p.price)}</span>}
                        </li>
                      ))}
                    </ul>
                  </Row>
                  <Row label="Our price and floor"><span className="mono">{formatInr(settings.our_price_inr)}</span> · floor <span className="mono">{formatInr(settings.floor_price_inr)}</span></Row>
                  <Row label="Repricing">
                    {settings.undercut_by_inr ? <>Undercut the lowest competitor by <span className="num">{formatInr(settings.undercut_by_inr)}</span></> : "Match the lowest competitor"} · max move {settings.max_change_pct}%
                    {" · "}{settings.auto_apply ? `auto-apply changes up to ${settings.auto_apply_max_pct}%` : "every change needs approval"}
                  </Row>
                  <Row label="Alerts">
                    {settings.min_change_pct ? `Moves of ${settings.min_change_pct}% or more` : "Every price move"}{settings.alert_on_stock_change ? ", plus stock changes" : ""} · {freqLabel(settings.check_every_hours)}
                    {email.trim() && <> · also to {email.trim()}</>}
                  </Row>
                  <Row label="Platforms">{[...new Set(picked.map((p) => p.marketplace).filter(Boolean))].map((m) => MARKETPLACE_LABEL[m as keyof typeof MARKETPLACE_LABEL]).join(", ") || "—"}</Row>
                </dl>
              </div>
            )}
          </motion.div>
        </AnimatePresence>

        <div className="flex flex-wrap items-center gap-3 border-t border-line bg-sunken/40 px-5 py-3 sm:px-6">
          {error && <p role="alert" className="w-full text-[13px] text-bad">{error}</p>}
          {step > 0 && <button type="button" className="btn-ghost" onClick={() => { setError(null); setStep((s) => s - 1); }} disabled={busy}>Back</button>}
          <span className="text-[12px] text-muted">Step {step + 1} of {STEPS.length}</span>
          {step < STEPS.length - 1 ? (
            <button type="button" className="btn-primary ml-auto" onClick={next}>Continue<Icon name="arrowRight" className="h-3.5 w-3.5" /></button>
          ) : (
            <button type="button" className="btn-primary btn-lg ml-auto" onClick={submit} disabled={busy}>
              {busy ? <><Icon name="refresh" className="h-3.5 w-3.5 animate-spin" />Fetching listings…</> : <><Icon name="check" />Start monitoring</>}
            </button>
          )}
        </div>
      </section>
    </div>
  );
}
