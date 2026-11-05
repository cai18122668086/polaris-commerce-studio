"use client";

import { useEffect, useMemo, useSyncExternalStore } from "react";
import { projectApi } from "./projects";
import { VideoProjectSession } from "./project-session";

export function useProjectSession(userId: string, workspaceId: string) {
  const session = useMemo(() => new VideoProjectSession(projectApi(workspaceId), {
    getItem: key => window.localStorage.getItem(key),
    setItem: (key, value) => window.localStorage.setItem(key, value),
    removeItem: key => window.localStorage.removeItem(key),
  }, `polaris-video-recovery-v1:${userId}:${workspaceId}`), [userId, workspaceId]);
  const state = useSyncExternalStore(session.subscribe, session.getSnapshot, session.getSnapshot);
  useEffect(() => {
    if (!state.projectId || state.status === "loading") return;
    const url = new URL(window.location.href);
    if (state.revision) url.searchParams.set("project", state.projectId);
    else url.searchParams.delete("project");
    window.history.replaceState(window.history.state, "", url);
  }, [state.projectId, state.revision, state.status]);
  useEffect(() => {
    const id = new URL(window.location.href).searchParams.get("project") || undefined;
    void session.initialize(id);
    return () => session.dispose();
  }, [session]);
  useEffect(() => {
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (["dirty", "saving", "error", "conflict"].includes(session.state.status)) event.preventDefault();
    };
    window.addEventListener("beforeunload", beforeUnload);
    return () => window.removeEventListener("beforeunload", beforeUnload);
  }, [session]);
  return { session, ...state };
}
