"use client";

import { useCallback, useEffect, useState } from "react";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/api-error";
import { unwrapApiResponse } from "@/lib/api/request";
import type { components } from "@/lib/api/generated/openapi";

export type AssistanceKind = "create" | "rewrite" | "extract";
export type AssistantMode = AssistanceKind | "benchmark";
export type BenchmarkSort = "relevance" | "newest" | "most_liked";
export type BenchmarkWindow = "unlimited" | "one_day" | "one_week" | "half_year";
export type BenchmarkCriteria = { keyword: string; sort: BenchmarkSort; publish_time: BenchmarkWindow };
export type BenchmarkItem = {
  platform_id: string;
  source_url: string;
  description: string;
  author_name: string | null;
  author_id: string | null;
  posted_at: string | null;
  duration_seconds: number | null;
  like_count: number | null;
  comment_count: number | null;
  collect_count: number | null;
  share_count: number | null;
  collect_like_ratio: number | null;
  share_like_ratio: number | null;
  media_status: "link_reported" | "unverified";
};
type BenchmarkPage = BenchmarkCriteria & {
  page: number;
  root_task_id: string;
  items?: BenchmarkItem[];
  has_more?: boolean;
  next_page_expires_at?: string;
  captured_at?: string;
  received_count?: number;
  duplicate_count?: number;
  skipped_count?: number;
  author_count?: number;
  top_author_item_count?: number;
  unknown_author_count?: number;
};
export type AssistanceJob = { id: string; request_id: string; project_id: string; kind: string; status: string; stage: string; error_code: string | null; source_revision: number; can_resume: boolean; benchmark_source?: components["schemas"]["BenchmarkExtractionSource"] | null; result: { title?: string; script?: string; warnings?: string[]; text?: string; source_url?: string; segments?: { start: number; end: number; text: string }[] } };
export type BenchmarkJob = AssistanceJob & { kind: "benchmark_search"; result: BenchmarkPage };
export type BenchmarkExtractionPick = components["schemas"]["BenchmarkExtractionPick"];
export type BenchmarkExtractionJob = AssistanceJob & { benchmark_source: NonNullable<AssistanceJob["benchmark_source"]> };
type BenchmarkSubmission = BenchmarkCriteria & { request_id: string; project_id: string; expected_revision: number };
type Submission = { request_id: string; project_id: string; expected_revision: number; kind: AssistanceKind; brief: string; style: "产品介绍" | "好物种草" | "知识分享" | "品牌故事"; reference_id?: string };
const root = "/api/v1/video-studio/workspaces/{workspace_id}" as const;

