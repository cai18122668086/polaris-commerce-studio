"use client";
import { useCallback, useEffect, useState } from "react";
import { apiClient } from "@/lib/api/client";
import { unwrapApiResponse } from "@/lib/api/request";
import type { components } from "@/lib/api/generated/openapi";
import { uploadWithProgress, type UploadProgress } from "@/lib/api/upload";
export type ClonedVoice = components["schemas"]["CloneResponse"];
export type CloneConfig = components["schemas"]["CloneConfigResponse"];
const root = "/api/v1/video-studio/workspaces/{workspace_id}" as const;

export function useVoiceClones(workspaceId: string) {
  const [voices, setVoices] = useState<ClonedVoice[]>([]);
  const [config, setConfig] = useState<CloneConfig>();
  const [error, setError] = useState("");
  const options = useCallback(() => ({ params: { path: { workspace_id: workspaceId } }, signal: AbortSignal.timeout(15000), cache: "no-store" as const }), [workspaceId]);
  const reload = useCallback(async () => {
    const [list, settings] = await Promise.all([apiClient.GET(`${root}/voice-clones`, options()), apiClient.GET(`${root}/voice-clone-config`, options())]);
    setVoices(unwrapApiResponse(list)); setConfig(unwrapApiResponse(settings)); setError("");
  }, [options]);
  useEffect(() => { let active = true; void Promise.resolve().then(() => { if (active) void reload().catch(() => setError("专属声音暂时无法读取，请刷新重试。")); }); return () => { active = false; }; }, [reload]);
  const running = voices.some(v => ["queued", "submitting", "processing"].includes(v.status) || v.preview_status === "submitting");
  useEffect(() => {
    if (!running) return;
    let active = true; let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const list = unwrapApiResponse(await apiClient.GET(`${root}/voice-clones`, options()));
        // processing already has a remote identity: refresh only queries it.
        // Never auto-resubmit queued/unknown creation or any preview synthesis.
        const next = await Promise.all(list.map(async voice => voice.status === "processing"
          ? unwrapApiResponse(await apiClient.POST(`${root}/voice-clones/{voice_id}/refresh`, { ...options(), params: { path: { workspace_id: workspaceId, voice_id: voice.id } } })) : voice));
        if (active) { setVoices(next); setError(""); }
      } catch { if (active) setError("进度更新暂时中断，正在重新连接；请勿重复创建。"); }
      finally { if (active) timer = setTimeout(() => { void poll(); }, 3000); }
    };
    timer = setTimeout(() => { void poll(); }, 1500);
    return () => { active = false; clearTimeout(timer); };
  }, [running, options, workspaceId]);
  const create = async (file: File, name: string, requestId: string, progress: (value: UploadProgress) => void) => {
    if (!config?.available) throw new Error("专属声音服务尚未配置，请联系管理员。");
    const data = new FormData(); data.append("file", file); data.append("name", name); data.append("request_id", requestId); data.append("consent", config.consent_version);
    const result = unwrapApiResponse(await apiClient.POST(`${root}/voice-clones`, { ...options(), signal: AbortSignal.timeout(90000), body: {} as never, bodySerializer: () => data, fetch: uploadWithProgress(data, progress) }));
    setVoices(current => [result, ...current.filter(voice => voice.id !== result.id)]);
    return result;
  };
  const refresh = async (voice: ClonedVoice) => {
    unwrapApiResponse(await apiClient.POST(`${root}/voice-clones/{voice_id}/refresh`, { ...options(), params: { path: { workspace_id: workspaceId, voice_id: voice.id } } })); await reload();
  };
  const preview = async (voice: ClonedVoice) => {
    unwrapApiResponse(await apiClient.POST(`${root}/voice-clones/{voice_id}/preview`, { ...options(), params: { path: { workspace_id: workspaceId, voice_id: voice.id } } })); await reload();
  };
  return { voices, config, error, reload, create, refresh, preview };
}
