"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { minDistinctMotionGroups, preferredDistinctMotionGroups } from "@/features/video-studio/editing-density";
import { apiClient } from "@/lib/api/client";
import { unwrapApiResponse } from "@/lib/api/request";
import type { components } from "@/lib/api/generated/openapi";
import { EditingProjectMaterials } from "./editing-project-materials";
import styles from "./editing-workspace.module.css";

type Job = components["schemas"]["EditingPlanningTaskResponse"];
type PreviewTask = components["schemas"]["EditingTaskResponse"];
type OverlayTemplate = components["schemas"]["EditingOverlayTemplate"];
type BaseTask = Pick<PreviewTask, "id" | "status" | "created_at" | "artifacts" | "source_frame">;
export type CarrySelection = {
  projectId: string;
  sourceId: string;
  base: components["schemas"]["EditingPreviewBase"];
};
const root = "/api/v1/video-studio/workspaces/{workspace_id}" as const;
const maxPreviewBatch = 5;
const retiredTemplate = (job: Job) => job.overlay_template?.id === "fruit-introduction-v1";
const canRevalidate = (job: Job) => job.overlay_template?.id === "product-explainer-v1" || job.overlay_template?.id === "knowledge-talk-v1";
const belowMinimum = (job: Job) => (job.motion_counts?.distinct_groups ?? minDistinctMotionGroups) < minDistinctMotionGroups;
const pendingAutoPreview = (job: Job) => job.auto_preview && !job.preview_task_id && !job.auto_preview_error_code;
const canBatchPreview = (job: Job) => job.status === "completed" && job.overlay_template && !retiredTemplate(job) && !job.preview_task_id && !pendingAutoPreview(job) && !belowMinimum(job);
const autoPreviewErrors: Record<string, string> = {
  EDITING_PLAN_GROUPS_INSUFFICIENT: "候选少于五种不同动效，代理未提交。已保存本次候选。",
  EDITING_CHOICES_CHANGED_REPLAN_REQUIRED: "项目选组备忘已变化，代理未提交。已保存本次候选。",
  EDITING_PLANNING_PROVENANCE_CHANGED: "无法核对已保存的规划来源，代理未提交。",
  EDITING_PLANNING_RULES_CHANGED: "现行词点规则改变了候选，可重核已保存的响应后再生成代理。",
  EDITING_ORIGINAL_NATIVE_DEPENDENCY_REQUIRED: "候选使用的原库字体或模型无法核验，代理未提交。请打开候选查看对应段落。",
  EDITING_ORIGINAL_BROWSER_ASSETS_REQUIRED: "候选使用的原库底板或纹理无法核验，代理未提交。请打开候选查看对应段落。",
  EDITING_ORIGINAL_BROWSER_FONTS_REQUIRED: "候选使用的原库启动字体无法核验，代理未提交。请打开候选查看对应段落。",
};
const labels: Record<string, string> = { queued: "等待处理", reading_inputs: "核对原片与实际转录", building_request: "准备全库规划请求", planning: "理解重点与关系", storing: "保存候选", prepared: "请求已准备 · 未调用模型", completed: "规划候选已返回 · 待核对", failed: "规划未完成", cancelled: "已取消" };
const errors: Record<string, string> = {
  EDITING_TASK_STORAGE_UNAVAILABLE: "规划服务暂时无法写入工作目录。请在存储恢复后重试此任务。",
  EDITING_CONDITION_ANCHOR_INCOMPLETE: "候选中的动效文字遗漏了实录适用条件。请核对转录并保留完整前提。",
  EDITING_ROLE_ACTION_ANCHOR_INVALID: "角色场景的关门、交接或禁行切点没有对应实录词首。请选择对应的动作词或其他动效。",
  EDITING_NEGATION_ANCHOR_INCOMPLETE: "候选中的动效文字遗漏了实录的否定表达。请核对转录或使用保留完整否定的编排。",
  EDITING_QUANTITY_ANCHOR_INCOMPLETE: "候选中的动效文字截断了实录数量或单位。请核对转录，保留完整范围、比例或限制词。",
  EDITING_PARALLEL_ITEMS_INVALID: "并列动效的事项须各有独立实录词点，并分别绑定文字或素材。请核对编排。",
  EDITING_ORIENTATION_REVIEW_REQUIRED: "原生模板需要方形像素的 9:16 竖屏原片，请选择符合画幅的转录。",
  EDITING_PLAN_ALREADY_SUBMITTED: "模型提交结果待核对，不能自动再次计费。",
  EDITING_PREPARED_REQUEST_CHANGED: "准备记录的产物已变化，请先恢复或重新准备。",
  EDITING_PLAN_SOURCE_CHANGED: "原片或转录已变化，请恢复对应版本。",
  EDITING_CHOICES_CHANGED_REPLAN_REQUIRED: "项目选组备忘已更新，请重新准备后核对。",
  EDITING_PLAN_INPUT_CHANGED: "请求内容已变化，请重新准备后核对。",
  EDITING_TEMPLATE_GROUPS_INSUFFICIENT: "可选动效少于五种。请核对项目备忘、素材或模板后重新准备。",
  EDITING_TEMPLATE_DEPENDENCIES_CHANGED: "准备后有模板原件无法核验，本次模型请求未提交。请重新准备。",
  EDITING_PLAN_CONTRACT_INVALID: "响应未通过词点与原库字段合同检查，不能作为可用编排。",
};

