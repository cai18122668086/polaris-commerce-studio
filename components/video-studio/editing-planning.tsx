"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiClient } from "@/lib/api/client";
import { unwrapApiResponse } from "@/lib/api/request";
import type { components } from "@/lib/api/generated/openapi";
import { EditingProjectMaterials } from "./editing-project-materials";
import styles from "./editing-workspace.module.css";

type Job = components["schemas"]["EditingPlanningTaskResponse"];
type OverlayTemplate = components["schemas"]["EditingOverlayTemplate"];
type BaseTask = { id: string; status: string; created_at: string; artifacts: { role: string }[] };
const root = "/api/v1/video-studio/workspaces/{workspace_id}" as const;
const labels: Record<string, string> = { queued: "等待处理", reading_inputs: "核对原片与实际转录", building_request: "准备全库规划请求", planning: "理解重点与关系", storing: "保存候选", prepared: "请求已准备 · 未调用模型", completed: "规划候选已返回 · 待核对", failed: "规划未完成", cancelled: "已取消" };
const errors: Record<string, string> = { EDITING_PLAN_ALREADY_SUBMITTED: "模型提交结果待核对，不能自动再次计费。", EDITING_PREPARED_REQUEST_CHANGED: "准备记录的产物已变化，请先恢复或重新准备。", EDITING_PLAN_SOURCE_CHANGED: "原片或转录已变化，请恢复对应版本。", EDITING_CHOICES_CHANGED_REPLAN_REQUIRED: "项目选组备忘已更新，请重新准备后核对。", EDITING_PLAN_INPUT_CHANGED: "请求内容已变化，请重新准备后核对。", EDITING_PLAN_CONTRACT_INVALID: "响应未通过词点与原库字段合同检查，不能作为可用编排。" };

