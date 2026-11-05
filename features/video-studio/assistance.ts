"use client";

import { useCallback, useEffect, useState } from "react";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/api-error";
import { unwrapApiResponse } from "@/lib/api/request";

export type AssistanceKind = "create" | "rewrite" | "extract";
export type AssistanceJob = { id: string; request_id: string; project_id: string; kind: string; status: string; stage: string; error_code: string | null; source_revision: number; can_resume: boolean; result: { title?: string; script?: string; warnings?: string[]; text?: string; source_url?: string; segments?: { start: number; end: number; text: string }[] } };
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
  const submit = async (body: Omit<Submission, "request_id">) => {
    const key = `polaris-video-assistance:${userId}:${workspaceId}:${body.project_id}:${body.kind}`;
    let pending: Submission = { ...body, request_id: crypto.randomUUID() };
    try { const saved = sessionStorage.getItem(key); if (saved) pending = JSON.parse(saved) as Submission; } catch {}
    try { sessionStorage.setItem(key, JSON.stringify(pending)); } catch {}
    try {
      const result = unwrapApiResponse(await apiClient.POST(`${root}/assistance-tasks`, { ...options(), body: pending })) as AssistanceJob;
      try { sessionStorage.removeItem(key); } catch {}
      setJobs(previous => [result, ...previous.filter(j => j.id !== result.id)]);
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
  const resume = async (id: string) => { unwrapApiResponse(await apiClient.POST(`${root}/assistance-tasks/{task_id}/resume`, { ...options(), params: { path: { workspace_id: workspaceId, task_id: id } } })); await reload(); };
  const latest = (kind: AssistanceKind) => current.find(j => j.kind === kind);
  const busy = (kind: AssistanceKind) => ["queued", "running", "unknown"].includes(latest(kind)?.status || "");
  return { latest, busy, submit, reload, resume };
}

export function assistanceMessage(job: AssistanceJob | undefined) {
  if (!job) return "";
  if (["queued", "running"].includes(job.status)) return job.kind === "extract" ? "正在提取语音文稿…" : "正在生成文案…";
  if (job.status === "unknown") return "提交结果待核对，请勿重复提交。";
  if (job.status === "failed") return job.error_code === "VIDEO_TRANSCRIPT_EMPTY" ? "未提取到语音文稿，请确认视频有人声，或粘贴原文。" : "处理未完成，请核对输入和服务状态后重试。";
  if (job.status === "awaiting_resume") return "可继续查询原提取任务。";
  return "";
}
