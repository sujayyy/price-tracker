// One typed function per backend endpoint. Components never call fetch directly.
import type {
  Activity,
  ListingPreview,
  Monitoring,
  RecheckResult,
  Decision,
  DemoPriceIn,
  DemoPriceResult,
  Health,
  HistorySeries,
  OurPriceChange,
  Product,
  ProductCreate,
  ProductUpdate,
  Proposal,
  SearchResult,
  TeamSettings,
} from "../types";

const BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "") ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

function detailMessage(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d) => (typeof d === "object" && d && "msg" in d ? String((d as { msg: unknown }).msg) : String(d)))
      .join("; ");
  }
  if (detail && typeof detail === "object" && "message" in detail) return String((detail as { message: unknown }).message);
  return "Request failed";
}

async function request(path: string, init?: RequestInit): Promise<Response> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch {
    throw new ApiError(0, `Can't reach the backend at ${BASE}. Is it running?`);
  }
  if (!res.ok) {
    let message = `${res.status} ${res.statusText}`;
    try {
      message = detailMessage((await res.json()).detail);
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, message);
  }
  return res;
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  return (await request(path, init)).json() as Promise<T>;
}

export const createProduct = (body: ProductCreate) =>
  json<Product>("/api/products", { method: "POST", body: JSON.stringify(body) });

export const listProducts = () => json<Product[]>("/api/products");

export const getProduct = (id: number) => json<Product>(`/api/products/${id}`);

export const updateProduct = (id: number, patch: ProductUpdate) =>
  json<Product>(`/api/products/${id}`, { method: "PATCH", body: JSON.stringify(patch) });

export async function deleteProduct(id: number): Promise<void> {
  await request(`/api/products/${id}`, { method: "DELETE" });
}

export const addListing = (productId: number, url: string, title?: string | null) =>
  json<Product>(`/api/products/${productId}/listings`, { method: "POST", body: JSON.stringify({ url, title }) });

export const setListingActive = (listingId: number, active: boolean) =>
  json<Product>(`/api/listings/${listingId}`, { method: "PATCH", body: JSON.stringify({ active }) });

export async function removeListing(listingId: number): Promise<void> {
  await request(`/api/listings/${listingId}`, { method: "DELETE" });
}

export const searchListings = (q: string) => json<SearchResult>(`/api/search?q=${encodeURIComponent(q)}`);

export const getHistory = (id: number, days = 30) => json<HistorySeries[]>(`/api/products/${id}/history?days=${days}`);

export const getDecisions = (id: number) => json<Decision[]>(`/api/products/${id}/decisions`);

export const getOurPriceHistory = (id: number) => json<OurPriceChange[]>(`/api/products/${id}/our-price-history`);

export const listProposals = (status?: string) =>
  json<Proposal[]>(`/api/proposals${status ? `?status=${encodeURIComponent(status)}` : ""}`);

export const getProductProposals = (id: number) => json<Proposal[]>(`/api/products/${id}/proposals`);

export const approveProposal = (id: number, body: { by: string; price_inr?: number | null; note?: string | null }) =>
  json<Proposal>(`/api/proposals/${id}/approve`, { method: "POST", body: JSON.stringify(body) });

export const rejectProposal = (id: number, body: { by: string; note?: string | null }) =>
  json<Proposal>(`/api/proposals/${id}/reject`, { method: "POST", body: JSON.stringify(body) });

export const getActivity = (days = 14, limit = 200) => json<Activity[]>(`/api/activity?days=${days}&limit=${limit}`);

export const recheckProduct = (id: number) => json<RecheckResult>(`/api/products/${id}/recheck`, { method: "POST" });

export const previewListing = (url: string) =>
  json<ListingPreview>("/api/listings/preview", { method: "POST", body: JSON.stringify({ url }) });

export const getMonitoring = () => json<Monitoring>("/api/monitoring");

export const getTeamSettings = () => json<TeamSettings>("/api/settings/team");

export const saveTeamSettings = (emails: string[], updatedBy: string) =>
  json<TeamSettings>("/api/settings/team", { method: "PUT", body: JSON.stringify({ ops_alert_emails: emails, updated_by: updatedBy }) });

export const resetTeamSettings = () => json<TeamSettings>("/api/settings/team", { method: "DELETE" });

export const sendTestEmail = (sentBy: string) =>
  json<{ sent_to: string[] }>("/api/settings/team/test-email", { method: "POST", body: JSON.stringify({ sent_by: sentBy }) });

export const getHealth = () => json<Health>("/health");

// Demo mode (internal endpoints): the secret is typed into the demo panel, never built into the bundle.
const internalAuth = (secret: string) => ({ "X-Internal-Secret": secret });

export const simulatePrice = (secret: string, body: DemoPriceIn) =>
  json<DemoPriceResult>("/internal/demo/price", {
    method: "POST",
    headers: internalAuth(secret),
    body: JSON.stringify(body),
  });

export const clearSimulatedPrices = (secret: string, productId: number) =>
  json<{ product_id: number; deleted_observations: number }>(`/internal/demo/price?product_id=${productId}`, {
    method: "DELETE",
    headers: internalAuth(secret),
  });
