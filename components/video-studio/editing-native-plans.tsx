"use client";

import { useEffect, useRef, useState } from "react";
import { apiClient } from "@/lib/api/client";
import { unwrapApiResponse } from "@/lib/api/request";
import type { components } from "@/lib/api/generated/openapi";
import styles from "./editing-workspace.module.css";

type Plan = components["schemas"]["EditingNativePlanResponse"];
type NativeEdits = components["schemas"]["NativeRenderEdits"];
type Controls = { music: "keep" | "lower" | "off"; segments: string[] };
const defaultControls: Controls = { music: "keep", segments: [] };
const root = "/api/v1/video-studio/workspaces/{workspace_id}" as const;

export function EditingNativePlans({ workspaceId, projectId, onCreated }: {
  workspaceId: string; projectId: string; onCreated: () => Promise<void>;
}) {
  const [plans, setPlans] = useState<Plan[]>([]);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  const [controls, setControls] = useState<Record<string, Controls>>({});
  const intent = useRef<{ key: string; id: string } | undefined>(undefined);
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
  const render = async (plan: Plan, selected: Controls) => {
    setBusy(plan.id); setError("");
    try {
      const segments = selected.segments.slice().sort();
      const music = selected.music === "keep" ? null : selected.music;
      const edits: NativeEdits | undefined = music || segments.length ? { music, source_only_beat_ids: segments } : undefined;
      const key = JSON.stringify([plan.id, edits]);
      if (intent.current?.key !== key) intent.current = { key, id: crypto.randomUUID() };
      unwrapApiResponse(await apiClient.POST(`${root}/editing-tasks`, {
        params: { path: { workspace_id: workspaceId } }, signal: AbortSignal.timeout(12000),
        body: { request_id: intent.current.id, source_id: plan.source_id, options: {
          mode: "native_plan", native_plan_id: plan.id, language: "zh",
          source_subtitles: plan.source_subtitles, caption_font_id: "font-d1961be1161ea1be",
          native_edits: edits, delivery: "preview_first",
        } },
      }));
      intent.current = undefined;
      if (live.current) await onCreated();
    } catch (caught) { if (live.current) setError(caught instanceof Error ? caught.message : "出片请求暂未确认，再次点击会查询同一请求。"); }
    finally { if (live.current) setBusy(""); }
  };
  return <section aria-label="动效编排候选">
    <b>已有动效编排候选</b>
    <p className={styles.note}>每份候选绑定原片、逐词转录和选组版本。先看代理预览，再确认并下载对应的高清文件。</p>
    {plans.length === 0 && !error && <p>当前项目还没有保存的编排。</p>}
    {plans.map(plan => {
      const selected = controls[plan.id] || defaultControls;
      const change = (update: Partial<Controls>) => setControls(current => ({
        ...current, [plan.id]: { ...(current[plan.id] || defaultControls), ...update },
      }));
      const editable = plan.beats.filter(beat => beat.source_only_available);
      const activeEffects = plan.beats.filter(beat => beat.group_id !== "Z-M00" && !selected.segments.includes(beat.id));
      const activeGroups = new Set(activeEffects.map(beat => beat.group_id));
      const available = plan.render_available && plan.continuous_preview_available;
      return <article key={plan.id}>
      <b>{plan.audience_question}</b>
      {plan.overlay_template && <p className={styles.note}>组合模板 · {plan.overlay_template.name}</p>}
      <p>{plan.origin === "operator_candidate" ? "人工工程候选 · 未经人工验收" : "腾力模型候选 · 待核对"}</p>
      <ul>{plan.beats.map(beat => <li key={beat.id}>{beat.group_id} · {beat.text}<br />{beat.reason}</li>)}</ul>
      {(plan.warnings.length > 0 || plan.missing_materials.length > 0) && <p>{[...plan.warnings, ...plan.missing_materials].join("；")}</p>}
      {available && (plan.music_edit_available || editable.length > 0) && <details>
        <summary>调整本次出片</summary>
        <p className={styles.note}>调整随这次出片保存。勾选保留原景的段落仍显示主字幕，该段动效和绑定音效会关闭。</p>
        {plan.music_edit_available && <label>本次背景音乐
          <select value={selected.music} disabled={!!busy} onChange={event => change({ music: event.target.value as Controls["music"] })}>
            <option value="keep">沿用编排</option><option value="lower">降低 6 dB</option><option value="off">关闭背景音乐</option>
          </select>
        </label>}
        {editable.map(beat => <label key={beat.id}>
          <input type="checkbox" disabled={!!busy} checked={selected.segments.includes(beat.id)} onChange={event => change({
            segments: event.target.checked ? [...selected.segments, beat.id] : selected.segments.filter(id => id !== beat.id),
          })} />
          保留原景 · {beat.group_id} · {beat.text}
        </label>)}
      </details>}
      {available ? <>
        <p className={styles.note}>本次使用 {activeGroups.size} 种动效，共出现 {activeEffects.length} 次。{activeGroups.size < 5 && "请保留至少五种不同动效。"}</p>
        <button type="button" onClick={() => void render(plan, selected)} disabled={!!busy || activeGroups.size < 5}>{busy === plan.id ? "正在提交…" : "生成代理预览"}</button>
      </> : <p className={styles.note}>历史验证候选 · 待适配连续人物底片与组合动效</p>}
    </article>})}
    {error && <p role="alert" className={styles.error}>{error} <button type="button" onClick={() => setReload(n => n + 1)}>重新读取编排</button></p>}
  </section>;
}
