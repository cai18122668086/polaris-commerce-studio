import { apiClient } from "@/lib/api/client";
import { withAuthTimeout } from "@/lib/auth/request-timeout";
import { unwrapApiResponse } from "@/lib/api/request";

export type VideoDraft = { name: string; text: string; avatarId: string; voiceId: string; speed: number; emotion: "自然" | "愉快" | "温柔" | "专业" | "平静" | "悲伤" | "愤怒" | "害怕" | "厌恶" | "惊讶"; language: string; quality: "720P" | "1080P"; drive: "text" | "audio"; audioAssetId?: string | null };
export type VideoReference = { id: string; kind: "text" | "url"; url: string; original_text: string; note: string };
export type VideoMedia = { id: string; kind: "audio" | "avatar_sample" | "voice_sample"; name: string; mime_type: string; size_bytes: number; availability: "local_only" };
export type VideoContent = { draft: VideoDraft; product_facts: string; references: VideoReference[]; media: VideoMedia[] };
export type VideoProject = { id: string; workspace_id: string; revision: number; content: VideoContent; created_at: string; updated_at: string };
export type VideoVersion = { id: string; project_id: string; kind: "draft" | "library" | "confirmed"; snapshot: VideoContent; created_at: string };
export type VideoTask = { id: string; project_id: string; confirmed_version_id: string; status: "demo"; snapshot: VideoContent; created_at: string };
export type VideoWrite = { request_id: string; expected_revision: number; content: VideoContent; action: "save" | "library" | "demo" };
export type VideoWriteResult = { project: VideoProject; version?: VideoVersion | null; task?: VideoTask | null };
export const emptyVideoContent = (): VideoContent => ({ draft: { name: "未命名视频", text: "", avatarId: "", voiceId: "", speed: 1, emotion: "自然", language: "auto", quality: "1080P", drive: "text" }, product_facts: "", references: [], media: [] });

const root = "/api/v1/video-studio/workspaces/{workspace_id}" as const;
export function projectApi(workspaceId: string) {
  const params = { path: { workspace_id: workspaceId } };
  const options = () => ({ params, cache: "no-store" as const, signal: AbortSignal.timeout(8000) });
  return {
    projects: async () => unwrapApiResponse(await withAuthTimeout(apiClient.GET(`${root}/projects`, options()))) as VideoProject[],
    project: async (id: string) => unwrapApiResponse(await withAuthTimeout(apiClient.GET(`${root}/projects/{project_id}`, { ...options(), params: { path: { workspace_id: workspaceId, project_id: id } } }))) as VideoProject,
    versions: async (id?: string, kind: "draft" | "library" | "confirmed" = "library") => unwrapApiResponse(await withAuthTimeout(apiClient.GET(`${root}/versions`, { ...options(), params: { ...params, query: { project_id: id, kind } } }))) as VideoVersion[],
    tasks: async () => unwrapApiResponse(await withAuthTimeout(apiClient.GET(`${root}/tasks`, options()))) as VideoTask[],
    write: async (id: string, body: VideoWrite) => unwrapApiResponse(await withAuthTimeout(apiClient.PUT(`${root}/projects/{project_id}`, { ...options(), params: { path: { workspace_id: workspaceId, project_id: id } }, body }))) as VideoWriteResult,
    importLegacy: async (body: { request_id: string; draft: VideoDraft; copies: { id: string; title: string; text: string; date: string }[]; works: { id: string; draft: VideoDraft; date: string }[] }) => unwrapApiResponse(await withAuthTimeout(apiClient.POST(`${root}/imports/legacy`, { ...options(), body }))) as VideoWriteResult,
  };
}

export type VideoProjectApi = ReturnType<typeof projectApi>;
