import { AnimatePresence, motion } from "motion/react";
import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { toast } from "sonner";
import { ApiError, updateProduct } from "../api/client";
import type { Product } from "../types";
import { loadReviewer } from "../lib/format";
import { EASE_OUT } from "../lib/motion";
import Icon from "./Icon";
import PricingForm, { type SettingsValue, settingsOf } from "./PricingForm";

interface Props {
  product: Product;
  onSaved: (p: Product) => void;
  onRemove: () => void;
}

/** The product's Settings tab: pricing rules as sections, a save bar only when something changed. */
export default function ProductSettings({ product, onSaved, onRemove }: Props) {
  const [value, setValue] = useState<SettingsValue>(() => settingsOf(product));
  const [email, setEmail] = useState(product.notify_email ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Follow the product when it changes elsewhere (e.g. an approval), unless the user is editing.
  const baseline = useMemo(() => JSON.stringify([settingsOf(product), product.notify_email ?? ""]), [product]);
  const current = JSON.stringify([value, email.trim()]);
  const dirty = current !== baseline;
  useEffect(() => {
    if (!dirty) {
      setValue(settingsOf(product));
      setEmail(product.notify_email ?? "");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [baseline]);

  function discard() {
    setValue(settingsOf(product));
    setEmail(product.notify_email ?? "");
    setError(null);
  }

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const patch: Record<string, unknown> = { ...value, notify_email: email.trim() || null, changed_by: loadReviewer() || "dashboard" };
      if (value.our_price_inr === product.our_price_inr) delete patch.our_price_inr; // only audit real changes
      const updated = await updateProduct(product.id, patch);
      onSaved(updated);
      toast.success("Settings saved");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-6 pb-20">
      <section className="card p-5 sm:p-6" aria-label="Pricing rules">
        <PricingForm
          variant="sections"
          value={value}
          onChange={setValue}
          competitorPrice={product.lowest_price_inr}
          alertsExtra={
            <div className="max-w-md">
              <label className="label" htmlFor="extra-email">Extra recipient</label>
              <input id="extra-email" className="input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="Optional, e.g. category-lead@company.com" />
              <p className="hint">Gets this product's alerts in addition to the ops team inbox (Settings → Alert recipients).</p>
            </div>
          }
        />
      </section>

      <section className="card border-bad/25 p-5 sm:p-6" aria-labelledby="danger-title">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h3 id="danger-title" className="text-[14px] font-semibold">Stop monitoring</h3>
            <p className="mt-1 max-w-lg text-[12px] text-muted">
              Stops checking every competitor listing of this product. Price history, recommendations and our price log are kept, and
              its listings can be added to a product again later.
            </p>
          </div>
          <button className="btn-danger" onClick={onRemove}><Icon name="trash" />Stop monitoring</button>
        </div>
      </section>

      {/* Save bar: appears only with unsaved changes (enter 200ms, exit 150ms, transform + opacity only).
          Portalled to <body>: the page's entry animation leaves a transform that would trap a fixed bar. */}
      {createPortal(
      <AnimatePresence>
        {dirty && (
          <motion.div
            role="region"
            aria-label="Unsaved changes"
            className="fixed inset-x-0 bottom-5 z-30 flex justify-center px-4 lg:pl-[248px]"
            initial={{ opacity: 0, transform: "translateY(12px)" }}
            animate={{ opacity: 1, transform: "translateY(0px)", transition: { duration: 0.2, ease: EASE_OUT } }}
            exit={{ opacity: 0, transform: "translateY(12px)", transition: { duration: 0.15, ease: EASE_OUT } }}
          >
            <div className="flex w-full max-w-xl flex-wrap items-center gap-3 rounded-[12px] border border-line bg-raised px-4 py-2.5 shadow-pop">
              <span className="h-2 w-2 shrink-0 rounded-full bg-warn-fill" aria-hidden />
              <span className="flex-1 text-[13px]">
                {error ? <span className="text-bad">{error}</span> : <><span className="font-medium">Unsaved changes</span><span className="text-muted"> to pricing rules</span></>}
              </span>
              <button className="btn-quiet btn-sm" onClick={discard} disabled={saving}>Discard</button>
              <button className="btn-primary btn-sm" onClick={save} disabled={saving}>{saving ? "Saving…" : "Save changes"}</button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>,
      document.body,
      )}
    </div>
  );
}
