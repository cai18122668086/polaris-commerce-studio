export const AUTH_UNAUTHORISED_EVENT = "polaris:auth:unauthorised";
export type AuthUnauthorisedReason = "api-401" | "session" | "sign-out";
const AUTH_SESSION_CHANGED_EVENT = "polaris:auth:session-changed";
let channel: BroadcastChannel | undefined;
let sessionRevoked = false;

export function isAuthSessionRevoked(): boolean { return sessionRevoked; }

function sessionChannel() {
  if (typeof window === "undefined" || typeof BroadcastChannel === "undefined") return;
  if (!channel) {
    channel = new BroadcastChannel("polaris-auth-lifecycle");
    channel.onmessage = ({ data }) => {
      if (data === "revoke") { sessionRevoked = true; window.dispatchEvent(new Event(AUTH_UNAUTHORISED_EVENT)); }
      if (data === "changed") { sessionRevoked = false; window.dispatchEvent(new Event(AUTH_SESSION_CHANGED_EVENT)); }
    };
  }
  return channel;
}

export function emitAuthUnauthorised(reason: AuthUnauthorisedReason): void {
  if (typeof window === "undefined") return;
  sessionRevoked = true;
  window.dispatchEvent(new CustomEvent(AUTH_UNAUTHORISED_EVENT, { detail: { reason } }));
  sessionChannel()?.postMessage("revoke");
}

export function onAuthUnauthorised(listener: () => void): () => void {
  if (typeof window === "undefined") return () => undefined;
  sessionChannel();
  window.addEventListener(AUTH_UNAUTHORISED_EVENT, listener);
  return () => window.removeEventListener(AUTH_UNAUTHORISED_EVENT, listener);
}

export function emitAuthSessionChanged(): void {
  if (typeof window === "undefined") return;
  sessionRevoked = false;
  window.dispatchEvent(new Event(AUTH_SESSION_CHANGED_EVENT));
  sessionChannel()?.postMessage("changed");
}

export function onAuthSessionChanged(listener: () => void): () => void {
  if (typeof window === "undefined") return () => undefined;
  sessionChannel();
  window.addEventListener(AUTH_SESSION_CHANGED_EVENT, listener);
  return () => window.removeEventListener(AUTH_SESSION_CHANGED_EVENT, listener);
}
