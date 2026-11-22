/**
 * A confirmed paid submission whose response was lost (network drop, closed tab).
 * The page looks it up by its idempotency key instead of asking the user to
 * "query the original submission"; nothing here ever re-sends a paid request.
 */
export type PendingSubmission<T> = { body: T; savedAt: number };

/** A request still missing after this long never reached the server (the POST itself times out at 15 s). */
export const ABSENT_AFTER_MS = 60_000;

export function encodePending<T>(body: T, now: number): string {
  return JSON.stringify({ body, savedAt: now } satisfies PendingSubmission<T>);
}

/** Accepts the current format and the older bare-body format (treated as long saved). */
export function decodePending<T>(raw: string | null, isBody: (value: unknown) => value is T): PendingSubmission<T> | undefined {
  if (!raw) return undefined;
  let value: unknown;
  try { value = JSON.parse(raw); } catch { return undefined; }
  if (value && typeof value === "object" && "body" in value && isBody((value as { body: unknown }).body)) {
    const savedAt = Number((value as { savedAt?: unknown }).savedAt);
    return { body: (value as { body: T }).body, savedAt: Number.isFinite(savedAt) ? savedAt : 0 };
  }
  return isBody(value) ? { body: value, savedAt: 0 } : undefined;
}

export type PendingOutcome = "found" | "absent" | "wait";

/** found: show the existing job. absent: nothing was received or charged. wait: still possibly in flight. */
export function pendingOutcome(lookup: { received: boolean }, savedAt: number, now: number = Date.now()): PendingOutcome {
  if (lookup.received) return "found";
  return now - savedAt >= ABSENT_AFTER_MS ? "absent" : "wait";
}

export const PENDING_COPY = {
  checking: "正在确认上次提交，不会重复扣费。",
  found: "上次提交已在处理，没有重复扣费。",
  absent: "上次提交没有到达服务器，没有扣费，可以重新提交。",
} as const;
