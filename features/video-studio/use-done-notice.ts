"use client";

import { useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api/client";
import { unwrapApiResponse } from "@/lib/api/request";
import { busyPhase, justFinished, noticeTitle, type BusyPhase, type NoticeBatch } from "./done-notice";

const route = "/api/v1/video-studio/workspaces/{workspace_id}/work-batches" as const;

/** 最近 5 批（含条目）。首页「进行中的批次」与完成提醒共用同一份数据；页面在后台时也继续刷新。 */
export function useRecentBatches(workspaceId: string) {
  return useQuery({
    queryKey: ["video-studio", "work-batches", workspaceId, "recent"],
    staleTime: 15000,
    queryFn: async ({ signal }) => unwrapApiResponse(await apiClient.GET(route, {
      params: { path: { workspace_id: workspaceId }, query: { limit: 5 } },
      signal: AbortSignal.any([signal, AbortSignal.timeout(12000)]),
    })),
    refetchInterval: query => ((query.state.data ?? []) as NoticeBatch[]).some(batch => busyPhase(batch)) ? 20000 : 60000,
    refetchIntervalInBackground: true,
  });
}

/**
 * C10「完成提醒」轻量版：页面在后台时有一批口播或剪辑跑完，标签标题改成「（口播已完成）…」；
 * 回到页面就恢复原标题。只在后台时提醒（在前台时页面本身会刷新出结果）。
 */
export function useDoneNotice(workspaceId: string) {
  const batches = useRecentBatches(workspaceId);
  const phases = useRef<Record<string, BusyPhase> | null>(null);
  const original = useRef<string | null>(null);

  useEffect(() => {
    if (!batches.data) return;
    const result = justFinished(phases.current ?? {}, batches.data as NoticeBatch[]);
    const first = phases.current === null;
    phases.current = result.phases;
    if (first || !result.finished.length || typeof document === "undefined" || !document.hidden) return;
    original.current ??= document.title;
    document.title = noticeTitle(result.finished, document.title);
  }, [batches.data]);

  useEffect(() => {
    const restore = () => {
      if (document.hidden || original.current === null) return;
      document.title = original.current;
      original.current = null;
    };
    document.addEventListener("visibilitychange", restore);
    return () => { document.removeEventListener("visibilitychange", restore); restore(); };
  }, []);
  return batches;
}
