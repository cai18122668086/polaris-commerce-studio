import { parseResponse, requestHeaders, type AdminPagination } from "./admin";

export type Customer = { workspace_id: string; workspace_name: string; user_id: string; email: string | null; display_name: string | null; status: string; balance_credits: number; reserved_credits: number; available_credits: number; consumed_credits: number; paid_fen: number; last_used_at: string | null; last_login_at: string | null; note: string; enforcement_enabled: boolean };
export type Refund = { id: string; purchase_id: string; workspace_id: string; email?: string | null; amount_fen: number; credits: number; status: "processing" | "completed" | "rejected"; reason: string; receipt_reference: string | null; result_note: string | null; actor_user_id: string; confirmed_by_user_id: string | null; hold_ledger_entry_id: number; result_ledger_entry_id: number | null; created_at: string; confirmed_at: string | null; gateway_result: string };
export type Order = { id: string; workspace_id: string; email: string | null; package_name: string; amount_fen: number; credits: number; status: string; gateway_trade_no: string | null; ledger_entry_id: number | null; created_at: string; paid_at: string | null; product_kind: string; bonus_credits: number | null; months: number; issued_credits: number; remaining_credits: number; held_credits: number; used_or_expired_credits: number; refunded_fen: number; processing_refund_fen: number; refundable_fen: number; refundable_credits: number; refunds: Refund[] };
export type Ledger = { id: number; workspace_id: string; job_id: string | null; entry_type: string; description: string | null; delta_balance_credits: number; delta_reserved_credits: number; balance_after_credits: number; reserved_after_credits: number; created_at: string; purchase_id: string | null; refund_id: string | null; adjustment_id: string | null; actor_user_id: string | null };
export type GenerationJob = { id: string; workspace_id: string; email: string | null; type: string; status: string; display_name: string | null; expected_item_count: number; succeeded_item_count: number; failed_item_count: number; estimated_credits: number | null; actual_credits: number | null; error_code: string | null; error_message: string | null; created_at: string; finished_at: string | null };
export type SupportCase = { id: string; workspace_id: string; job_id: string | null; issue: string; resolution: string; status: "open" | "in_progress" | "resolved"; actor_user_id: string; created_at: string; updated_at: string };
export type Audit = { id: number; workspace_id: string; actor_user_id: string; action: string; resource_id: string; details: Record<string, unknown>; occurred_at: string };
export type CommerceData = { customers: Customer[]; orders: Order[]; ledger: Ledger[]; jobs: GenerationJob[]; cases: SupportCase[]; refunds: Refund[]; audit: Audit[] };
export type CommerceTab = keyof CommerceData;
export type CommerceOverview = { customers: number; paid_fen: number; refunded_fen: number; pending_refunds: number; open_cases: number };
export type CommerceAccess = { permissions: string[]; global_enforcement_enabled: boolean; refund_mode: string };
export type CommerceList<T> = { items: T[]; pagination: AdminPagination };

export async function commerceRequest<T>(path: string, options: { method?: string; body?: unknown; requestKey?: string; signal?: AbortSignal } = {}): Promise<T> {
  const headers = requestHeaders();
  if (options.body !== undefined) headers.set("Content-Type", "application/json");
  if (options.requestKey) headers.set("Idempotency-Key", options.requestKey);
  return parseResponse<T>(await fetch(`/api/v1/admin/commerce${path}`, {
    credentials: "include", cache: "no-store", method: options.method ?? "GET", headers,
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined, signal: options.signal,
  }));
}

export function listCommerce<K extends CommerceTab>(tab: K, params: Record<string, string | number | undefined>, signal?: AbortSignal) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) if (value !== undefined && value !== "") query.set(key, String(value));
  return commerceRequest<CommerceList<CommerceData[K][number]>>(`/${tab}?${query}`, { signal });
}

export function parseYuan(value: string): number | null {
  if (!/^(0|[1-9]\d{0,7})(\.\d{1,2})?$/.test(value.trim())) return null;
  const [yuan, cents = ""] = value.trim().split(".");
  return Number(yuan) * 100 + Number(cents.padEnd(2, "0"));
}
