"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiClient } from "@/lib/api/client";
import { unwrapApiResponse } from "@/lib/api/request";
import { mediaUrl } from "@/lib/api/base-url";
import type { components } from "@/lib/api/generated/openapi";

export type PolishCandidate = components["schemas"]["PolishCandidateResponse"];
const root = "/api/v1/video-studio/workspaces/{workspace_id}" as const;

/** 一键填入的示例描述（与后端 PRESETS 同步，展示用短标签 + 实际描述）。 */
export const POLISH_PRESETS: { label: string; description: string }[] = [
  { label: "职业西装·干净背景", description: "穿合身的深色西装、白衬衫，干净的浅灰色纯色背景，柔和均匀的影棚光" },
  { label: "门店店长·暖光", description: "穿整洁的店长工作服，站在明亮整洁的门店里，背景虚化，暖色自然光" },
  { label: "居家主播·自然光", description: "穿简洁的日常针织上衣，坐在干净温馨的客厅里，背景虚化，窗边柔和自然光" },
  { label: "户外街景·清爽", description: "穿清爽的休闲衬衫，站在干净的城市街道旁，背景虚化，白天柔和日光" },
];
export const POLISH_DESCRIPTION_MAX = 120;

/** 前端先做一遍和后端一致的拦截，减少无效提交（后端仍会再查）。 */
const FACE_SWAP = /换脸|换.{0,4}脸|(变成|换成|改成|弄成|p成|P成).{0,12}(的脸|的长相|的五官|的面孔)|别人的脸|他人的脸|别人的长相|(变成|换成|改成|弄成|p成|P成).{0,12}(明星|名人|网红|演员|歌手|偶像|总统|主席)|(长得|长相|脸).{0,6}像|像.{0,12}(明星|名人|演员|歌手|偶像)|明星脸|名人脸|网红脸|整容成|face\s*-?\s*swap|deep\s*-?\s*fake|celebrity/i;
const UNSAFE = /裸|露点|色情|情色|性感内衣|比基尼|泳装|暴露|走光|低胸|透视装|血腥|暴力|毒品|未成年|nude|naked|nsfw|lingerie|bikini|sexy/i;
export function polishDescriptionError(text: string): string {
  const value = text.trim();
  if (!value) return "写一句想要的样子，或点一个示例";
  if (value.length > POLISH_DESCRIPTION_MAX) return `描述最多 ${POLISH_DESCRIPTION_MAX} 个字`;
  if (FACE_SWAP.test(value)) return "AI 润色会保持你本人的五官，只改穿着、场景和光线，不能换成他人或名人的脸。";
  if (UNSAFE.test(value)) return "描述里有不适合用于数字人形象的内容，请换成穿着、场景、光线方面的描述。";
  return "";
}

export const polishRunning = (items: PolishCandidate[]) => items.some(item => item.status === "queued" || item.status === "running");

/** AI 润色：提交一次生成 1～2 张候选，轮询到全部结束；同一 request_id 重试不会重复扣费。 */
export function useAvatarPolish(workspaceId: string) {
  const [candidates, setCandidates] = useState<PolishCandidate[]>([]);
  const [requestId, setRequestId] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const options = useCallback(() => ({ params: { path: { workspace_id: workspaceId } }, signal: AbortSignal.timeout(15000), cache: "no-store" as const }), [workspaceId]);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const refresh = useCallback(async (id: string) => {
    const rows = unwrapApiResponse(await apiClient.GET(`${root}/avatar-polishes`, { ...options(), params: { path: { workspace_id: workspaceId }, query: { request_id: id } } }));
    setCandidates(rows);
    return rows;
  }, [options, workspaceId]);
  useEffect(() => {
    if (!requestId || !polishRunning(candidates)) return;
    timer.current = setTimeout(() => { void refresh(requestId).catch(() => setError("进度暂时读不到，正在重试；不会重复扣费。")); }, 3000);
    return () => clearTimeout(timer.current);
  }, [candidates, requestId, refresh]);
  const generate = async (file: File, description: string, count = 2) => {
    if (busy) return;
    const id = requestId && !candidates.length ? requestId : crypto.randomUUID();
    setRequestId(id); setBusy(true); setError("");
    const data = new FormData();
    data.append("file", file); data.append("description", description.trim()); data.append("request_id", id);
    data.append("consent", "true"); data.append("consent_version", "avatar-v1"); data.append("count", String(count));
    try {
      const rows = unwrapApiResponse(await apiClient.POST(`${root}/avatar-polishes`, { ...options(), signal: AbortSignal.timeout(120000), body: {} as never, bodySerializer: () => data }));
      setCandidates(rows);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "提交没有完成，请重试；同一次提交不会重复扣费。");
    } finally { setBusy(false); }
  };
  const reset = () => { setCandidates([]); setRequestId(""); setError(""); };
  /** 把选中的候选取回成 File，交给原有的「创建形象」上传。 */
  const toFile = async (candidate: PolishCandidate) => {
    if (!candidate.image_url) throw new Error("这张候选还没有生成好");
    const response = await fetch(mediaUrl(candidate.image_url) || candidate.image_url, { credentials: "include", cache: "no-store" });
    if (!response.ok) throw new Error("候选图片暂时取不到，请稍后再试");
    return new File([await response.blob()], `ai-polish-${candidate.slot}.jpg`, { type: "image/jpeg" });
  };
  return { candidates, error, busy, running: polishRunning(candidates), generate, reset, toFile };
}
