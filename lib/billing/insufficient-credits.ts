/** Tiny external store: any submission that fails with 402 raises one global 「充值积分」 notice. */
export type CreditShortfall = { required?: number; available?: number; at: number };

let current: CreditShortfall | null = null;
const listeners = new Set<() => void>();

function numberField(details: unknown, key: string): number | undefined {
  if (!details || typeof details !== "object") return undefined;
  const value = (details as Record<string, unknown>)[key];
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

export function reportCreditShortfall(details?: unknown): void {
  current = { required: numberField(details, "required_credits"), available: numberField(details, "available_credits"), at: Date.now() };
  listeners.forEach((notify) => notify());
}

export function dismissCreditShortfall(): void {
  current = null;
  listeners.forEach((notify) => notify());
}

export function subscribeCreditShortfall(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

export const creditShortfallSnapshot = () => current;
export const noCreditShortfall = () => null;
