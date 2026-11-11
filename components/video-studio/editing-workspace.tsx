"use client";

import { UserRound, PackageOpen } from "lucide-react";
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { preferredDistinctMotionGroups } from "@/features/video-studio/editing-density";
import { projectApi, type VideoVersion } from "@/features/video-studio/projects";
import { ApiError } from "@/lib/api/api-error";
import { apiClient } from "@/lib/api/client";
import { unwrapApiResponse } from "@/lib/api/request";
import type { GenerationJob } from "@/features/video-studio/library";
import type { components } from "@/lib/api/generated/openapi";
import { TranscriptEditor } from "./transcript-editor";
import { EditingFilmReview } from "./editing-film-review";
import { EditingSoundReview } from "./editing-sound-review";
import { EditingLibrary } from "./editing-library";
import { EditingNativePlans, type EditingRevisionSelection } from "./editing-native-plans";
import { EditingPlanning, type CarrySelection, type EditingPrimaryAction, type EditingPrimaryState } from "./editing-planning";
import { WritingVersionSources } from "./writing-version-sources";
import styles from "./editing-workspace.module.css";
import flow from "./editing-flow.module.css";
import { EditingTemplateGallery, type TemplateCard } from "./editing-template-gallery";

type EditingTask = components["schemas"]["EditingTaskResponse"];
type TaskLinkError = { id: string; message: string };
const root = "/api/v1/video-studio/workspaces/{workspace_id}" as const;
const taskHash = /^#editing-task-([0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12})$/i;
function subscribeToHash(listener: () => void) {
  window.addEventListener("hashchange", listener);
  return () => window.removeEventListener("hashchange", listener);
}
const readTaskHash = () => taskHash.exec(window.location.hash)?.[1].toLowerCase();
const stageLabel: Record<string, string> = { queued: "等待剪辑", preparing: "准备原片", transcribing: "识别实际口播", aligning: "按校对文字重新对齐", compiling: "编排画面与字幕", rendering: "生成视频", validating: "检查成片", building_preview: "生成代理预览", storing: "保存产物", transcript_ready: "口播转录已就绪", preview_ready: "代理预览已就绪", completed: "成片已生成" };
const errorLabel: Record<string, string> = {
  EDITING_UPLOAD_SCRIPT_CHANGED: "这条原片的参考确认稿无法核对，请重新选择确认稿并上传。",
  EDITING_HYPIT_INTERNAL_ONLY: "Hypit 原生出片仅在已配置的内部联调工作区开放。",
  EDITING_HYPIT_RUNTIME_UNAVAILABLE: "原 Hypit 运行环境未通过预检，请在环境恢复后重试。",
  EDITING_LABEL_CARD_CAPTION_LANE_REQUIRED: "这段主字幕与原生文字卡的读区冲突。请调整该段动效或字幕排版。",
  EDITING_ORIGINAL_NATIVE_DEPENDENCY_REQUIRED: "所选动效的原库字体或模型无法核验，请在原库目录核对后重试。",
  EDITING_TASK_STORAGE_UNAVAILABLE: "剪辑服务暂时无法写入工作目录。请在存储恢复后重试此任务。",
  EDITING_PREVIEW_REPAIR_MASTER_CHANGED: "恢复代理时无法核验高清母版。请从原编排重新生成预览。",
  EDITING_SOURCE_AUDIO_HEAD_REVIEW_REQUIRED: "画面开始前已有可听的原声，暂时无法安全接入。请核对原片开头的音画。",
  EDITING_MEASURE_SOURCE_AUDIO_CLOCK_FAILED: "无法读取原片口播的实际起点，请检查原片或联系管理员。",
  EDITING_SOUND_OUTPUT_INVALID: "成片声音与原始口播或已选音效、背景乐不一致。请重试剪辑后复核。",
  EDITING_DECODE_SOUND_CHECK_FAILED: "暂时无法核对成片声音。请重试剪辑。",
  EDITING_CONDITION_ANCHOR_INCOMPLETE: "本次动效文字遗漏了实录适用条件。请核对原转录和动效强调词。",
  EDITING_NEGATION_ANCHOR_INCOMPLETE: "本次动效文字遗漏了实录的否定表达。请核对原转录和动效强调词。",
  EDITING_PARALLEL_ITEMS_INVALID: "并列动效的事项重复使用实录词点或缺少原生绑定。请返回编排核对。",
  EDITING_QUANTITY_ANCHOR_INCOMPLETE: "本次动效文字截断了实录数量或单位。请核对原转录和动效强调词。",
  EDITING_ORIENTATION_REVIEW_REQUIRED: "原生模板需要方形像素的 9:16 竖屏原片。请选择符合画幅的原片。",
  EDITING_SUBTITLE_PIXEL_ASPECT_UNSUPPORTED: "基础字幕片需要方形像素。请先将原片转换为方形像素视频。",
  EDITING_VIDEO_FRAME_CLOCK_INVALID: "无法核对原片的显示时钟，请更换原片或联系管理员。",
  EDITING_MATERIAL_FRAME_CLOCK_INVALID: "无法核对补充视频的显示时钟，请检查素材或联系管理员。",
  EDITING_MEASURE_VIDEO_FRAME_CLOCK_FAILED: "无法读取原片的显示时间，请检查视频文件。",
  EDITING_NORMALIZE_VIDEO_FRAME_CLOCK_FAILED: "原片的变帧率取帧轨未能生成，请联系管理员。",
  EDITING_GENERATION_SCRIPT_CHANGED: "这条原口播的确认稿无法核对，请检查原生成任务。", EDITING_IMAGE_EDIT_INVALID: "这次选择的配图无法用于原图槽，请核对图片是否重复及透明图要求。", EDITING_MATERIAL_CHANGED: "配图原件已缺失或变化，请回到本期素材核对。", EDITING_HIGHLIGHT_INVALID: "这次选择的实录短语无法用于原动效，请返回编排重新选择。", EDITING_NO_SPEECH_RECOGNIZED: "没有识别到清晰口播，请检查原片声音。", EDITING_SOURCE_CHANGED: "原片已变化，请重新选择视频。", EDITING_CLOCK_REVIEW_REQUIRED: "原片音画起点需要校正，请更换原片或联系管理员。", EDITING_SOURCE_AUDIO_TAIL_REVIEW_REQUIRED: "请核对原片末尾的音画。画面结束后仍有声音，或音画时长差超出自动处理范围。", EDITING_ROTATION_REVIEW_REQUIRED: "此视频的旋转信息需要校正，请联系管理员。", EDITING_ORIGINAL_BROWSER_ASSETS_REQUIRED: "所选动效缺少会进入画面的原库图片，请联系管理员补齐原件。", EDITING_ORIGINAL_BROWSER_FONTS_REQUIRED: "所选动效需要原库启动字体，请在原库目录核对缺件。", EDITING_NATIVE_INPUTS_REQUIRED: "当前编排所需的原生参数或素材尚未备齐，请先补全编排。", EDITING_PLAN_SOURCE_CHANGED: "编排绑定的原片或转录已变化，请恢复原产物或保存新编排。", EDITING_NATIVE_PLAN_NOT_FOUND: "编排暂不可用，请联系管理员核对版本与运行配置。", EDITING_CAPTION_CAPACITY_REVIEW_REQUIRED: "当前识别词组超出字幕容量，请核对文字或联系管理员调整排版。", EDITING_CAPTION_DICTIONARY_MISSING: "剪辑服务缺少中文分词依赖，请联系管理员。", EDITING_CAPTION_DICTIONARY_CHANGED: "剪辑分词词典版本不匹配，请联系管理员核对。", EDITING_CAPTION_FONT_MISSING: "剪辑服务缺少已选定的原字幕字体，请联系管理员。", EDITING_CAPTION_FONT_CHANGED: "字幕字体与原库记录不一致，请联系管理员核对。", EDITING_CAPTION_LAYOUT_MISMATCH: "字幕换行与原生检查不一致，请先核对编排。" };

