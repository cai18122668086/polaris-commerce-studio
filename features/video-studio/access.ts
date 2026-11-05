"use client";

import { useEffect, useState, useSyncExternalStore } from "react";
import { usePathname } from "next/navigation";
import { apiClient } from "@/lib/api/client";
import { onAuthUnauthorised, onAuthSessionChanged, isAuthSessionRevoked } from "@/lib/auth/session-events";
import { withAuthTimeout } from "@/lib/auth/request-timeout";
import { INITIAL_VIDEO_GRANT, VideoAccessSession } from "./access-session";

// Deliberately no query/localStorage cache: a previous account's grant must
// never be available while a new route or session is being checked.
export function useVideoStudioGrantState() {
  const pathname = usePathname();
  const [session] = useState(() => new VideoAccessSession(async signal => {
    if (isAuthSessionRevoked()) return { status: "revoked" };
    const result = await withAuthTimeout(apiClient.GET("/api/v1/video-studio/access", { signal, cache: "no-store" }));
    if (result.response.status === 401) return { status: "revoked" };
    if (result.response.status === 403 || result.response.status === 404) return { status: "denied" };
    if (!result.response.ok || result.error || !isVideoStudioGrant(result.data)) throw new Error("VIDEO_ACCESS_CHECK_FAILED");
    return { status: "allowed", userId: (result.data as { user_id: string }).user_id };
  }));
  const state = useSyncExternalStore(session.subscribe, session.snapshot, session.serverSnapshot);
  useEffect(() => {
    session.setPath(pathname);
    const check = () => { if (isAuthSessionRevoked()) session.revoke(); else void session.check(); };
    const onVisible = () => { if (document.visibilityState === "visible") check(); };
    const stopUnauthorised = onAuthUnauthorised(() => session.revoke());
    const stopSessionChanged = onAuthSessionChanged(() => { session.sessionChanged(); check(); });
    window.addEventListener("focus", check);
    window.addEventListener("pageshow", check);
    document.addEventListener("visibilitychange", onVisible);
    check();
    return () => {
      session.cancel();
      stopUnauthorised(); stopSessionChanged();
      window.removeEventListener("focus", check);
      window.removeEventListener("pageshow", check);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [pathname, session]);
  return { ...(state.path === pathname ? state : INITIAL_VIDEO_GRANT), retry: () => { if (isAuthSessionRevoked()) session.revoke(); else void session.check(); } };
}

export function useVideoStudioGrant() { const result = useVideoStudioGrantState(); return result.status === "allowed" ? result.userId : undefined; }
export function useVideoStudioAccess() { return Boolean(useVideoStudioGrant()); }

export function isVideoStudioGrant(data: unknown): boolean {
  return typeof data === "object" && data !== null &&
    "allowed" in data && data.allowed === true &&
    "user_id" in data && typeof data.user_id === "string" && data.user_id.trim().length > 0;
}