export function useVideoAssistance(userId: string, workspaceId: string, projectId: string) {
  const [jobs, setJobs] = useState<AssistanceJob[]>([]);
  const current = jobs.filter(j => j.project_id === projectId);
  const options = useCallback(() => ({ params: { path: { workspace_id: workspaceId } }, signal: AbortSignal.timeout(12000), cache: "no-store" as const }), [workspaceId]);
  const reload = useCallback(async () => {
    if (!projectId) return [];
    const response = unwrapApiResponse(await apiClient.GET(`${root}/assistance-tasks`, { ...options(), params: { path: { workspace_id: workspaceId }, query: { project_id: projectId } } }));
    setJobs(response as AssistanceJob[]);
    return response as AssistanceJob[];
  }, [options, workspaceId, projectId]);
  useEffect(() => { let active = true; void Promise.resolve().then(() => { if (active) void reload().catch(() => undefined); }); return () => { active = false; }; }, [reload]);
  const running = current.some(j => ["queued", "running"].includes(j.status));
  useEffect(() => { if (!running) return; const timer = setInterval(() => { void reload().catch(() => undefined); }, 3000); return () => clearInterval(timer); }, [running, reload]);
  const remember = (job: AssistanceJob) => setJobs(previous => [job, ...previous.filter(j => j.id !== job.id)]);
  const submitOnce = async <Body extends { request_id: string; project_id: string }>(
    keyPart: string,
    body: Body,
    send: (pending: Body) => Promise<AssistanceJob>,
  ) => {
    const key = `polaris-video-assistance:${userId}:${workspaceId}:${body.project_id}:${keyPart}`;
    let pending = body;
    try { const saved = sessionStorage.getItem(key); if (saved) pending = JSON.parse(saved) as Body; } catch {}
    try { sessionStorage.setItem(key, JSON.stringify(pending)); } catch {}
    try {
      const result = await send(pending);
      try { sessionStorage.removeItem(key); } catch {}
      remember(result);
      return result;
    } catch (error) {
      if (error instanceof ApiError && error.status && error.status >= 400 && error.status < 500) {
        try { sessionStorage.removeItem(key); } catch {}
        throw error;
      }
      const found = await reload().then(rows => rows.find(j => j.request_id === pending.request_id)).catch(() => undefined);
      if (found) { try { sessionStorage.removeItem(key); } catch {} return found; }
      throw error;
    }
  };
  const submit = (body: Omit<Submission, "request_id">) =>
    submitOnce(body.kind, { ...body, request_id: crypto.randomUUID() }, async pending =>
      unwrapApiResponse(await apiClient.POST(`${root}/assistance-tasks`, { ...options(), body: pending })) as AssistanceJob);
  const submitBenchmark = (body: Omit<BenchmarkSubmission, "request_id">) =>
    submitOnce("benchmark_search", { ...body, request_id: crypto.randomUUID() }, async pending =>
      unwrapApiResponse(await apiClient.POST(`${root}/benchmark-searches`, { ...options(), body: pending })) as AssistanceJob);
  const nextBenchmarkPage = async (id: string) => {
    const job = unwrapApiResponse(await apiClient.POST(`${root}/benchmark-searches/{task_id}/next`, {
      ...options(), params: { path: { workspace_id: workspaceId, task_id: id } },
    })) as AssistanceJob;
    remember(job);
  };
  const resume = async (id: string) => { unwrapApiResponse(await apiClient.POST(`${root}/assistance-tasks/{task_id}/resume`, { ...options(), params: { path: { workspace_id: workspaceId, task_id: id } } })); await reload(); };
  const submitBenchmarkExtractions = async (body: components["schemas"]["BenchmarkExtractionRequest"]) => {
    const results = unwrapApiResponse(await apiClient.POST(`${root}/benchmark-extractions`, { ...options(), body })) as AssistanceJob[];
    const ids = new Set(results.map(job => job.id));
    setJobs(previous => [...results, ...previous.filter(job => !ids.has(job.id))]);
  };
  const latest = (kind: AssistanceKind) => current.find(j => j.kind === kind && !j.benchmark_source);
  const busy = (kind: AssistanceKind) => ["queued", "running", "unknown"].includes(latest(kind)?.status || "");
  const benchmarkJobs = current.filter((job): job is BenchmarkJob => job.kind === "benchmark_search");
  const benchmarkExtractions = current.filter((job): job is BenchmarkExtractionJob => job.kind === "extract" && !!job.benchmark_source);
  return { latest, busy, submit, reload, resume, benchmarkJobs, submitBenchmark, nextBenchmarkPage, benchmarkExtractions, submitBenchmarkExtractions };
}

export function assistanceMessage(job: AssistanceJob | undefined) {
  if (!job) return "";
  if (["queued", "running"].includes(job.status)) return job.kind === "extract" ? "正在提取语音文稿…" : "正在生成文案…";
  if (job.status === "unknown") return "提交结果待核对，请勿重复提交。";
  if (job.status === "failed") return job.error_code === "VIDEO_TRANSCRIPT_EMPTY" ? "未提取到语音文稿，请确认视频有人声，或粘贴原文。" : "处理未完成，请核对输入和服务状态后重试。";
  if (job.status === "awaiting_resume") return "可继续查询原提取任务。";
  return "";
}
