export const AUTH_UNAUTHORISED_EVENT = "polaris:auth:unauthorised";
export type AuthUnauthorisedReason = "api-401" | "session" | "sign-out";

export function emitAuthUnauthorised(reason: AuthUnauthorisedReason): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(AUTH_UNAUTHORISED_EVENT, { detail: { reason } }));
}

export function onAuthUnauthorised(listener: () => void): () => void {
  if (typeof window === "undefined") return () => undefined;
  window.addEventListener(AUTH_UNAUTHORISED_EVENT, listener);
  return () => window.removeEventListener(AUTH_UNAUTHORISED_EVENT, listener);
}
