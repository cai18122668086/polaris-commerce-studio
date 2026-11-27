"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api/client";
import { unwrapApiResponse } from "@/lib/api/request";
import type { components } from "@/lib/api/generated/openapi";
import type { Platform, WorkItemLike } from "./works";

export type CoverCandidate = components["schemas"]["CoverCandidateResponse"];
export type WorkItem = components["schemas"]["WorkItemResponse"] & WorkItemLike;

const root = "/api/v1/video-studio/workspaces/{workspace_id}" as const;
const timeout = (signal?: AbortSignal) => signal ? AbortSignal.any([signal, AbortSignal.timeout(15000)]) : AbortSignal.timeout(15000);
const BUSY = new Set(["queued", "running"]);

export const finishingKeys = {
  items: (workspaceId: string, scope: string) => ["video-studio", "work-items", workspaceId, scope] as const,
  covers: (workspaceId: string, itemId: string) => ["video-studio", "cover-candidates", workspaceId, itemId] as const,
  video: (workspaceId: string, taskId: string) => ["video-studio", "work-video", workspaceId, taskId] as const,
};

/** 一批（?batch=）或一条（?item=）作品条目；都没有时取「待成片」的全部。 */
export function useFinishingItems(workspaceId: string, scope: { batch?: string | null; item?: string | null }) {
  const key = scope.batch ? `batch:${scope.batch}` : scope.item ? `item:${scope.item}` : "finishing";
  return useQuery({
    queryKey: finishingKeys.items(workspaceId, key),
    staleTime: 5000,
    queryFn: async ({ signal }) => {
      if (scope.item && !scope.batch) {
        const one = unwrapApiResponse(await apiClient.GET(`${root}/work-items/{item_id}`, {
          params: { path: { workspace_id: workspaceId, item_id: scope.item } }, signal: timeout(signal),
        }));
        return [one] as WorkItem[];
      }
      return unwrapApiResponse(await apiClient.GET(`${root}/work-items`, {
        params: { path: { workspace_id: workspaceId }, query: scope.batch ? { batch_id: scope.batch, limit: 50 } : { stage: ["finishing"], limit: 50 } },
        signal: timeout(signal),
      })) as WorkItem[];
    },
    refetchInterval: query => (query.state.data ?? []).some(item => item.stage !== "done" && item.stage !== "finishing") ? 15000 : false,
  });
}

/** 我的作品：所有作品条目（进行中 + 已完成）。 */
export function useAllWorkItems(workspaceId: string) {
  return useQuery({
    queryKey: finishingKeys.items(workspaceId, "all"),
    staleTime: 5000,
    queryFn: async ({ signal }) => unwrapApiResponse(await apiClient.GET(`${root}/work-items`, {
      params: { path: { workspace_id: workspaceId }, query: { limit: 200 } }, signal: timeout(signal),
    })) as WorkItem[],
    refetchInterval: query => (query.state.data ?? []).some(item => (item.stage === "talking" || item.stage === "editing") && item.status !== "failed") ? 20000 : false,
  });
}

/** 一条作品的封面候选，新的在前；有生成中的就每 3 秒刷新。 */
export function useCoverCandidates(workspaceId: string, itemId: string | null) {
  return useQuery({
    queryKey: finishingKeys.covers(workspaceId, itemId ?? ""),
    enabled: Boolean(itemId),
    staleTime: 2000,
    queryFn: async ({ signal }) => unwrapApiResponse(await apiClient.GET(`${root}/cover-candidates`, {
      params: { path: { workspace_id: workspaceId }, query: { work_item_id: itemId!, limit: 40 } }, signal: timeout(signal),
    })) as CoverCandidate[],
    refetchInterval: query => (query.state.data ?? []).some(cover => BUSY.has(cover.status)) ? 3000 : false,
  });
}

/** 这条作品能播的视频：剪辑成片优先，其次口播结果。 */
export function useWorkVideo(workspaceId: string, item: Pick<WorkItemLike, "editing_task_id" | "generation_task_id" | "source_video_ref"> | null) {
  const editing = item?.editing_task_id ?? null;
  const talking = item?.generation_task_id ?? (item?.source_video_ref?.kind === "talking" ? item.source_video_ref.id : null);
  return useQuery({
    queryKey: finishingKeys.video(workspaceId, editing ?? talking ?? ""),
    enabled: Boolean(editing || talking),
    staleTime: 60000,
    queryFn: async ({ signal }) => {
      if (editing) {
        const task = unwrapApiResponse(await apiClient.GET(`${root}/editing-tasks/{task_id}`, {
          params: { path: { workspace_id: workspaceId, task_id: editing } }, signal: timeout(signal),
        })) as { status: string; artifacts?: { role: string; url: string }[] };
        const final = task.artifacts?.find(artifact => artifact.role === "final");
        if (final) return final.url;
      }
      return talking ? `/api/v1/video-studio/workspaces/${workspaceId}/generation-tasks/${talking}/video` : null;
    },
  });
}

export type GenerateBody = { work_item_id: string; cover_text: string; highlight?: string | null; platform: Platform; round?: number };

export function useCoverActions(workspaceId: string) {
  const client = useQueryClient();
  const refresh = (itemId: string) => client.invalidateQueries({ queryKey: finishingKeys.covers(workspaceId, itemId) });
  const generate = useMutation({
    mutationFn: async (body: GenerateBody & { request_id: string }) => unwrapApiResponse(await apiClient.POST(`${root}/cover-candidates`, {
      params: { path: { workspace_id: workspaceId } }, body: { ...body, round: body.round ?? 0 }, signal: timeout(),
    })) as CoverCandidate[],
    onSettled: (_data, _error, body) => refresh(body.work_item_id),
  });
  const retext = useMutation({
    mutationFn: async (input: { candidateId: string; itemId: string; cover_text: string; highlight?: string | null; request_id: string }) => unwrapApiResponse(await apiClient.POST(`${root}/cover-candidates/{candidate_id}/retext`, {
      params: { path: { workspace_id: workspaceId, candidate_id: input.candidateId } },
      body: { request_id: input.request_id, cover_text: input.cover_text, highlight: input.highlight ?? null }, signal: timeout(),
    })) as CoverCandidate,
    onSettled: (_data, _error, input) => refresh(input.itemId),
  });
  const finish = useMutation({
    mutationFn: async (input: { itemId: string; expected_version: number; cover_candidate_id: string; publish_title: string; publish_body: string }) => unwrapApiResponse(await apiClient.POST(`${root}/work-items/{item_id}/finish`, {
      params: { path: { workspace_id: workspaceId, item_id: input.itemId } },
      body: { expected_version: input.expected_version, cover_candidate_id: input.cover_candidate_id, publish_title: input.publish_title, publish_body: input.publish_body },
      signal: timeout(),
    })) as WorkItem,
    onSuccess: () => client.invalidateQueries({ queryKey: ["video-studio", "work-items", workspaceId] }),
  });
  return { generate, retext, finish };
}

export function coverImageUrl(workspaceId: string, coverId: string, view: "cover" | "thumb" = "cover", download = false): string {
  const query = [view !== "cover" ? `view=${view}` : "", download ? "download=true" : ""].filter(Boolean).join("&");
  return `/api/v1/video-studio/workspaces/${workspaceId}/cover-candidates/${coverId}/image${query ? `?${query}` : ""}`;
}
