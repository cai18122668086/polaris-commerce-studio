"use client";

import { useEffect, useRef, useState } from "react";
import { apiClient } from "@/lib/api/client";
import { unwrapApiResponse } from "@/lib/api/request";
import type { components } from "@/lib/api/generated/openapi";
import styles from "./editing-workspace.module.css";

type Plan = components["schemas"]["EditingNativePlanResponse"];
const root = "/api/v1/video-studio/workspaces/{workspace_id}" as const;

export function EditingNativePlans({ workspaceId, projectId, onCreated }: {
  workspaceId: string; projectId: string; onCreated: () => Promise<void>;
}) {
  const [plans, setPlans] = useState<Plan[]>([]);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  const intent = useRef<{ planId: string; id: string } | undefined>(undefined);
  const live = useRef(true);
  useEffect(() => { live.current = true; return () => { live.current = false; }; }, []);
  useEffect(() => {
    const controller = new AbortController();
    void apiClient.GET(`${root}/projects/{project_id}/editing-native-plans`, {
      params: { path: { workspace_id: workspaceId, project_id: projectId } },
      signal: AbortSignal.any([controller.signal, AbortSignal.timeout(12000)]),
    }).then(result => { if (!controller.signal.aborted) { setPlans(unwrapApiResponse(result)); setError(""); } })
      .catch(() => { if (!controller.signal.aborted) setError("暂时无法读取动效编排，请重试。"); });
    return () => controller.abort();
  }, [workspaceId, projectId, reload]);
  const render = async (plan: Plan) => {
    setBusy(plan.id); setError("");
    try {
      if (!intent.current || intent.current.planId !== plan.id) intent.current = { planId: plan.id, id: crypto.randomUUID() };
      unwrapApiResponse(await apiClient.POST(`${root}/editing-tasks`, {
        params: { path: { workspace_id: workspaceId } }, signal: AbortSignal.timeout(12000),
        body: { request_id: intent.current.id, source_id: plan.source_id, options: {
          mode: "native_plan", native_plan_id: plan.id, language: "zh",
          source_subtitles: plan.source_subtitles, caption_font_id: "font-d1961be1161ea1be",
        } },
      }));
      intent.current = undefined;
      if (live.current) await onCreated();
    } catch (caught) { if (live.current) setError(caught instanceof Error ? caught.message : "出片请求暂未确认，再次点击会查询同一请求。"); }
    finally { if (live.current) setBusy(""); }
  };
  return <section aria-label="动效编排候选">
    <b>已有动效编排候选</b>
    <p className={styles.note}>每份候选绑定原片、逐词转录和选组版本；出片后仍需核对语义、字幕及观看听感。</p>
    {plans.length === 0 && !error && <p>当前项目还没有保存的编排。</p>}
    {plans.map(plan => <article key={plan.id}>
      <b>{plan.audience_question}</b>
      <p>{plan.origin === "operator_candidate" ? "人工工程候选 · 未经人工验收" : "腾力模型候选 · 待核对"}</p>
      <ul>{plan.beats.map((beat, i) => <li key={i}>{String(beat.group_id)} · {String(beat.text)}<br />{String(beat.reason)}</li>)}</ul>
      {(plan.warnings.length > 0 || plan.missing_materials.length > 0) && <p>{[...plan.warnings, ...plan.missing_materials].join("；")}</p>}
      <button type="button" onClick={() => void render(plan)} disabled={!!busy || !plan.render_available}>{busy === plan.id ? "正在提交…" : "按此动效编排出片"}</button>
    </article>)}
    {error && <p role="alert" className={styles.error}>{error} <button type="button" onClick={() => setReload(n => n + 1)}>重新读取编排</button></p>}
  </section>;
}