export function EditingPlanning({ workspaceId, projectId, tasks, onNativePlan }: {
  workspaceId: string; projectId: string; tasks: BaseTask[]; onNativePlan: () => void;
}) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [selected, setSelected] = useState("");
  const [materialIds, setMaterialIds] = useState<string[]>([]);
  const [templates, setTemplates] = useState<OverlayTemplate[]>([]);
  const [templateId, setTemplateId] = useState("");
  const [templateError, setTemplateError] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [loadError, setLoadError] = useState("");
  const [nativePlans, setNativePlans] = useState<Record<string, string>>({});
  const intent = useRef<{ key: string; id: string } | undefined>(undefined);
  const candidates = tasks.filter(task => task.status === "completed" && task.artifacts.some(a => a.role === "transcript"));
  const refresh = useCallback(async () => unwrapApiResponse(await apiClient.GET(`${root}/projects/{project_id}/editing-planning-tasks`, {
    params: { path: { workspace_id: workspaceId, project_id: projectId } }, signal: AbortSignal.timeout(12000),
  })), [workspaceId, projectId]);
  useEffect(() => {
    let live = true;
    const reload = () => { void refresh().then(rows => { if (live) { setJobs(rows); setLoadError(""); } }).catch(() => { if (live) setLoadError("暂时无法读取规划任务，请稍后重试。"); }); };
    reload(); const timer = setInterval(reload, 5000);
    return () => { live = false; clearInterval(timer); };
  }, [refresh]);
  useEffect(() => {
    const controller = new AbortController();
    void apiClient.GET(`${root}/editing-templates`, {
      params: { path: { workspace_id: workspaceId } },
      signal: AbortSignal.any([controller.signal, AbortSignal.timeout(12000)]),
    }).then(result => { if (!controller.signal.aborted) setTemplates(unwrapApiResponse(result)); })
      .catch(() => { if (!controller.signal.aborted) setTemplateError(true); });
    return () => controller.abort();
  }, [workspaceId]);
  const submit = async (mode: "prepare" | "generate", prepared?: Job) => {
    const taskId = prepared?.base_task_id || selected;
    if (!taskId || (mode === "prepare" && !templateId)) return;
    setBusy(true); setError("");
    try {
      const currentMaterials = mode === "prepare" ? [...materialIds].sort() : [];
      const selectedTemplate = mode === "prepare" ? templateId : undefined;
      const key = JSON.stringify([taskId, mode, prepared?.id, currentMaterials, selectedTemplate]);
      if (!intent.current || intent.current.key !== key) intent.current = { key, id: crypto.randomUUID() };
      unwrapApiResponse(await apiClient.POST(`${root}/editing-tasks/{task_id}/planning-tasks`, {
        params: { path: { workspace_id: workspaceId, task_id: taskId } }, signal: AbortSignal.timeout(12000),
        body: { request_id: intent.current.id, mode, template_id: selectedTemplate, ...(prepared ? { prepared_task_id: prepared.id } : {}), ...(currentMaterials.length ? { material_ids: currentMaterials } : {}) },
      }));
      intent.current = undefined; setJobs(await refresh());
    } catch (caught) { setError(caught instanceof Error ? caught.message : "提交暂未确认，再次点击会查询同一请求。"); }
    finally { setBusy(false); }
  };
  const action = async (job: Job, kind: "cancel" | "retry") => {
    setBusy(true); setError("");
    try {
      const params = { path: { workspace_id: workspaceId, task_id: job.id } };
      unwrapApiResponse(kind === "cancel"
        ? await apiClient.POST(`${root}/editing-planning-tasks/{task_id}/cancel`, { params, signal: AbortSignal.timeout(12000) })
        : await apiClient.POST(`${root}/editing-planning-tasks/{task_id}/retry`, { params, signal: AbortSignal.timeout(12000) }));
      setJobs(await refresh());
    } catch (caught) { setError(caught instanceof Error ? caught.message : "操作未确认，请刷新后查看。"); }
    finally { setBusy(false); }
  };
  const adopt = async (job: Job) => {
    setBusy(true); setError("");
    try {
      const plan = unwrapApiResponse(await apiClient.POST(`${root}/editing-planning-tasks/{task_id}/native-candidate`, {
        params: { path: { workspace_id: workspaceId, task_id: job.id } }, signal: AbortSignal.timeout(12000),
      }));
      setNativePlans(current => ({ ...current, [job.id]: plan.id }));
      onNativePlan();
    } catch (caught) { setError(caught instanceof Error ? caught.message : "原生编排未确认，可重试此操作。"); }
    finally { setBusy(false); }
  };
  return <section aria-label="语义规划任务">
    <p className={styles.note}>先用已有成片的实际转录准备完整请求，再生成重点与选组候选。准备不会重新配音、识别或调用模型。</p>
    <label>使用哪条成片的实际转录？<select aria-label="使用哪条成片的实际转录？" value={selected} onChange={event => setSelected(event.target.value)}><option value="">请选择已有转录</option>{candidates.map(task => <option key={task.id} value={task.id}>{new Date(task.created_at).toLocaleString("zh-CN")} · {task.id.slice(0, 8)}</option>)}</select></label>
    <fieldset className={styles.templatePicker}>
      <legend>选择组合模板</legend>
      <p className={styles.note}>人物原片持续播放。成片至少使用五种不同动效，优先十种以上。同一种动效可在不同词点重复使用。</p>
      <div className={styles.templateGrid}>{templates.map(template => <label key={template.id} className={styles.templateOption}>
        <span><input type="radio" name="editing-template" value={template.id} checked={templateId === template.id} disabled={busy} onChange={() => setTemplateId(template.id)} /> <b>{template.name}</b></span>
        <small>{template.slots.length} 种可选动效</small>
        <small>{template.slots.slice(0, 3).map(slot => slot.purpose).join(" · ")}</small>
      </label>)}</div>
      {templateError && <p role="alert">暂时无法读取组合模板，请刷新后重试。</p>}
    </fieldset>
    <EditingProjectMaterials workspaceId={workspaceId} projectId={projectId} selected={materialIds} onSelect={setMaterialIds} />
    <button type="button" disabled={busy || !selected || !templateId} onClick={() => void submit("prepare")}>准备语义请求（不调用模型）</button>
    {error && <p role="alert" className={styles.error}>{error}</p>}
    {loadError && <p role="alert" className={styles.error}>{loadError}</p>}
    <div className={styles.tasks}>{jobs.map(job => <article key={job.id} data-planning-job={job.id}>
      <div className={styles.taskHeading}><b>{labels[job.status === "running" ? job.stage : job.status] || "正在处理规划"}</b><time>{new Date(job.created_at).toLocaleString("zh-CN")}</time></div>
      <p className={styles.note}>模型：{job.model} · 网关：{job.gateway_host || "尚未固定"} · 转录版本 {job.base_transcript_sha256.slice(0, 12)}{job.text_status && ` · ${job.text_status === "user_corrected" ? "用户已校对文字，词点待验" : "转录文字待核对"}`}</p>
      {job.overlay_template && <p className={styles.note}>组合模板 · {job.overlay_template.name}</p>}
      {job.request_bytes !== null && <p>{job.catalog_group_count} 组原库 · 请求 {job.request_bytes.toLocaleString()} 字节 · 输入版本 {job.request_sha256?.slice(0, 12)}</p>}
      {job.status === "prepared" && <>
        <p className={styles.note}>尚未调用模型，没有规划结果。执行时最大输出 5000 token，输入另计，实际费用按腾力网关账单。</p>
        {job.artifacts.filter(a => a.role === "request").map(a => <a key={a.id} href={a.url} download>下载已准备请求</a>)}
        <button type="button" disabled={busy || !job.execution_available || jobs.some(j => j.prepared_task_id === job.id)} onClick={() => void submit("generate", job)}>生成重点与选组候选（付费）</button>
        {!job.execution_available && <p className={styles.note}>模型执行尚未开放，当前仅完成请求准备。</p>}
      </>}
      {job.semantic && job.semantic_origin === "tengli_gateway" && <><b>{job.semantic.audience_question}</b><ol>{job.semantic.argument_outline.map((line, i) => <li key={i}>{line}</li>)}</ol><ul>{job.semantic.beats.map(beat => <li key={beat.id}>{beat.group_id} · {beat.relation}<br />{job.aligned_spans?.find(span => span.beat_id === beat.id)?.text}<br />{beat.reason}</li>)}</ul><p className={styles.note}>语义与事实待核对。原生编排生成后可进入候选预览。</p>{[...(job.semantic.warnings ?? []), ...(job.semantic.missing_materials ?? [])].map((line, i) => <p key={i} className={styles.note}>{line}</p>)}</>}
      {job.status === "completed" && job.overlay_template && (nativePlans[job.id]
        ? <a href={`#editing-native-plan-${nativePlans[job.id]}`}>查看本次原生编排</a>
        : <button type="button" disabled={busy} onClick={() => void adopt(job)}>生成原生编排</button>)}
      {job.status === "failed" && <p role="alert" className={styles.error}>{errors[job.error_code || ""] || "本次规划未完成，请核对输入或服务配置。"}</p>}
      {job.call_state === "intent_saved" && <p className={styles.note}>请求已登记提交，结果未确认；不能自动重发付费请求。取消只能停止后续处理。</p>}
      {["queued", "running"].includes(job.status) && <button type="button" disabled={busy || job.cancel_requested} onClick={() => void action(job, "cancel")}>{job.cancel_requested ? "正在取消" : job.call_state === "not_submitted" ? "取消" : "取消后续处理"}</button>}
      {["failed", "cancelled"].includes(job.status) && job.call_state !== "intent_saved" && <button type="button" disabled={busy || (job.mode === "generate" && job.call_state === "not_submitted" && !job.execution_available)} onClick={() => void action(job, "retry")}>{job.call_state === "response_saved" ? "重新校验已保存响应" : "重试任务"}</button>}
    </article>)}</div>
  </section>;
}
