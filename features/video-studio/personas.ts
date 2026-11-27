"use client";

import { useCallback, useEffect, useState } from "react";
import { apiClient } from "@/lib/api/client";
import { unwrapApiResponse } from "@/lib/api/request";
import type { components } from "@/lib/api/generated/openapi";
import { personaDraftPatch, sortPersonas } from "./persona-rules";

/** 固定形象 = 一个形象 + 一个声音（契约 C3）。列表已带封面、声音名、试听地址。 */
export type VideoPersona = components["schemas"]["PersonaResponse"];
export type PersonaInput = { name: string; avatar_id: string; voice_id: string; emotion?: string | null; language?: string | null };
const root = "/api/v1/video-studio/workspaces/{workspace_id}" as const;

export { personaDraftPatch, sortPersonas };

/**
 * 固定形象列表与增删改。创建用 request_id 幂等：同一次提交重试不会建出两个。
 * 口播页、形象库页、抽屉共用这一份状态（由页面持有后传给抽屉）。
 */
export function usePersonas(workspaceId: string) {
  const [personas, setPersonas] = useState<VideoPersona[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const options = useCallback(() => ({ params: { path: { workspace_id: workspaceId } }, signal: AbortSignal.timeout(12000), cache: "no-store" as const }), [workspaceId]);
  const reload = useCallback(async () => {
    try { setPersonas(sortPersonas(unwrapApiResponse(await apiClient.GET(`${root}/personas`, options())))); setError(""); }
    catch { setError("固定形象暂时读不到，可稍后重试；已保存的形象和声音不受影响。"); }
    finally { setLoading(false); }
  }, [options]);
  useEffect(() => { let active = true; void Promise.resolve().then(() => { if (active) void reload(); }); return () => { active = false; }; }, [reload]);
  const create = async (input: PersonaInput, requestId: string) => {
    const result = unwrapApiResponse(await apiClient.POST(`${root}/personas`, { ...options(), body: { request_id: requestId, ...input } }));
    setPersonas(current => sortPersonas([result, ...current.filter(item => item.id !== result.id)]));
    return result;
  };
  const update = async (id: string, patch: Partial<PersonaInput>) => {
    const result = unwrapApiResponse(await apiClient.PATCH(`${root}/personas/{persona_id}`, { ...options(), params: { path: { workspace_id: workspaceId, persona_id: id } }, body: patch }));
    setPersonas(current => current.map(item => item.id === id ? result : item));
    return result;
  };
  const remove = async (id: string) => {
    unwrapApiResponse(await apiClient.DELETE(`${root}/personas/{persona_id}`, { ...options(), params: { path: { workspace_id: workspaceId, persona_id: id } } }));
    setPersonas(current => current.filter(item => item.id !== id));
  };
  return { personas, loading, error, reload, create, update, remove };
}
