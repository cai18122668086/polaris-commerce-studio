"use client";

import { apiClient } from "@/lib/api/client";
import { unwrapApiResponse } from "@/lib/api/request";
import { withAuthTimeout } from "@/lib/auth/request-timeout";
import type { components } from "@/lib/api/generated/openapi";
import { batchItems, type TalkingBatch, type TalkingDraft, type TalkingScript } from "./talking-batch";

const root = "/api/v1/video-studio/workspaces/{workspace_id}" as const;
export type LibraryEntry = components["schemas"]["LibraryEntry"];

export function scriptFromLibrary(entry: LibraryEntry): TalkingScript {
  return { key: `doc:${entry.id}`, source: "library", documentId: entry.id, title: entry.publish_title || entry.display_title, body: entry.publish_body, script: entry.script, chars: entry.script_chars, seconds: entry.script_seconds };
}

/** 口播面板用到的接口。每个请求都带超时；生成相关的请求可以原样重发（后端幂等）。 */
export function talkingApi(workspaceId: string) {
  const path = { workspace_id: workspaceId };
  const options = (timeout = 12000) => ({ signal: AbortSignal.timeout(timeout), cache: "no-store" as const });
  return {
    async library(query: { q?: string; offset?: number; limit?: number } = {}) {
      return unwrapApiResponse(await apiClient.GET(`${root}/script-library`, { ...options(), params: { path, query: { q: query.q || "", limit: query.limit ?? 30, offset: query.offset ?? 0 } } }));
    },
    async libraryByIds(ids: string[]) {
      return unwrapApiResponse(await apiClient.GET(`${root}/script-library`, { ...options(), params: { path, query: { ids: ids.join(",") } } }));
    },
    /** 建批次 + 确认生成。两步都按 draft.requestId 幂等：重复点、断网重试都落到同一个批次。 */
    async submit(draft: TalkingDraft & { requestId: string }): Promise<TalkingBatch> {
      const batch = unwrapApiResponse(await withAuthTimeout(apiClient.POST(`${root}/work-batches`, { ...options(15000), params: { path }, body: { request_id: draft.requestId, source: "talking", items: batchItems(draft) } }), 15000));
      return unwrapApiResponse(await withAuthTimeout(apiClient.POST(`${root}/work-batches/{batch_id}/talking`, { ...options(20000), params: { path: { ...path, batch_id: batch.id } } }), 20000)) as TalkingBatch;
    },
    async status(batchId: string): Promise<TalkingBatch> {
      return unwrapApiResponse(await apiClient.GET(`${root}/work-batches/{batch_id}/talking`, { ...options(), params: { path: { ...path, batch_id: batchId } } })) as TalkingBatch;
    },
    async retry(itemId: string): Promise<TalkingBatch> {
      return unwrapApiResponse(await withAuthTimeout(apiClient.POST(`${root}/work-items/{item_id}/talking-retry`, { ...options(20000), params: { path: { ...path, item_id: itemId } } }), 20000)) as TalkingBatch;
    },
    /** 查询结果：只查询原任务，不会重新生成。 */
    async check(itemId: string): Promise<TalkingBatch> {
      return unwrapApiResponse(await withAuthTimeout(apiClient.POST(`${root}/work-items/{item_id}/talking-check`, { ...options(20000), params: { path: { ...path, item_id: itemId } } }), 20000)) as TalkingBatch;
    },
    /** 换浏览器/刷新后找回：最近一个还有未完成条目的口播批次（从后端读，不靠本机存储）。 */
    async latestOpenBatch(): Promise<string | null> {
      const batches = unwrapApiResponse(await apiClient.GET(`${root}/work-batches`, { ...options(), params: { path, query: { source: "talking", limit: 5 } } }));
      const open = batches.find(batch => batch.items.some(item => item.stage === "talking" && ["queued", "running"].includes(item.status)));
      return open?.id ?? null;
    },
  };
}
