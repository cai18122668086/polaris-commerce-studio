"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiClient } from "@/lib/api/client";
import { unwrapApiResponse } from "@/lib/api/request";
import { withAuthTimeout } from "@/lib/auth/request-timeout";
import type { VideoContent } from "./projects";
import { uploadWithProgress, type UploadProgress } from "@/lib/api/upload";

export type VideoAvatar = { id: string; name: string; gender: string; tag: string; source: "quanyu_public" | "self_owned"; cover_url: string; preview_url?: string | null; ready: boolean };
export type VideoVoice = { id: string; name: string; gender: string; tag: string; description: string; source?: "own" | "public"; available?: boolean; language?: string; preview_url?: string | null; emotions?: VideoContent["draft"]["emotion"][]; languages?: Record<string, string> };
export type StageTiming = { stage: string; started_at: string; finished_at: string | null; duration_seconds: number | null; outcome?: string };
export type GenerationJob = { id: string; request_id?: string; kind: "lipsync" | "h3_template"; avatar_id: string; project_id: string | null; confirmed_version_id?: string | null; status: string; stage: string; can_resume?: boolean; error_code?: string | null; lipsync_routing?: { long_wait?: boolean; switch_reason?: string; selected_provider?: string }; created_at: string; video_url?: string | null; audio_url?: string | null; snapshot?: VideoContent | null; handoff_url?: string | null; stage_history?: StageTiming[]; tts?: { voice_name?: string }; audio_duration_seconds?: number | null };
const root = "/api/v1/video-studio/workspaces/{workspace_id}" as const;

export function useVideoLibrary(workspaceId: string) {
  const [avatars, setAvatars] = useState<VideoAvatar[]>([]);
  const [voices, setVoices] = useState<VideoVoice[]>([]);
  const [jobs, setJobs] = useState<GenerationJob[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const resumeRequests = useRef(new Set<string>());
  const [resumingIds, setResumingIds] = useState<string[]>([]);
  const options = useCallback(() => ({ params: { path: { workspace_id: workspaceId } }, signal: AbortSignal.timeout(12000), cache: "no-store" as const }), [workspaceId]);
  const reload = useCallback(async () => {
    try {
      const [a, v, j] = await Promise.allSettled([
        apiClient.GET(`${root}/avatars`, options()).then(unwrapApiResponse), apiClient.GET(`${root}/voices`, options()).then(unwrapApiResponse), apiClient.GET(`${root}/generation-tasks`, options()).then(unwrapApiResponse),
      ]);
      if (a.status === "fulfilled") setAvatars(a.value as VideoAvatar[]);
      if (v.status === "fulfilled") setVoices(v.value as VideoVoice[]);
      if (j.status === "fulfilled") setJobs(j.value as GenerationJob[]);
      const unavailable = [a.status === "rejected" && "数字人形象", v.status === "rejected" && "音色", j.status === "rejected" && "生成记录"].filter(Boolean);
      setError(unavailable.length ? `${unavailable.join("、")}暂时无法读取，可重试。已读取的口播与上传剪辑仍可使用。` : "");
    } catch { setError("数字人库暂时无法读取，请重试。"); }
    finally { setLoading(false); }
  }, [options]);
  useEffect(() => { let active = true; void Promise.resolve().then(() => { if (active) void reload(); }); return () => { active = false; }; }, [reload]);
  useEffect(() => {
    if (!jobs.some(j => ["queued", "running", "awaiting_resume"].includes(j.status))) return;
    const timer = setInterval(() => { void apiClient.GET(`${root}/generation-tasks`, options()).then(result => { const next = unwrapApiResponse(result) as GenerationJob[]; setJobs(next); if (next.some(j => ["completed", "awaiting_review"].includes(j.status) && !jobs.some(old => old.id === j.id && old.status === j.status))) void reload(); }).catch(() => undefined); }, 5000);
    return () => clearInterval(timer);
  }, [jobs, options, reload]);
  const submit = async (body: { request_id: string; kind: "lipsync" | "h3_template"; avatar_id: string; project_id?: string; expected_revision?: number; audio_id?: string }) => {
    const result = unwrapApiResponse(await withAuthTimeout(apiClient.POST(`${root}/generation-tasks`, { ...options(), body: { ...body, prompt: "生成15秒固定机位真人口播模板，动作自然，首尾回到中性姿态，双手不遮脸，口周清晰。" } }), 15000)) as GenerationJob;
    setJobs(current => [result, ...current.filter(j => j.id !== result.id)]);
    return result;
  };
  const createAvatar = async (file: File, name: string, requestId: string, progress: (value: UploadProgress) => void) => {
    const data = new FormData(); data.append("file", file); data.append("name", name); data.append("request_id", requestId); data.append("consent", "true"); data.append("consent_version", "avatar-v1");
    const result = unwrapApiResponse(await apiClient.POST(`${root}/avatar-clones`, { ...options(), signal: AbortSignal.timeout(600000), body: {} as never, bodySerializer: () => data, fetch: uploadWithProgress(data, progress) })) as GenerationJob;
    setJobs(current => [result, ...current.filter(job => job.id !== result.id)]);
    await reload();
    return result;
  };
  const uploadAudio = async (file: File) => {
    const result = await apiClient.POST(`${root}/audio-files`, { ...options(), body: { file } as never, bodySerializer: () => { const data = new FormData(); data.append("file", file); return data; } });
    return unwrapApiResponse(result) as { id: string; name: string; duration: number };
  };
  const rejectTemplate = async (id: string) => { unwrapApiResponse(await apiClient.POST(`${root}/generation-tasks/{job_id}/reject-template`, { ...options(), params: { path: { workspace_id: workspaceId, job_id: id } } })); await reload(); };
  const approveTemplate = async (id: string) => { unwrapApiResponse(await apiClient.POST(`${root}/generation-tasks/{job_id}/approve-template`, { ...options(), params: { path: { workspace_id: workspaceId, job_id: id } } })); await reload(); };
  const resume = async (id: string) => {
    if (resumeRequests.current.has(id)) return;
    resumeRequests.current.add(id);
    setResumingIds([...resumeRequests.current]);
    try {
      const result = unwrapApiResponse(await apiClient.POST(`${root}/generation-tasks/{job_id}/resume`, { ...options(), params: { path: { workspace_id: workspaceId, job_id: id } } })) as GenerationJob;
      setJobs(current => current.map(job => job.id === id ? result : job));
      await reload();
    } finally {
      resumeRequests.current.delete(id);
      setResumingIds([...resumeRequests.current]);
    }
  };
  return { avatars, voices, jobs, loading, error, resumingIds, reload, submit, createAvatar, uploadAudio, resume, approveTemplate, rejectTemplate };
}
