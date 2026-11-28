"use client";

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api/client";
import { unwrapApiResponse } from "@/lib/api/request";
import type { components } from "@/lib/api/generated/openapi";
import type { Platform, WorkItemLike, WorkSummary } from "./works";

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
    // 还有在口播/剪辑中的（不含已失败）就每 15 秒刷新，剪完的自动出现在成片页。
    refetchInterval: query => (query.state.data ?? []).some(item => (item.stage === "talking" || item.stage === "editing") && ["pending", "queued", "running"].includes(item.status)) ? 15000 : false,
  });
}

/** 我的作品：所有作品条目（进行中 + 已完成）。 */
/** 每条作品的发布平台：取自文案库条目（C1 platform），没有的不在结果里。 */
export function useScriptPlatforms(workspaceId: string, documentIds: string[]) {
  const ids = [...new Set(documentIds.filter(Boolean))].sort();
  return useQuery({
    queryKey: ["video-studio", "script-platforms", workspaceId, ids.join(",")],
    enabled: ids.length > 0,
    staleTime: 60000,
    queryFn: async ({ signal }) => {
      const page = unwrapApiResponse(await apiClient.GET(`${root}/script-library`, {
        params: { path: { workspace_id: workspaceId }, query: { ids: ids.join(","), limit: 100 } }, signal: timeout(signal),
      })) as { items: { id: string; platform: string }[] };
      return Object.fromEntries(page.items.filter(item => item.platform === "douyin" || item.platform === "xiaohongshu").map(item => [item.id, item.platform as Platform]));
    },
  });
}

export const WORK_PAGE = 50;

/** B2：我的作品——作品条目按游标翻页（after=上一页最后一条 id，不足一页即到底），不再固定只取 200 条。 */
export function useWorkItemPages(workspaceId: string, active: boolean) {
  return useInfiniteQuery({
    queryKey: finishingKeys.items(workspaceId, "pages"),
    initialPageParam: undefined as string | undefined,
    staleTime: 5000,
    queryFn: async ({ pageParam, signal }) => unwrapApiResponse(await apiClient.GET(`${root}/work-items`, {
      params: { path: { workspace_id: workspaceId }, query: { limit: WORK_PAGE, ...(pageParam ? { after: pageParam } : {}) } }, signal: timeout(signal),
    })) as WorkItem[],
    getNextPageParam: page => page.length < WORK_PAGE ? undefined : page.at(-1)?.id,
    refetchInterval: active ? 20000 : false,
  });
}

/** B1：顶部计数（不含已删除），与 group 同一口径。 */
export function useWorkSummary(workspaceId: string) {
  return useQuery({
    queryKey: finishingKeys.items(workspaceId, "summary"),
    staleTime: 5000,
    queryFn: async ({ signal }) => unwrapApiResponse(await apiClient.GET(`${root}/work-items/summary`, {
      params: { path: { workspace_id: workspaceId } }, signal: timeout(signal),
    })) as WorkSummary,
    refetchInterval: query => (query.state.data?.active ?? 0) > 0 ? 20000 : false,
  });
}

/** 一批的全部条目（按批内顺序），给「导出这一批」用。 */
export function useBatchItems(workspaceId: string, batchId: string | null) {
  return useQuery({
    queryKey: finishingKeys.items(workspaceId, `export:${batchId}`),
    enabled: Boolean(batchId),
    staleTime: 5000,
    queryFn: async ({ signal }) => unwrapApiResponse(await apiClient.GET(`${root}/work-items`, {
      params: { path: { workspace_id: workspaceId }, query: { batch_id: batchId!, limit: 50 } }, signal: timeout(signal),
    })) as WorkItem[],
  });
}

/** 删除（软删除，文件保留）、重试、已发布标记。成功后刷新作品列表与计数。 */
export function useWorkItemActions(workspaceId: string) {
  const client = useQueryClient();
  const settle = () => client.invalidateQueries({ queryKey: ["video-studio", "work-items", workspaceId] });
  const remove = useMutation({
    mutationFn: async (itemId: string) => unwrapApiResponse(await apiClient.DELETE(`${root}/work-items/{item_id}`, {
      params: { path: { workspace_id: workspaceId, item_id: itemId } }, signal: timeout(),
    })) as WorkItem,
    onSuccess: settle,
  });
  const retry = useMutation({
    mutationFn: async (input: { itemId: string; stage: "talking" | "editing" }) => {
      const path = { workspace_id: workspaceId, item_id: input.itemId };
      if (input.stage === "talking") return unwrapApiResponse(await apiClient.POST(`${root}/work-items/{item_id}/talking-retry`, { params: { path }, signal: timeout() }));
      return unwrapApiResponse(await apiClient.POST(`${root}/work-items/{item_id}/editing-retry`, { params: { path }, signal: timeout() }));
    },
    onSettled: settle,
  });
  const publish = useMutation({
    mutationFn: async (input: { itemId: string; version: number; published: boolean }) => unwrapApiResponse(await apiClient.PATCH(`${root}/work-items/{item_id}`, {
      params: { path: { workspace_id: workspaceId, item_id: input.itemId } }, body: { expected_version: input.version, published: input.published }, signal: timeout(),
    })) as WorkItem,
    onSuccess: settle,
  });
  return { remove, retry, publish };
}

/** 作品条目能播的视频地址（剪辑成片优先，其次口播结果）；给批量下载用。 */
export async function resolveWorkVideo(workspaceId: string, item: Pick<WorkItemLike, "editing_task_id" | "generation_task_id" | "source_video_ref">): Promise<string | null> {
  const editing = item.editing_task_id ?? null;
  const talking = item.generation_task_id ?? (item.source_video_ref?.kind === "talking" ? item.source_video_ref.id : null);
  if (editing) {
    const task = unwrapApiResponse(await apiClient.GET(`${root}/editing-tasks/{task_id}`, {
      params: { path: { workspace_id: workspaceId, task_id: editing } }, signal: timeout(),
    })) as { artifacts?: { role: string; url: string }[] };
    const final = task.artifacts?.find(artifact => artifact.role === "final");
    if (final) return final.url;
  }
  return talking ? `/api/v1/video-studio/workspaces/${workspaceId}/generation-tasks/${talking}/video` : null;
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