export function EditingPlanning({ workspaceId, projectId, tasks, selected, onSelect, onNativePlan, onPreview, carryFrom, onClearCarry }: {
  workspaceId: string; projectId: string; tasks: BaseTask[]; selected: string; onSelect: (taskId: string) => void; onNativePlan: () => void;
  onPreview: (tasks: PreviewTask[]) => void;
  carryFrom?: CarrySelection;
  onClearCarry: () => void;
}) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [materialIds, setMaterialIds] = useState<string[]>([]);
  const [templates, setTemplates] = useState<OverlayTemplate[]>([]);
  const [templateId, setTemplateId] = useState("");
  const [templateError, setTemplateError] = useState(false);
  const [manualPreviewIds, setManualPreviewIds] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [loadError, setLoadError] = useState("");
  const [nativePlans, setNativePlans] = useState<Record<string, string>>({});
  const [batchSelection, setBatchSelection] = useState<string[]>([]);
  const [batchErrors, setBatchErrors] = useState<Record<string, string>>({});
  const [batchCount, setBatchCount] = useState(0);
  const intent = useRef<{ key: string; id: string } | undefined>(undefined);
  const candidates = tasks.filter(task => task.status === "completed" && task.source_frame?.supports_native_portrait !== false && task.artifacts.some(a => a.role === "transcript"));
  const selectedCandidate = candidates.some(task => task.id === selected) ? selected : "";
  const eligible = jobs.filter(canBatchPreview);
  const batchIds = batchSelection.filter(id => eligible.some(job => job.id === id));
  const showBatch = eligible.length >= 2 || batchIds.length > 0;
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
    const taskId = prepared?.base_task_id || selectedCandidate;
    if (!taskId || (mode === "prepare" && !templateId)) return;
    setBusy(true); setError("");
    try {
      const currentMaterials = mode === "prepare" ? [...materialIds].sort() : [];
      const selectedTemplate = mode === "prepare" ? templateId : undefined;
      const shouldPreview = Boolean(prepared?.auto_preview_available && !manualPreviewIds.includes(prepared.id));
      const key = JSON.stringify([taskId, mode, prepared?.id, currentMaterials, selectedTemplate, shouldPreview]);
      if (!intent.current || intent.current.key !== key) intent.current = { key, id: crypto.randomUUID() };
      unwrapApiResponse(await apiClient.POST(`${root}/editing-tasks/{task_id}/planning-tasks`, {
        params: { path: { workspace_id: workspaceId, task_id: taskId } }, signal: AbortSignal.timeout(12000),
        body: { request_id: intent.current.id, mode, template_id: selectedTemplate, auto_preview: shouldPreview, ...(prepared ? { prepared_task_id: prepared.id } : {}), ...(currentMaterials.length ? { material_ids: currentMaterials } : {}) },
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
  const adopt = async (job: Job, revalidate = false) => {
    setBusy(true); setError("");
    try {
      const plan = unwrapApiResponse(await apiClient.POST(`${root}/editing-planning-tasks/{task_id}/native-candidate`, {
        params: { path: { workspace_id: workspaceId, task_id: job.id }, query: { revalidate } }, signal: AbortSignal.timeout(12000),
      }));
      setNativePlans(current => ({ ...current, [job.id]: plan.id }));
      onNativePlan();
    } catch (caught) { setError(caught instanceof Error ? caught.message : "原生编排未确认，可重试此操作。"); }
    finally { setBusy(false); }
  };
  const linkPreviews = (linked: Map<string, PreviewTask>) => {
    const previews = [...linked.values()];
    if (previews.some(task => task.project_id !== projectId)) throw new Error("预览任务与当前项目不匹配。");
    setJobs(rows => rows.map(row => {
      const task = linked.get(row.id);
      return task ? { ...row, preview_task_id: task.id, native_render_state: "preview_requested" } : row;
    }));
    setBatchSelection(ids => ids.filter(id => !linked.has(id)));
    onPreview(previews);
  };
  const preview = async (job: Job) => {
    setBusy(true); setError("");
    try {
      const task = unwrapApiResponse(job.preview_task_id
        ? await apiClient.GET(`${root}/editing-tasks/{task_id}`, {
          params: { path: { workspace_id: workspaceId, task_id: job.preview_task_id } }, signal: AbortSignal.timeout(12000),
        })
        : await apiClient.POST(`${root}/editing-planning-tasks/{task_id}/preview`, {
          params: { path: { workspace_id: workspaceId, task_id: job.id } }, signal: AbortSignal.timeout(12000),
        }));
      linkPreviews(new Map([[job.id, task]]));
      setBatchErrors(current => ({ ...current, [job.id]: "" }));
    } catch (caught) { setError(caught instanceof Error ? caught.message : "预览提交未确认，再次点击会查询同一任务。"); }
    finally { setBusy(false); }
  };
  const carryPreview = async (job: Job) => {
    if (!carryFrom) return;
    setBusy(true); setError("");
    try {
      const task = unwrapApiResponse(await apiClient.POST(`${root}/editing-planning-tasks/{task_id}/revision-preview`, {
        params: { path: { workspace_id: workspaceId, task_id: job.id } },
        signal: AbortSignal.timeout(12000), body: carryFrom.base,
      }));
      onPreview([task]);
      onClearCarry();
      requestAnimationFrame(() => document.getElementById(`editing-task-${task.id}`)?.scrollIntoView({ block: "start" }));
    } catch (caught) { setError(caught instanceof Error ? caught.message : "继承调整暂未完成，原版仍可查看。"); }
    finally { setBusy(false); }
  };
  const batchPreview = async () => {
    setBusy(true); setError(""); setBatchCount(0); setBatchErrors({});
    try {
      const results = unwrapApiResponse(await apiClient.POST(`${root}/projects/{project_id}/editing-planning-preview-batch`, {
        params: { path: { workspace_id: workspaceId, project_id: projectId } },
        body: { planning_task_ids: batchIds }, signal: AbortSignal.timeout(60000),
      }));
      const linked = new Map<string, PreviewTask>();
      const failed: Record<string, string> = {};
      for (const result of results) {
        if (result.task) linked.set(result.planning_task_id, result.task);
        else failed[result.planning_task_id] = result.error_message || "此条预览未提交，请核对规划后重试。";
      }
      if (linked.size) linkPreviews(linked);
      setBatchCount(linked.size);
      setBatchErrors(failed);
    } catch (caught) { setError(caught instanceof Error ? caught.message : "批量提交暂未确认，请刷新核对后重试。"); }
    finally { setBusy(false); }
  };
  return <section aria-label="语义规划任务">
    <p className={styles.note}>使用实际口播的转录准备请求，再生成重点与选组候选。准备不会重新配音、识别或调用模型。</p>
    <label>使用哪条口播的实际转录？<select value={selectedCandidate} onChange={event => onSelect(event.target.value)}><option value="">请选择已有转录</option>{candidates.map(task => <option key={task.id} value={task.id}>{new Date(task.created_at).toLocaleString("zh-CN")} · {task.id.slice(0, 8)}</option>)}</select></label>
    <fieldset className={styles.templatePicker}>
      <legend>选择组合模板</legend>
      <p className={styles.note}>口播声音连续。画面可随模板叠加动效或切换整帧场景。成片至少使用五种不同动效，优先十种以上。同一种动效可在不同词点重复使用。</p>
      <div className={styles.templateGrid}>{templates.map(template => <label key={template.id} className={styles.templateOption}>
        <span><input type="radio" name="editing-template" value={template.id} checked={templateId === template.id} disabled={busy} onChange={() => setTemplateId(template.id)} /> <b>{template.name}</b></span>
        <small>{template.slots.length} 种可选动效</small>
        <small>{template.slots.slice(0, 3).map(slot => slot.purpose).join(" · ")}</small>
      </label>)}</div>
      {templateError && <p role="alert">暂时无法读取组合模板，请刷新后重试。</p>}
    </fieldset>
    <EditingProjectMaterials workspaceId={workspaceId} projectId={projectId} selected={materialIds} onSelect={setMaterialIds} />
    <button type="button" disabled={busy || !selectedCandidate || !templateId} onClick={() => void submit("prepare")}>准备语义请求（不调用模型）</button>
    {error && <p role="alert" className={styles.error}>{error}</p>}
    {loadError && <p role="alert" className={styles.error}>{loadError}</p>}
    {carryFrom && <div className={styles.correction}>
      <b>保留预览 {carryFrom.base.task_id.slice(0, 8)} 的人工调整</b>
      <p className={styles.note}>从同一原片的已完成规划中选择新版本。实录词段和槽位须兼容，原版可继续查看。</p>
      <button type="button" disabled={busy} onClick={onClearCarry}>取消继承</button>
    </div>}
    {showBatch && <div>
      <p className={styles.note}>可勾选 2 至 {maxPreviewBatch} 条规划生成代理。每条独立剪辑，高清逐条确认。</p>
      <button type="button" disabled={busy || batchIds.length < 2} onClick={() => void batchPreview()}>批量生成代理预览（{batchIds.length} 条）</button>
    </div>}
    {batchCount > 0 && <p role="status">已关联 {batchCount} 条代理预览任务。</p>}
    <div className={styles.tasks}>{jobs.map(job => {
      const available = job.available_template_group_count;
      const insufficient = available != null && available < minDistinctMotionGroups;
      const belowMinimumForPreview = belowMinimum(job);
      return <article key={job.id} data-planning-job={job.id}>
      <div className={styles.taskHeading}><b>{labels[job.status === "running" ? job.stage : job.status] || "正在处理规划"}</b><time>{new Date(job.created_at).toLocaleString("zh-CN")}</time></div>
      <p className={styles.note}>模型：{job.model} · 网关：{job.gateway_host || "尚未固定"} · 转录版本 {job.base_transcript_sha256.slice(0, 12)}{job.text_status && ` · ${job.text_status === "user_corrected" ? "用户已校对文字，词点待验" : "转录文字待核对"}`}</p>
      {job.overlay_template && <p className={styles.note}>组合模板 · {job.overlay_template.name}{retiredTemplate(job) && "（已下架）"}</p>}
      {showBatch && canBatchPreview(job) && <label className={styles.reviewCheck}>
        <input type="checkbox" checked={batchIds.includes(job.id)} disabled={busy || (!batchIds.includes(job.id) && batchIds.length >= maxPreviewBatch)} onChange={event => setBatchSelection(event.target.checked ? [...batchIds, job.id] : batchIds.filter(id => id !== job.id))} />加入批量预览
      </label>}
      {available != null && <p className={styles.note}>本次有 {available} 种可选动效。</p>}
      {available != null && !insufficient && available < preferredDistinctMotionGroups && <p className={styles.note}>本次可选种类低于优先目标 {preferredDistinctMotionGroups} 种。</p>}
      {job.motion_counts && <p className={styles.note}>
        候选选中 {job.motion_counts.distinct_groups} 种动效，共 {job.motion_counts.occurrences} 次。
        {belowMinimumForPreview ? "至少五种才可出片。" : job.motion_counts.distinct_groups < preferredDistinctMotionGroups && `低于优先目标 ${preferredDistinctMotionGroups} 种。`}
      </p>}
      {!!job.excluded_template_group_ids?.length && <p className={styles.note}>按项目备忘避用 · {job.excluded_template_group_ids.join("、")}</p>}
      {!!job.unavailable_template_group_ids?.length && <p className={styles.note}>当前运行条件未满足的动效 · {job.unavailable_template_group_ids.join("、")}</p>}
      {job.overlay_template?.id === "question-card-b-story-v1" && job.unavailable_template_group_ids?.includes("AH-S03") && <p className={styles.note}>问号 B 版需要原 Aa 研宋、Times New Roman Bold 和 Impact。各字体的状态可在原库目录查看。</p>}
      {job.unavailable_template_group_ids?.includes("CX-G05") && <p className={styles.note}>特写条堆叠需要原模板的活动底板、原字体和抠像模型、无内嵌字幕的原片及三张不同的本期配图。原件状态可在原库目录查看。</p>}
      {job.unavailable_template_group_ids?.some(id => ["CX-G08", "CX-G09", "CX-G10"].includes(id)) && <p className={styles.note}>透视板、材质词和圆形配图需要原字体、原抠像模型及无内嵌字幕的原片。材质词需原纹理，三个圆形槽需三张不同的本期配图。原件状态可在原库目录查看。</p>}
      {job.unavailable_template_group_ids?.some(id => id === "HY-A4" || id === "HY-A5") && <p className={styles.note}>原生人物标签和斜切标签需要无内嵌字幕的原片，以及当前工作区可用的 Hypit 运行环境。</p>}
      {job.unavailable_template_group_ids?.some(id => id === "HY-A2" || id === "HY-A3") && <p className={styles.note}>原生三图卡需要无内嵌字幕的原片，以及当前工作区可用的 Hypit 运行环境。斜卡还需要原字体和抠像模型。</p>}
      {job.unavailable_template_group_ids?.includes("HY-A6") && <p className={styles.note}>原生双行三卡需要无内嵌字幕的原片，以及当前工作区可用的 Hypit 运行环境。</p>}
      {job.unavailable_template_group_ids?.includes("HY-A7") && <p className={styles.note}>三项占比需要无内嵌字幕的原片、已校对文字和当前工作区可用的原生运行环境与字体。</p>}
      {job.unavailable_template_group_ids?.includes("YYP05") && <p className={styles.note}>双素材接力需要无内嵌字幕的原片，以及两段不同且足够长的本期补充视频。</p>}
      {job.overlay_template?.id === "azl-panels-v1" && !!job.unavailable_template_group_ids?.length && <p className={styles.note}>阿哲板式需要无内嵌字幕的原片。不同板式需要一至三份不同的本期图片或足够长的视频。</p>}
      {job.overlay_template?.id === "chenxi-broll-v1" && !!job.unavailable_template_group_ids?.length && <p className={styles.note}>晨曦实景需要无内嵌字幕的原片和足够长的本期补充视频。部分板式还需要一张纸纹底图。</p>}
      {job.overlay_template?.id === "yy-presenter-openings-v3" && !!job.unavailable_template_group_ids?.length && <p className={styles.note}>月云川开场需要无内嵌字幕的原片。部分画面需要本期背景图及实录数量词，撕纸组需要两张不同的背景图。</p>}
      {job.unavailable_template_group_ids?.includes("AH-S07") && <p className={styles.note}>年份动效需要实录说出四位年份，并能读取原组背衬字体。</p>}
      {job.unavailable_template_group_ids?.includes("Z-M11") && <p className={styles.note}>方格纸逐字说明需要无内嵌字幕的原片，以及可用的原抠像模型。</p>}
      {job.unavailable_template_group_ids?.some(id => id === "Z-M05" || id === "Z-M17") && <p className={styles.note}>描边章节和人物分身需要无内嵌字幕的原片，以及可用的原抠像模型。</p>}
      {job.overlay_template?.id === "material-cut-v1" && !!job.unavailable_template_group_ids?.length && <p className={styles.note}>素材接力需要无内嵌字幕的原片。实拍接力需要 1 张本期配图，手机画面需要 2 张，撕纸和表盘各需要 3 张。每组内的配图须不同。</p>}
      {job.overlay_template?.id === "media-panels-v1" && !!job.unavailable_template_group_ids?.length && <p className={styles.note}>四图板和图例各需要 4 张不同的本期图片。三路并置需要 2 份不同的本期补充素材，补充视频须覆盖所选口播段。请使用无内嵌字幕的原片。</p>}
      {job.overlay_template?.id === "unified-handoff-v1" && !!job.unavailable_template_group_ids?.length && <p className={styles.note}>闪亮转场和评论框需要无内嵌字幕的原片及一张本期配图。评论框还需要实录说出评论邀请和指定关键词。</p>}
      {job.project_image_requirements?.map(requirement => requirement.group_id === "CX-G06" ? <p key={requirement.group_id} className={styles.note}>
        CX-G06 · 水果清单需要三张不同的水果配图和一张至少 1006×814 的独立头图。本期已选 {requirement.selected_distinct_images} 张不同图片，其中 {requirement.native_image_slot_ids?.["/presenter"]?.length ?? 0} 张符合头图尺寸。
        {job.unavailable_template_group_ids?.includes(requirement.group_id)
          ? " 当前实录主题或原库依赖尚不满足，编排可选同模板其他动效。"
          : (requirement.selected_distinct_images < requirement.required_distinct_images || !requirement.native_image_slot_ids?.["/presenter"]?.length)
          && " 补齐图片后可重新准备。"}
      </p> : requirement.group_id === "W-R17" ? <p key={requirement.group_id} className={styles.note}>
        W-R17 · 两个问号需要两张不同的 540×960 透明 PNG。本期已选 {requirement.selected_distinct_images} 张符合要求的图片。
        {requirement.selected_distinct_images < requirement.required_distinct_images && " 补齐道具后可重新准备。"}
      </p> : requirement.group_id === "W-R09" ? <p key={requirement.group_id} className={styles.note}>
        W-R09 · 需要一张 540×960 不透明承接图和七张按槽尺寸上传的透明 PNG。当前已配齐 {Object.values(requirement.native_image_slot_ids ?? {}).filter(ids => ids.length > 0).length} / {requirement.required_distinct_images} 个素材位。
        剪影尺寸依次为 210×240、260×240、205×400、120×310、120×320、305×425、145×410。
        {job.unavailable_template_group_ids?.includes("W-R09") && " 补齐图片并使用无内嵌字幕的原片后，可重新准备。"}
      </p> : requirement.group_id === "W-R04" ? <p key={requirement.group_id} className={styles.note}>
        W-R04 · 需要顶部图 365×240、透明人物 PNG 至少 275×345、左图 270×280、记录图 390×240，以及七张透明装饰剪影。当前已配齐 {Object.values(requirement.native_image_slot_ids ?? {}).filter(ids => ids.length > 0).length} / {requirement.required_distinct_images} 个素材位。
        {job.unavailable_template_group_ids?.includes("W-R04") && " 补齐本期素材并使用无内嵌字幕的原片后，可重新准备。"}
      </p> : requirement.group_id === "W-R01" ? <p key={requirement.group_id} className={styles.note}>
        W-R01 · 三张反馈图须各有核对记录和对应的实录短标签，当前匹配 {requirement.selected_distinct_images} 张不同图片。
        {job.unavailable_template_group_ids?.includes("W-R01") && " 本组还需要实录英文短词、无内嵌字幕的原片及可用的原抠像模型。编排可以选同模板其他动效。"}
      </p> : requirement.group_id === "W-R15" ? <p key={requirement.group_id} className={styles.note}>
        W-R15 · 需要 16 张分别对应流程各场景的本期插画，当前已选 {requirement.selected_distinct_images} 张不同图片。
        {requirement.role_action_word_matches && !Object.keys(requirement.role_action_word_matches).length
          ? " 本次实录未找到按顺序可锚定的关门、交接和禁行动作，编排可使用同模板的其他动效。"
          : job.unavailable_template_group_ids?.includes("W-R15") && " 补齐素材并使用无内嵌字幕的原片后，可重新准备。"}
      </p> : requirement.native_image_slot_ids ? <p key={requirement.group_id} className={styles.note}>
        {requirement.group_id} · 本期线描素材需要不透明过渡图、透明线描图及六列四行的透明手势帧图。
        {Object.values(requirement.native_image_slot_ids).every(ids => ids.length > 0)
          ? " 三类素材均有可选原件。"
          : " 本次编排跳过线描场景，仍可使用同模板的其他动效。补图后可重新准备。"}
      </p> : <p key={requirement.group_id} className={styles.note}>
        {requirement.group_id} · 本期已选 {requirement.selected_distinct_images} 张不同图片，图卡需要 {requirement.required_distinct_images} 张。
        {requirement.transparent_image_ids && (" 其中可用于右上透明图位的图片有 " + requirement.transparent_image_ids.length + " 张。")}
        {(requirement.selected_distinct_images < requirement.required_distinct_images || requirement.transparent_image_ids?.length === 0) && " 本次编排跳过该图卡，仍可使用同模板的其他动效。补图后可重新准备。"}
      </p>)}
      {job.request_bytes !== null && <p>{job.catalog_group_count} 组原库 · 请求 {job.request_bytes.toLocaleString()} 字节 · 输入版本 {job.request_sha256?.slice(0, 12)}</p>}
      {job.status === "prepared" && <>
        <p className={styles.note}>尚未调用模型，没有规划结果。执行时最大输出 5000 token，输入另计，实际费用按腾力网关账单。</p>
        {job.artifacts.filter(a => a.role === "request").map(a => <a key={a.id} href={a.url} download>下载已准备请求</a>)}
        {!retiredTemplate(job) && <>
          {job.auto_preview_available && <label>
            <input type="checkbox" checked={!manualPreviewIds.includes(job.id)} disabled={busy || jobs.some(j => j.prepared_task_id === job.id)} onChange={event => {
              const checked = event.target.checked;
              setManualPreviewIds(ids => checked ? ids.filter(id => id !== job.id) : [...ids, job.id]);
            }} />
            候选通过后自动生成代理预览
          </label>}
          <button type="button" disabled={busy || insufficient || !job.execution_available || jobs.some(j => j.prepared_task_id === job.id)} onClick={() => void submit("generate", job)}>生成重点与选组候选（付费）</button>
          {insufficient && <p className={styles.note}>可选动效少于五种，请核对项目备忘、素材或更换模板后重新准备。</p>}
          {!job.execution_available && <p className={styles.note}>模型执行尚未开放，当前仅完成请求准备。</p>}
        </>}
      </>}
      {job.semantic && job.semantic_origin === "tengli_gateway" && <><b>{job.semantic.audience_question}</b><ol>{job.semantic.argument_outline.map((line, i) => <li key={i}>{line}</li>)}</ol><ul>{job.semantic.beats.map(beat => <li key={beat.id}>
        {beat.group_id} · {beat.relation}<br />{job.aligned_spans?.find(span => span.beat_id === beat.id)?.text}<br />{beat.reason}
        {beat.translation_gloss && <p className={styles.note}>英文短译待核对 · {beat.translation_gloss.before} → {beat.translation_gloss.after}</p>}
      </li>)}</ul><p className={styles.note}>{belowMinimumForPreview ? "可先核对候选语义和事实。" : "语义与事实待核对。可先按默认编排生成代理，也可保存编排后调整。"}</p>{[...(job.semantic.warnings ?? []), ...(job.semantic.missing_materials ?? [])].map((line, i) => <p key={i} className={styles.note}>{line}</p>)}</>}
      {job.status === "completed" && job.overlay_template && <>
        {carryFrom?.sourceId === job.source_id && !retiredTemplate(job) && !belowMinimumForPreview && <button type="button" disabled={busy} onClick={() => void carryPreview(job)}>保留调整并按此规划生成代理</button>}
        {batchErrors[job.id] && <p role="alert" className={styles.error}>{batchErrors[job.id]}</p>}
        {pendingAutoPreview(job) && <p role="status" className={styles.note}>候选已保存，正在提交代理预览。</p>}
        {job.auto_preview_error_code && <p role="alert" className={styles.error}>{autoPreviewErrors[job.auto_preview_error_code] || "自动代理未提交。已保存本次候选，可用同一份规划再次提交代理。"}</p>}
        {job.preview_task_id && tasks.some(task => task.id === job.preview_task_id)
          ? <a href={`#editing-task-${job.preview_task_id}`}>查看本次代理预览任务</a>
          : (job.preview_task_id || (!retiredTemplate(job) && !pendingAutoPreview(job))) && <button type="button" disabled={busy || (!job.preview_task_id && belowMinimumForPreview)} onClick={() => void preview(job)}>{job.preview_task_id ? "读取本次代理预览任务" : "按本次规划生成代理预览"}</button>}
        {nativePlans[job.id]
          ? <a href={`#editing-native-plan-${nativePlans[job.id]}`}>查看本次原生编排</a>
          : !retiredTemplate(job) && <button type="button" disabled={busy || belowMinimumForPreview} onClick={() => void adopt(job)}>保存编排后调整</button>}
        {canRevalidate(job) && <button type="button" disabled={busy} onClick={() => void adopt(job, true)}>按现行规则重核已保存响应</button>}
      </>}
      {job.status === "failed" && <p role="alert" className={styles.error}>{errors[job.error_code || ""] || "本次规划未完成，请核对输入或服务配置。"}</p>}
      {job.call_state === "intent_saved" && <p className={styles.note}>请求已登记提交，结果未确认；不能自动重发付费请求。取消只能停止后续处理。</p>}
      {["queued", "running"].includes(job.status) && <button type="button" disabled={busy || job.cancel_requested} onClick={() => void action(job, "cancel")}>{job.cancel_requested ? "正在取消" : job.call_state === "not_submitted" ? "取消" : "取消后续处理"}</button>}
      {["failed", "cancelled"].includes(job.status) && !retiredTemplate(job) && job.call_state !== "intent_saved" && <button type="button" disabled={busy || (job.mode === "generate" && job.call_state === "not_submitted" && !job.execution_available)} onClick={() => void action(job, "retry")}>{job.call_state === "response_saved" ? "重新校验已保存响应" : "重试任务"}</button>}
      </article>;
    })}</div>
  </section>;
}
