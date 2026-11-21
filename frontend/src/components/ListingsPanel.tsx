import { useState } from "react";
import { toast } from "sonner";
import { ApiError, addListing, removeListing, setListingActive } from "../api/client";
import type { Marketplace, Product } from "../types";
import { MARKETPLACE_LABEL, formatInr, timeAgo } from "../lib/format";
import Icon from "./Icon";
import ListingFinder, { type PickedListing } from "./ListingFinder";
import { useConfirm } from "./ui/Confirm";
import { Delta, ProductThumb, SourceChip } from "./ui/Primitives";

/** Every competitor listing of the product: price, change, stock, which is lowest; add / pause / remove. */
export default function ListingsPanel({ product, onChanged }: { product: Product; onChanged: () => void }) {
  const [adding, setAdding] = useState(false);
  const [picked, setPicked] = useState<PickedListing[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const confirm = useConfirm();

  async function act(key: string, fn: () => Promise<unknown>, success: string) {
    setBusy(key);
    setError(null);
    try {
      await fn();
      onChanged();
      toast.success(success);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  async function addPicked() {
    const n = picked.length;
    await act(
      "add",
      async () => {
        for (const p of picked) await addListing(product.id, p.url, p.title);
        setPicked([]);
        setAdding(false);
      },
      `Added ${n} competitor listing${n === 1 ? "" : "s"}`,
    );
  }

  const multi = product.listings.filter((l) => l.active).length > 1;
  return (
    <section className="card overflow-hidden" aria-labelledby="listings-title">
      <div className="card-header">
        <div>
          <h2 id="listings-title" className="card-title">Competitor listings</h2>
          <p className="card-sub">We price against the lowest in-stock listing. Suspect readings are ignored.</p>
        </div>
        <button className="btn-ghost btn-sm" onClick={() => setAdding((a) => !a)} aria-expanded={adding}>
          <Icon name={adding ? "x" : "plus"} className="h-3.5 w-3.5" />{adding ? "Cancel" : "Add platform"}
        </button>
      </div>

      <div className="relative overflow-x-auto">
        <table className="w-full min-w-[600px] text-left text-[13px]">
          <thead className="thead">
            <tr className="border-b border-line">
              <th scope="col" className="px-4 py-2.5 font-medium sm:pl-5">Platform</th>
              <th scope="col" className="px-3 py-2 font-medium">Listing</th>
              <th scope="col" className="px-3 py-2 text-right font-medium">Price</th>
              <th scope="col" className="px-3 py-2 font-medium">Change</th>
              <th scope="col" className="px-3 py-2 font-medium">Checked</th>
              <th scope="col" className="px-3 py-2 font-medium"><span className="sr-only">Actions</span></th>
            </tr>
          </thead>
          <tbody>
            {product.listings.map((l) => (
              <tr key={l.id} className={`border-b border-line last:border-0 transition-colors duration-150 hover:bg-sunken/50 ${l.active ? "" : "opacity-55"}`}>
                <td className="whitespace-nowrap px-4 py-2.5 sm:pl-5">
                  <span className="flex items-center gap-1.5">
                    <SourceChip marketplace={l.marketplace} lowest={l.is_lowest && multi} />
                    {l.is_lowest && multi && <span className="rounded-[4px] bg-good/10 px-1.5 py-0.5 text-[11px] font-medium text-good">Lowest</span>}
                    {l.suspect && <span className="chip border-bad/30 text-bad" title="Far outside this listing's history; ignored for pricing">Suspect</span>}
                    {!l.active && <span className="chip">Paused</span>}
                  </span>
                </td>
                <td className="max-w-[22rem] px-3 py-2.5">
                  <span className="flex items-center gap-2.5">
                    <ProductThumb src={l.image_url} size={36} />
                    <a href={l.canonical_url} target="_blank" rel="noreferrer" className="line-clamp-2 text-[12px] leading-snug text-muted hover:text-ink hover:underline" title={l.title}>{l.title}</a>
                  </span>
                </td>
                <td className="mono whitespace-nowrap px-3 py-3 text-right font-medium">{l.latest?.in_stock === false ? "—" : formatInr(l.latest?.price_inr)}</td>
                <td className="whitespace-nowrap px-3 py-2.5">
                  {l.latest?.in_stock === false ? <span className="text-[12px] font-medium text-warn">Out of stock</span> : <Delta from={l.previous_price_inr} to={l.latest?.price_inr} size="xs" />}
                </td>
                <td className="whitespace-nowrap px-3 py-2.5 text-[12px] text-muted">{timeAgo(l.last_checked_at)}</td>
                <td className="whitespace-nowrap px-3 py-2.5 text-right">
                  <button
                    className="icon-btn"
                    disabled={!!busy}
                    aria-label={l.active ? `Pause ${MARKETPLACE_LABEL[l.marketplace]} listing` : `Resume ${MARKETPLACE_LABEL[l.marketplace]} listing`}
                    title={l.active ? "Pause" : "Resume"}
                    onClick={() => act(`p${l.id}`, () => setListingActive(l.id, !l.active), `${MARKETPLACE_LABEL[l.marketplace]} listing ${l.active ? "paused" : "resumed"}`)}
                  >
                    <Icon name={l.active ? "pause" : "play"} className="h-3.5 w-3.5" />
                  </button>
                  <button
                    className="icon-btn hover:text-bad"
                    disabled={!!busy}
                    aria-label={`Remove ${MARKETPLACE_LABEL[l.marketplace]} listing`}
                    title="Remove"
                    onClick={async () => {
                      const ok = await confirm({
                        title: `Remove the ${MARKETPLACE_LABEL[l.marketplace]} listing?`,
                        body: "We'll stop comparing against it. Its price history is kept, and it can be added again later.",
                        confirmLabel: "Remove listing",
                        danger: true,
                      });
                      if (ok) act(`r${l.id}`, () => removeListing(l.id), `${MARKETPLACE_LABEL[l.marketplace]} listing removed`);
                    }}
                  >
                    <Icon name="trash" className="h-3.5 w-3.5" />
                  </button>
                </td>
              </tr>
            ))}
            {product.listings.length === 0 && (
              <tr><td colSpan={6} className="px-5 py-6 text-center text-[13px] text-muted">No competitor listings yet. Add one to start monitoring.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {error && <p role="alert" className="mx-4 mb-4 rounded-[7px] border border-bad/30 bg-bad/[0.05] px-3 py-2 text-[13px] text-bad sm:mx-5">{error}</p>}

      {adding && (
        <div className="space-y-3 border-t border-line px-4 py-4 sm:px-5">
          <ListingFinder
            picked={picked}
            onChange={setPicked}
            exclude={product.listings.map((l) => l.canonical_url)}
            defaultQuery={product.title.slice(0, 300)}
            autoPick={(["amazon_in", "flipkart"] as Marketplace[]).filter((m) => !product.listings.some((l) => l.active && l.marketplace === m))}
          />
          <p className="hint">Only platforms this product doesn't have yet are pre-selected. Check the colour and variant before adding.</p>
          <button className="btn-primary" disabled={!picked.length || !!busy} onClick={addPicked}>
            {busy === "add" ? "Fetching listings…" : `Add ${picked.length || ""} listing${picked.length === 1 ? "" : "s"}`}
          </button>
        </div>
      )}
    </section>
  );
}
