import { authFailureReason, type AuthDiagnostic, type AuthPhase } from "./diagnostic-payload";

let requestIds: string[] = [];
let failedStatus: number | undefined;

export function beginAuthDiagnostics() {
  requestIds = [];
  failedStatus = undefined;
}

export function rememberAuthRequest(id: string) {
  if (/^[a-zA-Z0-9_-]{1,80}$/.test(id) && !requestIds.includes(id)) requestIds = [...requestIds, id].slice(-6);
}

export async function observeAuthResponse({ fetchResponse: response }: { fetchResponse: Response }) {
  const id = response.headers.get("X-Request-Id");
  if (id) rememberAuthRequest(id);
  failedStatus = response.status >= 400 ? response.status : undefined;
}

export function createAuthDiagnostic(error: unknown, phase: AuthPhase, started: number): AuthDiagnostic {
  const response = error instanceof Response ? error : error && typeof error === "object" && "response" in error ? error.response : undefined;
  if (response instanceof Response) {
    const id = response.headers.get("X-Request-Id");
    if (id) rememberAuthRequest(id);
  }
  const status = response instanceof Response && response.status >= 400 ? response.status : failedStatus;
  const path = window.location.pathname;
  return {
    id: `auth_${crypto.randomUUID()}`,
    occurred_at: new Date().toISOString(),
    phase,
    reason: authFailureReason(error, navigator.onLine, status),
    path: /^\/[a-zA-Z0-9_/-]{0,120}$/.test(path) ? path : "/",
    elapsed_ms: Math.min(120_000, Math.max(0, Math.round(performance.now() - started))),
    http_status: status ?? null,
    request_ids: [...requestIds],
  };
}

export function reportAuthDiagnostic(diagnostic: AuthDiagnostic) {
  // Independent of the unavailable auth API; the frontend records this ID.
  void fetch("/diagnostics/auth", {
    method: "POST",
    credentials: "omit",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(diagnostic),
    keepalive: true,
  }).catch(() => undefined);
}