export function EditingWorkspace({ workspaceId, projectId, saved, jobs, compact = false }: { workspaceId: string; projectId: string; saved: boolean; jobs: GenerationJob[]; compact?: boolean }) {
  const [tasks, setTasks] = useState<EditingTask[]>([]);
  const [selected, setSelected] = useState("");
  const [file, setFile] = useState<File>();
  const [sourcePreview, setSourcePreview] = useState("");
  const [referenceVersion, setReferenceVersion] = useState("");
  const [confirmedVersions, setConfirmedVersions] = useState<VideoVersion[] | "unavailable">();
  const [subtitles, setSubtitles] = useState<"none" | "present" | "unknown">("unknown");
  const [busy, setBusy] = useState(false);
  const sourcePicker = useRef<HTMLSelectElement>(null);
  const [error, setError] = useState("");
  const [loadError, setLoadError] = useState("");
  const [previewFailures, setPreviewFailures] = useState<string[]>([]);
  const focusedTaskId = useSyncExternalStore(subscribeToHash, readTaskHash, () => undefined);
  const [taskLinkError, setTaskLinkError] = useState<TaskLinkError>();
  const revealedTaskId = useRef<string | undefined>(undefined);
  const [correctionTask, setCorrectionTask] = useState("");
  const [libraryOpened, setLibraryOpened] = useState(false);
  const [nativeOpened, setNativeOpened] = useState(false);
  const [showTaskHistory, setShowTaskHistory] = useState(false);
  const [template, setTemplate] = useState<TemplateCard>();
  const primaryAction = useRef<EditingPrimaryAction>(null);
  const [primaryState, setPrimaryState] = useState<EditingPrimaryState>();
  const [continueAfterRecognition, setContinueAfterRecognition] = useState(false);
  const [planningTask, setPlanningTask] = useState("");
  const nativePanel = useRef<HTMLDetailsElement>(null);
  const [plansVersion, setPlansVersion] = useState(0);
  const [revisionSelection, setRevisionSelection] = useState<EditingRevisionSelection>();
  const [carrySelection, setCarrySelection] = useState<CarrySelection>();
  const pending = useRef<{ key: string; requestId: string } | undefined>(undefined);
  const upload = useRef<{ workspaceId: string; projectId: string; file: File; versionId: string; requestId: string; sourceId?: string } | undefined>(undefined);
  const candidates = jobs.filter(job => job.project_id === projectId && job.kind === "lipsync" && job.status === "completed");
  const selectedGeneration = candidates.find(job => job.id === selected);
  useEffect(() => {
    if (!file) { setSourcePreview(""); return; }
    const url = URL.createObjectURL(file);
    setSourcePreview(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);
  const options = useCallback(() => ({ params: { path: { workspace_id: workspaceId } }, signal: AbortSignal.timeout(12000) }), [workspaceId]);
  const [linkedPreviews, setLinkedPreviews] = useState<{ projectId: string; ids: string[] }>();
  useEffect(() => {
    if (!saved || !projectId || selected !== "upload") return;
    let live = true;
    const list = async () => {
      const api = projectApi(workspaceId);
      const versions = new Map<string, VideoVersion>();
      try {
        for (let offset = 0; live; offset += 100) {
          const page = await api.versions(projectId, "confirmed", offset);
          for (const version of page) versions.set(version.id, version);
          if (page.length < 100) break;
        }
        if (live) setConfirmedVersions([...versions.values()]);
      } catch {
        if (live) setConfirmedVersions("unavailable");
      }
    };
    void list();
    return () => { live = false; };
  }, [projectId, saved, selected, workspaceId]);
  const reload = useCallback(async () => {
    const result = await apiClient.GET(`${root}/editing-tasks`, { ...options(), params: { path: { workspace_id: workspaceId }, query: { project_id: projectId } } });
    const rows = unwrapApiResponse(result);
    const targets = new Set(linkedPreviews?.projectId === projectId ? linkedPreviews.ids : []);
    if (focusedTaskId) targets.add(focusedTaskId);
    const missing = [...targets].filter(id => !rows.some(row => row.id === id));
    const details = await Promise.allSettled(missing.map(async id => unwrapApiResponse(await apiClient.GET(`${root}/editing-tasks/{task_id}`, {
      ...options(), params: { path: { workspace_id: workspaceId, task_id: id }, query: { project_id: projectId } },
    }))));
    const linked = details.flatMap(detail => detail.status === "fulfilled" && detail.value.project_id === projectId ? [detail.value] : []);
    const focused = focusedTaskId && details[missing.indexOf(focusedTaskId)];
    let linkError: TaskLinkError | undefined;
    if (focusedTaskId && focused && !linked.some(task => task.id === focusedTaskId)) {
      const reason = focused.status === "rejected" ? focused.reason : undefined;
      linkError = { id: focusedTaskId, message: focused.status === "fulfilled" || (reason instanceof ApiError && reason.status === 404)
        ? "在当前项目中找不到这条剪辑任务。"
        : "暂时无法打开指定剪辑任务，稍后将重试。" };
    }
    return { rows: [...linked, ...rows], linkError };
  }, [workspaceId, projectId, options, linkedPreviews, focusedTaskId]);
  const applyTasks = useCallback(({ rows, linkError }: Awaited<ReturnType<typeof reload>>) => {
    setTasks(rows);
    setTaskLinkError(linkError);
    setLoadError("");
  }, []);
  useEffect(() => {
    if (!saved || !projectId) return;
    let live = true;
    let timer: number | undefined;
    const update = async () => {
      try {
        const result = await reload();
        if (live) applyTasks(result);
      } catch { if (live) setLoadError("暂时无法读取剪辑任务，请稍后重试。"); }
      finally { if (live) timer = window.setTimeout(() => void update(), 5000); }
    };
    void update();
    return () => { live = false; window.clearTimeout(timer); };
  }, [applyTasks, projectId, reload, saved]);
  const focusedTaskReady = tasks.some(task => task.id === focusedTaskId);
  useEffect(() => {
    if (!focusedTaskId) { revealedTaskId.current = undefined; return; }
    if (!focusedTaskReady || revealedTaskId.current === focusedTaskId) return;
    const card = document.getElementById(`editing-task-${focusedTaskId}`);
    if (!card) return;
    revealedTaskId.current = focusedTaskId;
    card.focus({ preventScroll: true });
    card.scrollIntoView({ block: "start", behavior: "instant" });
  }, [focusedTaskId, focusedTaskReady]);
  const submit = async (mode: "transcript" | "subtitles") => {
    setBusy(true); setError("");
    let uploadPending = false;
    try {
      let sourceId: string | undefined;
      if (selected === "upload" && file) {
        if (upload.current?.file !== file || upload.current.projectId !== projectId || upload.current.workspaceId !== workspaceId || upload.current.versionId !== referenceVersion) {
          upload.current = { workspaceId, projectId, file, versionId: referenceVersion, requestId: crypto.randomUUID() };
        }
        const original = upload.current;
        if (!original.sourceId) {
          uploadPending = true;
          const form = new FormData();
          form.append("project_id", projectId);
          form.append("request_id", original.requestId);
          if (original.versionId) form.append("confirmed_version_id", original.versionId);
          form.append("file", file);
          const uploaded = unwrapApiResponse(await apiClient.POST(`${root}/editing-sources`, {
            ...options(), signal: AbortSignal.timeout(600000), body: {} as never, bodySerializer: () => form,
          }));
          original.sourceId = uploaded.id;
          uploadPending = false;
        }
        sourceId = original.sourceId;
      }
      const key = JSON.stringify([workspaceId, projectId, sourceId ?? selected, subtitles, mode]);
      if (!pending.current || pending.current.key !== key) pending.current = { key, requestId: crypto.randomUUID() };
      const body = { request_id: pending.current.requestId, ...(sourceId ? { source_id: sourceId } : { generation_task_id: selected }), options: { mode, source_subtitles: subtitles, language: "zh" as const, caption_font_id: "font-d1961be1161ea1be" as const } };
      const task = unwrapApiResponse(await apiClient.POST(`${root}/editing-tasks`, { ...options(), body }));
      if (mode === "transcript") setPlanningTask(task.id);
      pending.current = undefined;
      setTasks(rows => [task, ...rows.filter(row => row.id !== task.id)]);
    } catch (caught) {
      setError(caught instanceof ApiError && !caught.retryable ? caught.message : uploadPending
        ? "原片上传结果暂未确认，再次点击会继续同一次上传。"
        : "剪辑提交暂未确认，再次点击会查询同一请求。");
    }
    finally { setBusy(false); }
  };
  const action = async (task: EditingTask, kind: "cancel" | "retry") => {
    setBusy(true); setError("");
    try {
      const opts = { ...options(), params: { path: { workspace_id: workspaceId, task_id: task.id } } };
      const result = kind === "cancel" ? await apiClient.POST(`${root}/editing-tasks/{task_id}/cancel`, opts) : await apiClient.POST(`${root}/editing-tasks/{task_id}/retry`, opts);
      unwrapApiResponse(result); applyTasks(await reload());
    } catch { setError("操作暂未确认，请刷新任务后重试。"); }
    finally { setBusy(false); }
  };
  const markPreviewFailure = (id: string) => setPreviewFailures(ids => ids.includes(id) ? ids : [...ids, id]);
  const previewAction = async (task: EditingTask, preview: components["schemas"]["EditingArtifactResponse"], action: "confirm" | "repair") => {
    setBusy(true); setError("");
    try {
      const endpoint = action === "repair"
        ? `${root}/editing-tasks/{task_id}/repair-preview` as const
        : `${root}/editing-tasks/{task_id}/confirm-export` as const;
      unwrapApiResponse(await apiClient.POST(endpoint, {
        ...options(), params: { path: { workspace_id: workspaceId, task_id: task.id } },
        body: { preview_artifact_id: preview.id, preview_sha256: preview.sha256 },
      }));
      applyTasks(await reload());
    } catch (caught) {
      if (action === "confirm" && caught instanceof ApiError && caught.code === "EDITING_EXPORT_CHANGED") markPreviewFailure(preview.id);
      setError(caught instanceof Error ? caught.message : "代理操作暂未完成，请刷新后重试。");
    }
    finally { setBusy(false); }
  };
  const canSubmit = saved && selected && subtitles !== "unknown" && (selected !== "upload" || file);
  const openPlanning = () => {
    document.getElementById("editing-arrange")?.scrollIntoView({ block: "start" });
  };
  const planFromTranscript = (taskId: string) => {
    setPlanningTask(taskId);
    openPlanning();
  };
  const revise = (selection: EditingRevisionSelection) => {
    setRevisionSelection(selection);
    setNativeOpened(true);
    if (nativePanel.current) nativePanel.current.open = true;
    (document.getElementById(`editing-native-plan-${selection.planId}`) ?? document.getElementById("editing-native-plans"))?.scrollIntoView({ block: "start" });
  };
  const transcriptReady = tasks.some(task => task.id === planningTask && task.status === "completed" && task.artifacts.some(a => a.role === "transcript"));
  const recognizing = tasks.some(task => task.id === planningTask && ["queued", "running"].includes(task.status));
  useEffect(() => {
    if (continueAfterRecognition && transcriptReady && primaryState?.phase === "prepare" && !primaryState.disabled) {
      setContinueAfterRecognition(false);
      primaryAction.current?.run();
    }
  }, [continueAfterRecognition, transcriptReady, primaryState]);
  const begin = () => {
    if (!transcriptReady) { setContinueAfterRecognition(true); void submit("transcript"); }
    else primaryAction.current?.run();
  };
  return <section className={`${styles.panel} ${flow.workbench} ${compact ? flow.compact : ""}`} aria-label="口播剪辑">
    <EditingTemplateGallery key={`gallery:${workspaceId}:${projectId}`} workspaceId={workspaceId} projectId={saved ? projectId : ""} selected={template?.id || ""} onRestore={setTemplate} sampleRevision={tasks.flatMap(task => task.artifacts.filter(a => a.role === "final").map(a => a.sha256)).join(",")} onSelect={setTemplate} />
    <section id="editing-source" className={`${flow.step} ${flow.source}`} aria-label="准备口播"><div className={flow.sourceHeading}><h2>口播视频</h2><label className={flow.uploadButton}>手动上传视频<input aria-label="上传口播视频" type="file" accept="video/mp4,video/quicktime,video/webm" onChange={event => { setSelected("upload"); setFile(event.target.files?.[0]); setPlanningTask(""); setReferenceVersion(""); setSubtitles("unknown"); }} /></label></div>
    {!sourcePreview && !selectedGeneration && <button type="button" className={flow.dropzone} onClick={() => { sourcePicker.current?.focus(); sourcePicker.current?.showPicker?.(); }}><UserRound size={36} strokeWidth={1.5} /><b>选择口播视频</b><small>我的视频 · 或手动上传</small></button>}

    {!saved && <p role="status">请先保存当前项目，再开始剪辑。</p>}
    <label>选择原片<select ref={sourcePicker} aria-label="选择原片" value={selected} onChange={event => { setSelected(event.target.value); setFile(undefined); setReferenceVersion(""); setPlanningTask(""); setSubtitles("unknown"); }}><option value="">请选择已完成的口播</option>{candidates.map(job => <option key={job.id} value={job.id}>{job.snapshot?.draft.name || "口播视频"} · {new Date(job.created_at).toLocaleString("zh-CN")}{job.confirmed_version_id && (" · 确认稿 " + job.confirmed_version_id.slice(0, 8))}</option>)}<option value="upload">上传真人口播或已有视频</option></select></label>
    {selectedGeneration?.video_url && <video src={selectedGeneration.video_url} controls playsInline preload="metadata" aria-label="已生成口播原片预览" style={{ width: "100%", maxWidth: 280, maxHeight: 400 }} />}
    {selected === "upload" && <>

      {sourcePreview && <video src={sourcePreview} controls playsInline preload="metadata" aria-label="上传口播原片预览" style={{ width: "100%", maxWidth: 280, maxHeight: 400 }} />}
      <details><summary>绑定参考稿（可选）</summary><label>参考确认稿（可选）<select value={referenceVersion} onChange={event => setReferenceVersion(event.target.value)} disabled={busy || !Array.isArray(confirmedVersions) || !confirmedVersions.length}>
        <option value="">不绑定确认稿</option>
        {Array.isArray(confirmedVersions) && confirmedVersions.map(version => <option key={version.id} value={version.id}>
          {version.snapshot.draft.name || "确认稿"} · {new Date(version.created_at).toLocaleString("zh-CN")} · {version.id.slice(0, 8)}
        </option>)}
      </select></label>
      <p className={styles.note}>{confirmedVersions === "unavailable" ? "暂时无法读取确认稿。重新选择上传原片可重试。" : confirmedVersions === undefined && saved ? "正在读取本项目确认稿。" : "参考稿用于回查写稿来源，字幕和词级时间轴以原片实际口播为准。"}</p>
      </details>
    </>}
    <label>原片已有字幕吗？<select value={subtitles} onChange={event => setSubtitles(event.target.value as typeof subtitles)}><option value="unknown">请先查看原片后选择</option><option value="none">没有，生成主字幕</option><option value="present">已有，保留画面中的字幕</option></select></label>
    <p className={styles.note}>动效剪辑使用 9:16 竖屏，保留原声。</p>
    <details><summary>单独识别与基础字幕</summary><div className={styles.correctionActions}>
      <button type="button" onClick={() => void submit("transcript")} disabled={busy || !canSubmit}>识别口播，准备动效剪辑</button>
      <button type="button" onClick={() => void submit("subtitles")} disabled={busy || !canSubmit}>生成基础字幕片</button>
    </div></details>
    </section>
    {error && <p className={styles.error} role="alert">{error}</p>}
    {loadError && <p className={styles.error} role="alert">{loadError}</p>}
    {taskLinkError && taskLinkError.id === focusedTaskId && <p className={styles.error} role="alert">{taskLinkError.message}</p>}
    {saved && <EditingPlanning key={`${workspaceId}:${projectId}`} workspaceId={workspaceId} projectId={projectId} tasks={tasks} actionRef={primaryAction} onPrimaryState={setPrimaryState} selected={planningTask} onSelect={setPlanningTask} template={template} onNativePlan={() => { setPlansVersion(value => value + 1); setNativeOpened(true); if (nativePanel.current) { nativePanel.current.open = true; nativePanel.current.scrollIntoView({ block: "start" }); } }}
      carryFrom={carrySelection?.projectId === projectId ? carrySelection : undefined} onClearCarry={() => setCarrySelection(undefined)} onPreview={previews => {
        const ids = previews.map(task => task.id);
        setTasks(rows => [...previews, ...rows.filter(row => !ids.includes(row.id))]);
        setLinkedPreviews({ projectId, ids });
        setPlansVersion(value => value + 1);
        requestAnimationFrame(() => document.getElementById("editing-results")?.scrollIntoView({ block: "start" }));
      }} />}
    {saved && <details className={flow.native} ref={nativePanel} onToggle={event => { if (event.currentTarget.open) setNativeOpened(true); }}><summary>调整画面、重点、配图与音乐 · 历史编排</summary>{nativeOpened && <EditingNativePlans key={`${workspaceId}:${projectId}`} workspaceId={workspaceId} projectId={projectId} plansVersion={plansVersion}
      revisionSelection={revisionSelection} onClearRevisionSelection={() => setRevisionSelection(undefined)}
      onCreated={async () => { applyTasks(await reload()); }} />}</details>}
    <details className={flow.library} onToggle={event => { if (event.currentTarget.open) setLibraryOpened(true); }}><summary>原库目录与项目选组备忘</summary>{libraryOpened && <EditingLibrary key={`${workspaceId}:${projectId}`} workspaceId={workspaceId} projectId={projectId} saved={saved} />}</details>
    <section id="editing-results" className={`${flow.step} ${flow.history}`} aria-label="预览与下载"><h2>任务与历史 <small>{tasks.length} 条</small></h2>
    {!tasks.length && <div className={flow.emptyHistory}><PackageOpen size={42} strokeWidth={1.2} /><span>暂无剪辑记录</span><small>生成后在这里预览和下载</small></div>}
    <div className={styles.tasks}>{tasks.filter((task, index) => showTaskHistory || index < 6 || task.id === focusedTaskId || ["queued", "running", "awaiting_review"].includes(task.status)).map(task => {
      const final = task.artifacts.find(a => a.role === "final");
      const preview = task.artifacts.find(a => a.role === "preview");
      const audioReceipt = task.artifacts.find(a => a.role === "audio_receipt");
      const transcript = task.artifacts.find(a => a.role === "transcript");
      const transcriptAudio = task.artifacts.find(a => a.role === "transcript_audio");
      const sourceReceipt = task.artifacts.find(a => a.role === "source_receipt");
      const layoutReceipt = task.artifacts.find(a => a.role === "layout_receipt");
      const editReceipt = (task.options.native_edits || task.options.preview_base) && task.artifacts.find(a => a.role === "compile_receipt");
      const parent = task.options.preview_base;
      const planId = task.options.native_plan_id;
      const layoutFailed = task.status === "failed" && (task.error_code === "EDITING_EFFECT_LAYOUT_FAILED" || task.error_code === "EDITING_NATIVE_LAYOUT_FAILED");
      return <details key={task.id} className={flow.taskCard} open={task.id === (focusedTaskId || tasks[0]?.id)}><summary><b>{task.status === "failed" ? "未完成" : task.status === "cancelled" ? "已取消" : stageLabel[task.stage] || "正在剪辑"}</b><time>{new Date(task.created_at).toLocaleDateString("zh-CN")}</time></summary><article id={`editing-task-${task.id}`} tabIndex={-1}><div className={styles.taskHeading}><b>{task.status === "failed" ? "剪辑未完成" : task.status === "cancelled" ? "已取消" : stageLabel[task.stage] || "正在剪辑"}</b><time>{new Date(task.created_at).toLocaleString("zh-CN")}</time></div>
        {["queued", "running"].includes(task.status) && <p role="status" className={styles.note}>当前阶段：{stageLabel[task.stage] || "正在处理"} · 已发起 {task.attempts} 次处理。进度来自服务端任务状态，每 5 秒刷新。</p>}
        <details><summary>来源与技术记录</summary>
        {task.source_origin?.kind === "generation_task" && <p className={styles.note}>
          原口播任务 <code title={task.source_origin.generation_task_id ?? undefined}>{task.source_origin.generation_task_id?.slice(0, 8)}</code>
          {task.source_origin.confirmed_version_id && <> · 确认稿 <code title={task.source_origin.confirmed_version_id}>{task.source_origin.confirmed_version_id.slice(0, 8)}</code></>}
        </p>}
        {task.source_origin?.confirmed_version_id && task.source_origin.writing_origin &&
          <WritingVersionSources workspaceId={workspaceId} projectId={task.project_id} versionId={task.source_origin.confirmed_version_id}
            adoptionId={task.source_origin.writing_origin.adoption_id} />}
        {task.source_origin?.kind === "upload_asset" && task.source_origin.confirmed_version_id && <p className={styles.note}>
          参考确认稿 <code title={task.source_origin.confirmed_version_id}>{task.source_origin.confirmed_version_id.slice(0, 8)}</code>
        </p>}
        {sourceReceipt && <a href={sourceReceipt.url} download>{task.source_origin?.kind === "upload_asset" ? "下载原片与参考稿核对记录" : "下载原片与配音核对记录"}</a>}
        </details>
        {task.options.mode === "native_plan" && <p className={styles.note}>按所选模板编排</p>}
        {task.motion_counts && <p className={styles.note}>{task.motion_counts.distinct_groups} 种动效 · {task.motion_counts.occurrences} 次。{task.motion_counts.distinct_groups < preferredDistinctMotionGroups && `低于优先目标 ${preferredDistinctMotionGroups} 种。`}</p>}
        {parent && <p className={styles.note}>基于预览 <a href={`#editing-task-${parent.task_id}`}>{parent.task_id.slice(0, 8)}</a></p>}
        {task.carried_revision && <p className={styles.note}>继承预览 <a href={`#editing-task-${task.carried_revision.preview_base.task_id}`}>{task.carried_revision.preview_base.task_id.slice(0, 8)}</a> 的人工调整 · {task.carried_revision.protected_beat_ids.length} 段原实录</p>}
        {task.options.native_edits && <p className={styles.note}>
          本次设置 · {task.options.native_edits.music === "off" ? "关闭背景音乐。" : task.options.native_edits.music === "lower" ? "背景音乐降低 6 dB。" : ""}
          {task.options.native_edits.music_track_id && "已更换原库背景音乐。"}
          {!!task.options.native_edits.highlight_edits?.length && ("已调整 " + task.options.native_edits.highlight_edits.length + " 个动效词槽。")}
          {!!task.options.native_edits.image_edits?.length && ("已替换 " + task.options.native_edits.image_edits.length + " 张配图。")}
          {!!task.options.native_edits.effect_edits?.length && `已更换 ${task.options.native_edits.effect_edits.length} 段原生动效。`}
          {!!task.options.native_edits.source_only_beat_ids?.length && `保留原景 ${task.options.native_edits.source_only_beat_ids.length} 段。`}
        </p>}
        {layoutReceipt && <p className={styles.note}>本次保留了原组设计里的前后叠字。 <a href={layoutReceipt.url} download>下载叠字版式记录</a></p>}
        {task.status === "failed" && <p role="alert">{layoutFailed
          ? "原生画面排版未通过。可沿用本次编排调整出错片段，再生成代理。"
          : errorLabel[task.error_code || ""] || "本次剪辑未完成，可以重试；已完成的配音不会重新生成。"}</p>}
        {layoutFailed && !!task.layout_findings?.length && <ul aria-label="原生排版问题">
          {task.layout_findings.map(finding => <li key={finding.shot_index}>
            {(finding.first_ms / 1000).toFixed(2)} 秒起 · {finding.group_id} · {finding.finding_count} 处排版问题
          </li>)}
        </ul>}
        {layoutFailed && planId && <button type="button" disabled={busy} onClick={() => revise({
          planId, taskId: task.id, kind: "layout_failure", preview: parent, edits: task.options.native_edits, layoutFindings: task.layout_findings,
        })}>调整出错片段</button>}
        {task.status === "awaiting_review" && preview && <>
          <video key={preview.id} id={`editing-preview-${task.id}`} controls playsInline preload="metadata" src={preview.url} aria-label="剪辑代理预览" onError={() => markPreviewFailure(preview.id)} />
          <p className={styles.note}>代理使用较小画幅，保留本版编排和音轨。</p>
          {audioReceipt && <EditingSoundReview key={`sound:${preview.id}:${audioReceipt.id}`} workspaceId={workspaceId} receipt={audioReceipt} media={preview} playerId={`editing-preview-${task.id}`} />}
          {previewFailures.includes(preview.id) && <button type="button" disabled={busy} onClick={() => void previewAction(task, preview, "repair")}>检查并恢复代理预览</button>}
          <button type="button" disabled={busy} onClick={() => void previewAction(task, preview, "confirm")}>确认并开放高清下载</button>
        </>}
        {preview && (task.status === "awaiting_review" || task.status === "completed") && planId && <button type="button" disabled={busy} onClick={() => revise({
          planId, taskId: task.id, kind: "preview", preview: { task_id: task.id, preview_artifact_id: preview.id, preview_sha256: preview.sha256 }, edits: task.options.native_edits,
        })}>沿用此版继续调整</button>}
        {preview && (task.status === "awaiting_review" || task.status === "completed") && planId && task.options.native_edits && <details><summary>继承到其他规划</summary><button type="button" disabled={busy} onClick={() => {
          setCarrySelection({ projectId, sourceId: task.source_id, base: { task_id: task.id, preview_artifact_id: preview.id, preview_sha256: preview.sha256 } });
          openPlanning();
        }}>将人工调整带入另一份规划</button></details>}
        {final && <><video id={`editing-film-${task.id}`} controls playsInline preload="metadata" src={final.url} aria-label="剪辑成片预览" /><p className={styles.note}>文件检查通过，口播与画面待验收。</p><a href={final.url} download>下载成片</a>
          {editReceipt && <a href={editReceipt.url} download>下载本次调整记录</a>}
          {audioReceipt && <EditingSoundReview key={`sound:${final.id}:${audioReceipt.id}`} workspaceId={workspaceId} receipt={audioReceipt} media={final} playerId={`editing-film-${task.id}`} />}
          <EditingFilmReview key={final.id} workspaceId={workspaceId} task={task} final={final} />
        </>}
        {task.status === "completed" && task.options.mode === "transcript" && transcript && <>
          {transcriptAudio && <audio id={`editing-transcript-audio-${task.id}`} controls preload="none" src={transcriptAudio.url} aria-label="口播原声试听" />}
          <a href={transcript.url} download>下载逐词转录</a>
          {task.source_frame?.supports_native_portrait === false
            ? <p className={styles.note} role="status">原片画幅 {task.source_frame.width}×{task.source_frame.height}。转录可试听和校对，方形像素原片也可生成保留画幅的基础字幕片。{errorLabel.EDITING_ORIENTATION_REVIEW_REQUIRED}</p>
            : <button type="button" disabled={busy} onClick={() => planFromTranscript(task.id)}>使用此转录开始规划</button>}
        </>}
        {task.status === "completed" && transcript && (final || task.options.mode === "transcript") && <>
          <button type="button" onClick={() => setCorrectionTask(correctionTask === task.id ? "" : task.id)}>{correctionTask === task.id ? "收起校对" : task.options.mode === "transcript" ? "校对口播转录" : "校对字幕"}</button>
          {correctionTask === task.id && <TranscriptEditor key={task.id} workspaceId={workspaceId} taskId={task.id} options={task.options} onCreated={async () => { applyTasks(await reload()); }} />}
        </>}
        {["queued", "running"].includes(task.status) && <button type="button" disabled={busy || task.cancel_requested} onClick={() => void action(task, "cancel")}>{task.cancel_requested ? "正在取消" : "取消"}</button>}
        {["failed", "cancelled"].includes(task.status) && !layoutFailed && <button type="button" disabled={busy} onClick={() => void action(task, "retry")}>重试剪辑</button>}
      </article></details>;
    })}</div>{tasks.length > 6 && <button type="button" onClick={() => setShowTaskHistory(value => !value)}>{showTaskHistory ? "收起历史版本" : "查看全部历史版本"}</button>}</section>
    <div className={flow.actionBar}><button type="button" disabled={busy || !saved || !template || recognizing || (transcriptReady ? primaryState?.disabled ?? true : !canSubmit)} onClick={begin}>{busy ? "正在提交…" : recognizing ? "正在识别口播…" : transcriptReady ? primaryState?.label || "开始智能剪辑" : "开始智能剪辑"}</button><small>{!saved ? "请先保存剪辑项目" : !template ? "请选择模板与口播视频" : recognizing ? "识别完成后自动检查素材" : transcriptReady ? primaryState?.hint : "原声保留 · 至少五种动效 · 先检查素材"}</small></div>
  </section>;
}
