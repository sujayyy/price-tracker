// Mirrors backend/app/schemas and backend/app/ai/schemas.py.

export type Marketplace = "amazon_in" | "flipkart";

export interface AlertRules {
  min_change_pct: number | null;
  alert_on_stock_change: boolean;
  check_every_hours: number;
}

export interface PricingRules {
  our_sku: string | null;
  our_price_inr: number | null;
  floor_price_inr: number | null;
  max_change_pct: number;
  undercut_by_inr: number;
  auto_apply: boolean;
  auto_apply_max_pct: number;
}

export interface PriceObservation {
  fetched_at: string;
  price_inr: number | null;
  mrp_inr: number | null;
  in_stock: boolean | null;
  seller: string | null;
  ok: boolean;
  error: string | null;
}

export type Position = "we_are_cheaper" | "we_are_pricier" | "same_price" | "competitor_unavailable" | "our_price_not_set";

export interface ProposalBrief {
  id: number;
  action: PriceAction;
  from_price_inr: number;
  to_price_inr: number;
  change_pct: number;
  created_at: string;
}

/** One competitor listing of our product, on one marketplace. */
export interface Listing {
  id: number;
  marketplace: Marketplace;
  external_id: string;
  canonical_url: string;
  title: string;
  active: boolean;
  /** The listing's product photo (marketplace CDN thumbnail). */
  image_url: string | null;
  latest: PriceObservation | null;
  previous_price_inr: number | null;
  last_checked_at: string | null;
  is_lowest: boolean;
  suspect: boolean;
}

/** One of OUR products, compared against all of its competitor listings. */
export interface Product extends AlertRules, PricingRules {
  id: number;
  title: string;
  notify_email: string | null;
  active: boolean;
  created_at: string;
  /** One photo for our product, taken from a competitor listing. */
  image_url: string | null;
  listings: Listing[];
  lowest_price_inr: number | null;
  lowest_marketplace: Marketplace | null;
  lowest_listing_id: number | null;
  competitor_in_stock: boolean | null;
  position: Position;
  gap_inr: number | null;
  gap_pct: number | null;
  pending_proposal: ProposalBrief | null;
  last_checked_at: string | null;
  sparkline: number[];
}

/** One AI decision in the cross-product activity feed. */
export interface Activity {
  id: number;
  product_id: number;
  product_title: string;
  our_sku: string | null;
  listing_id: number;
  marketplace: Marketplace | null;
  trigger_type: string;
  created_at: string;
  alerted: boolean;
  action: PriceAction;
  recommended_price_inr: number | null;
  competitor_price_inr: number | null;
  our_price_inr: number | null;
  reasoning: string;
  urgency: "high" | "medium" | "low" | null;
  market_read: MarketRead | null;
  confidence: number | null;
  proposal_id: number | null;
  proposal_status: ProposalStatus | null;
  resolved_by: string | null;
}

export interface HistoryPoint {
  fetched_at: string;
  price_inr: number | null;
  mrp_inr: number | null;
  in_stock: boolean | null;
}

export interface HistorySeries {
  listing_id: number;
  marketplace: Marketplace;
  title: string;
  points: HistoryPoint[];
}

export type EventType = "price_drop" | "price_increase" | "out_of_stock" | "back_in_stock" | "needs_attention" | "none";
export type PriceAction = "lower_price" | "raise_price" | "hold" | "investigate";
export type MarketRead = "sustained_change" | "flash_sale" | "data_glitch" | "stock_change" | "minor_fluctuation" | "unknown";

export interface RepricingDecision {
  product_id: number;
  event: EventType;
  competitor_price_inr: number | null;
  our_price_inr: number | null;
  action: PriceAction;
  recommended_price_inr: number | null;
  market_read: MarketRead;
  urgency: "high" | "medium" | "low";
  reasoning: string;
  confidence: number;
  data_issues: string[];
}

export interface Decision {
  id: number;
  product_id: number;
  listing_id: number;
  marketplace: Marketplace | null;
  trigger_type: string;
  created_at: string;
  alerted: boolean;
  decision: RepricingDecision;
}

export type ProposalStatus = "pending" | "approved" | "rejected" | "auto_applied" | "superseded" | "stale" | "failed";

