import { motion } from "motion/react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, previewListing, searchListings } from "../api/client";
import type { IntakeCandidate, Marketplace, SearchResult } from "../types";
import { MARKETPLACE_LABEL, formatInr } from "../lib/format";
import { EASE_OUT } from "../lib/motion";
import { PlatformDot, ProductThumb } from "./ui/Primitives";
import Icon from "./Icon";

export interface PickedListing {
  url: string;
  title?: string | null;
  marketplace?: Marketplace;
  price?: number | null;
  inStock?: boolean | null;
  note?: string | null;
  image?: string | null;
}

const key = (c: IntakeCandidate) => `${c.marketplace}:${c.external_id}`;


interface Props {
  picked: PickedListing[];
  onChange: (next: PickedListing[]) => void;
  /** URLs already monitored for this product (hidden from results). */
  exclude?: string[];
  defaultQuery?: string;
  /** Only pre-tick matches on these marketplaces (e.g. the platforms a product doesn't cover yet). */
  autoPick?: Marketplace[];
}

/**
 * Find the same product on every marketplace: search by name (the intake agent searches
 * Amazon.in and Flipkart and scores each match) or paste links. Confident matches are pre-ticked.
 */
export default function ListingFinder({ picked, onChange, exclude = [], defaultQuery = "", autoPick }: Props) {
  const [query, setQuery] = useState(defaultQuery);
  const [link, setLink] = useState("");
  const [result, setResult] = useState<SearchResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pickedUrls = new Set(picked.map((p) => p.url));

  // Not a <form>: this sits inside the Add product form, and forms can't nest.
  async function search() {
    if (query.trim().length < 3) return;
    setBusy(true);
    setError(null);
    try {
      const res = await searchListings(query.trim());
      setResult(res);
      // Pre-tick the best confident match per marketplace (only where one is wanted).
      const best = new Map<Marketplace, IntakeCandidate>();
      for (const c of res.candidates) {
        const wanted = !autoPick || autoPick.includes(c.marketplace);
        if (wanted && c.match_score >= 0.8 && !best.has(c.marketplace) && !exclude.includes(c.url)) best.set(c.marketplace, c);
      }
      const add = [...best.values()].filter((c) => !pickedUrls.has(c.url));
      if (add.length) onChange([...picked, ...add.map((c) => ({ url: c.url, title: c.title, marketplace: c.marketplace, price: c.price_inr, image: c.image_url }))]);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  function toggle(c: IntakeCandidate) {
    if (pickedUrls.has(c.url)) onChange(picked.filter((p) => p.url !== c.url));
    else onChange([...picked, { url: c.url, title: c.title, marketplace: c.marketplace, price: c.price_inr, image: c.image_url }]);
  }

  const [previewing, setPreviewing] = useState(false);
  const [owner, setOwner] = useState<number | null>(null);

  // Pasted links are fetched once (not stored) so the user sees what they're adding.
  async function addLink() {
    const url = link.trim();
    if (!url || pickedUrls.has(url)) return;
    setPreviewing(true);
    setError(null);
    setOwner(null);
    try {
      const pv = await previewListing(url);
      if (pv.monitored_by_product_id) {
        setOwner(pv.monitored_by_product_id);
        setError("This listing is already monitored under another product.");
        return;
      }
      if (picked.some((p) => p.url === pv.canonical_url)) {
        setLink("");
        return;
      }
      onChange([
        ...picked,
        {
          url: pv.canonical_url,
          title: pv.title,
          marketplace: pv.marketplace,
          price: pv.price_inr,
          inStock: pv.in_stock,
          image: pv.image_url,
          note: pv.ok ? null : "Couldn't read the page right now; it will be retried on the next check.",
        },
      ]);
      setLink("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setPreviewing(false);
    }
  }

  const groups = (["amazon_in", "flipkart"] as Marketplace[]).map((m) => ({
    marketplace: m,
    items: (result?.candidates ?? []).filter((c) => c.marketplace === m && !exclude.includes(c.url)),
  }));

  return (
    <div className="space-y-4">
      <div role="search" className="flex flex-wrap gap-2">
        <div className="min-w-0 flex-[1_1_14rem]">
          <label className="label" htmlFor="find-q">Search Amazon.in and Flipkart</label>
          <input id="find-q" className="input" placeholder="e.g. boAt Airdopes 141 black" value={query} onChange={(e) => setQuery(e.target.value)} maxLength={300}
            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); search(); } }} />
        </div>
        <button type="button" onClick={search} className="btn-ghost self-end" disabled={busy || query.trim().length < 3}>
          <Icon name="search" className="h-4 w-4" />{busy ? "Searching both…" : "Find matches"}
        </button>
      </div>

      {error && (
        <p role="alert" className="text-[13px] text-bad">
          {error} {owner && <Link to={`/products/${owner}`} className="font-medium underline">Open that product</Link>}
        </p>
      )}

      {result && (
        <div className="space-y-4 rounded-[10px] border border-line bg-sunken/40 p-4">
          {result.reasoning && (
            <p className="flex gap-2 text-[12px] leading-relaxed text-muted">
              <Icon name="insight" className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>{result.ai_used ? <span className="font-medium text-ink">Match check · </span> : null}{result.reasoning}</span>
            </p>
          )}
          {groups.map((g, gi) => (
            <motion.div key={g.marketplace} initial={{ opacity: 0, transform: "translateY(6px)" }} animate={{ opacity: 1, transform: "translateY(0px)", transition: { duration: 0.24, delay: gi * 0.08, ease: EASE_OUT } }}>
              <div className="eyebrow mb-1.5 flex items-center gap-1.5"><PlatformDot marketplace={g.marketplace} />{MARKETPLACE_LABEL[g.marketplace]}</div>
              {result.errors[g.marketplace] ? (
                <p className="text-xs text-warn">Search unavailable ({result.errors[g.marketplace]}). Paste the listing link below instead.</p>
              ) : g.items.length === 0 ? (
                <p className="text-xs text-muted">No match found. You can paste a link below.</p>
              ) : (
                <ul className="divide-y divide-line/70 rounded-[8px] border border-line bg-raised px-3">
                  {g.items.map((c) => (
                    <li key={key(c)}>
                      <label className="flex cursor-pointer items-center gap-3 py-2.5">
                        <input type="checkbox" className="h-4 w-4 shrink-0 accent-[rgb(var(--accent))]" checked={pickedUrls.has(c.url)} onChange={() => toggle(c)} />
                        <ProductThumb src={c.image_url} size={48} />
                        <span className="min-w-0 flex-1">
                          <span className="line-clamp-2 text-[13px]">{c.title}</span>
                          <span className="text-xs text-muted">
                            {result.ai_used && c.match_score > 0 ? (
                              <span className={`mr-1.5 inline-flex items-center rounded-[4px] px-1 font-medium ${c.match_score >= 0.8 ? "bg-good/10 text-good" : "bg-sunken text-muted"}`}>{Math.round(c.match_score * 100)}% match</span>
                            ) : null}
                            <a href={c.url} target="_blank" rel="noreferrer" className="text-accent underline-offset-2 hover:underline" onClick={(e) => e.stopPropagation()}>view listing</a>
                          </span>
                        </span>
                        <span className="mono shrink-0 text-[13px] font-medium">{formatInr(c.price_inr)}</span>
                      </label>
                    </li>
                  ))}
                </ul>
              )}
            </motion.div>
          ))}
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        <div className="min-w-0 flex-[1_1_14rem]">
          <label className="label" htmlFor="find-link">Or paste a listing link</label>
          <input id="find-link" className="input" type="url" placeholder="https://www.amazon.in/dp/… or https://www.flipkart.com/…/p/itm…" value={link} onChange={(e) => setLink(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addLink(); } }} />
        </div>
        <button type="button" className="btn-ghost self-end" onClick={addLink} disabled={!link.trim() || previewing}>
          {previewing ? <><Icon name="refresh" className="h-3.5 w-3.5 animate-spin" />Fetching…</> : <><Icon name="plus" />Add link</>}
        </button>
      </div>

      {picked.length > 0 && (
        <div>
          <div className="label">Selected competitor listings ({picked.length})</div>
          <ul className="space-y-1.5">
            {picked.map((p) => (
              <li key={p.url} className="flex items-center gap-2.5 rounded-[8px] border border-line bg-raised px-3 py-2 text-[13px]">
                <ProductThumb src={p.image} size={36} />
                <span className="chip shrink-0">{p.marketplace && <PlatformDot marketplace={p.marketplace} />}{p.marketplace ? MARKETPLACE_LABEL[p.marketplace] : "Link"}</span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate" title={p.url}>{p.title ?? p.url}</span>
                  {(p.inStock === false || p.note) && <span className="block text-[11px] text-warn">{p.note ?? "Currently out of stock"}</span>}
                </span>
                {p.price != null && <span className="mono shrink-0 text-muted">{formatInr(p.price)}</span>}
                <button type="button" className="shrink-0 cursor-pointer rounded p-1 text-muted hover:text-bad" aria-label="Remove" onClick={() => onChange(picked.filter((x) => x.url !== p.url))}>
                  <Icon name="x" />
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
