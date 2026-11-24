/* 后台接口返回空对象、缺字段或 null 时，统一补成“空数据”，让页面显示空状态而不是崩溃。
   只补缺失的部分，接口给出的真实值原样保留。 */

export type ListPagination = { total: number; limit: number; offset: number; has_more: boolean };

type Loose = Record<string, unknown>;

function record(value: unknown): Loose {
  return typeof value === "object" && value !== null && !Array.isArray(value) ? (value as Loose) : {};
}

function count(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

export function arrayOf<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

export function normalizeList<T, Extra extends object = object>(payload: unknown): { items: T[]; pagination: ListPagination } & Extra {
  const source = record(payload);
  const items = arrayOf<T>(source.items);
  const page = record(source.pagination);
  return {
    ...source,
    items,
    pagination: {
      total: count(page.total ?? items.length),
      limit: count(page.limit ?? items.length),
      offset: count(page.offset),
      has_more: page.has_more === true,
    },
  } as { items: T[]; pagination: ListPagination } & Extra;
}

function counts<K extends string>(value: unknown, keys: readonly K[]) {
  const source = record(value);
  return Object.fromEntries(keys.map((key) => [key, count(source[key])])) as Record<K, number>;
}

export function normalizeAdminOverview<T>(payload: unknown): T {
  const source = record(payload);
  return {
    ...source,
    users: counts(source.users, ["total", "active", "disabled", "recent_signups"] as const),
    workspaces: counts(source.workspaces, ["total", "active"] as const),
    usage: counts(source.usage, ["jobs_total", "jobs_running", "jobs_failed", "jobs_completed", "crawl_tasks_total", "crawl_tasks_running", "crawl_tasks_failed", "crawl_tasks_succeeded"] as const),
    crawler_sessions: record(source.crawler_sessions),
    generated_at: typeof source.generated_at === "string" ? source.generated_at : null,
  } as T;
}

export function normalizeLogDetail<T>(payload: unknown): T {
  const source = record(payload);
  const lists = ["events", "items", "assets", "input_assets", "output_assets", "intermediate_assets"] as const;
  return { ...source, ...Object.fromEntries(lists.map((key) => [key, arrayOf(source[key])])) } as T;
}

export function normalizeCommerceOverview<T>(payload: unknown): T {
  return { ...record(payload), ...counts(payload, ["customers", "paid_fen", "refunded_fen", "pending_refunds", "open_cases"] as const) } as T;
}

export function normalizeCommerceAccess<T>(payload: unknown): T {
  const source = record(payload);
  return { ...source, permissions: arrayOf<string>(source.permissions), global_enforcement_enabled: source.global_enforcement_enabled === true, refund_mode: typeof source.refund_mode === "string" ? source.refund_mode : "" } as T;
}

export function canManage(payload: unknown) {
  return record(payload).can_manage === true;
}