export interface Proposal {
  id: number;
  product_id: number;
  product_title: string;
  product_image_url: string | null;
  our_sku: string | null;
  listing_id: number | null;
  marketplace: Marketplace | null;
  status: ProposalStatus;
  action: PriceAction;
  competitor_price_inr: number | null;
  from_price_inr: number;
  to_price_inr: number;
  final_price_inr: number | null;
  change_pct: number;
  limited_by: "floor" | "max_change" | null;
  floor_price_inr: number | null;
  created_at: string;
  resolved_at: string | null;
  resolved_by: string | null;
  resolution_note: string | null;
  decision: RepricingDecision | null;
  guardrails: GuardrailCheck[];
  latest_competitor_price_inr: number | null;
  latest_checked_at: string | null;
  competitor_changed: boolean;
  our_price_changed: boolean;
}

export interface GuardrailCheck {
  key: string;
  label: string;
  passed: boolean | null;
  detail: string | null;
}

export interface RecheckResult {
  checked: number;
  errors: number;
  changed: boolean;
  proposal_replaced: boolean;
  checked_at: string;
  product: Product;
}

export interface ListingPreview {
  marketplace: Marketplace;
  external_id: string;
  canonical_url: string;
  title: string | null;
  price_inr: number | null;
  in_stock: boolean | null;
  image_url: string | null;
  ok: boolean;
  error: string | null;
  monitored_by_product_id: number | null;
}

export interface RunRow {
  id: number;
  started_at: string;
  finished_at: string | null;
  items_checked: number;
  agent_invocations: number;
  errors: number;
  notes: string | null;
}

export interface ListingHealth {
  listing_id: number;
  product_id: number;
  product_title: string;
  marketplace: Marketplace;
  status: "ok" | "failing" | "paused" | "not_checked";
  last_checked_at: string | null;
  next_due_at: string | null;
  check_every_hours: number;
  price_inr: number | null;
  in_stock: boolean | null;
  consecutive_failures: number;
  last_error: string | null;
}

export interface Monitoring {
  last_run_at: string | null;
  runs_24h: number;
  errors_24h: number;
  ai_runs_today: number;
  ai_daily_limit: number;
  runs: RunRow[];
  listings: ListingHealth[];
}

export interface OurPriceChange {
  id: number;
  old_price_inr: number | null;
  new_price_inr: number;
  changed_at: string;
  source: "manual" | "approved" | "auto";
  actor: string;
  proposal_id: number | null;
  note: string | null;
}

export interface IntakeCandidate {
  marketplace: Marketplace;
  external_id: string;
  title: string;
  price_inr: number | null;
  url: string;
  match_score: number;
  image_url?: string | null;
}

export interface SearchResult {
  query: string;
  candidates: IntakeCandidate[];
  reasoning: string;
  ai_used: boolean;
  errors: Record<string, string>;
}

export interface ProductCreate {
  title?: string | null;
  listings: { url: string; title?: string | null }[];
  rules: AlertRules;
  pricing: PricingRules;
  notify_email?: string | null;
}

export type ProductUpdate = Partial<AlertRules & PricingRules> & {
  title?: string;
  notify_email?: string | null;
  active?: boolean;
  changed_by?: string;
};

export interface Health {
  status: string;
  demo_endpoints: boolean;
  ai?: { runs_today: number; daily_limit: number };
}

// Demo mode: POST /internal/demo/price simulates the competitor's price, then the normal pipeline runs.
export interface DemoPriceIn {
  listing_id: number;
  price_inr?: number | null;
  in_stock?: boolean;
}

export interface RunTrigger {
  product_id: number;
  listing_id: number;
  trigger: string;
  listings_changed: number[];
  decision_id: number;
  action: PriceAction;
  recommended_price_inr: number | null;
  workflow_status: string;
  proposal_id: number | null;
  proposal_status: ProposalStatus | null;
  emailed: boolean;
  reason: "ok" | "email_not_configured" | "email_failed" | "no_recipients" | string;
}

export interface RunResult {
  run_id: number;
  items_checked: number;
  agent_invocations: number;
  errors: number;
  alerts_sent: number;
  triggers: RunTrigger[];
}

export interface DemoPriceResult {
  listing_id: number;
  product_id: number;
  marketplace: Marketplace;
  simulated_price_inr: number | null;
  previous_price_inr: number | null;
  our_price_before_inr: number | null;
  our_price_after_inr: number | null;
  floor_price_inr: number | null;
  lowest_price_inr: number | null;
  lowest_marketplace: Marketplace | null;
  observation: {
    id: number;
    fetched_at: string;
    price_inr: number | null;
    mrp_inr: number | null;
    in_stock: boolean | null;
    ok: boolean;
    source: string;
  };
  run: RunResult;
  decision: RepricingDecision | null;
}

export interface TeamSettings {
  ops_alert_emails: string[];
  source: "dashboard" | "environment";
  updated_at: string | null;
  updated_by: string | null;
  email_configured: boolean;
  sender: string | null;
}
