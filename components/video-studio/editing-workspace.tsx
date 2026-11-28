"use client";

import { GuidedEmpty } from "./page-hero";
import { editingTaskProgress } from "@/features/video-studio/editing-progress";
import { EditingProgressSteps } from "./editing-progress";
import { useInternalTools } from "@/features/video-studio/internal-tools";
import { Check, UserRound } from "lucide-react";
import { editingFlowSteps } from "@/features/video-studio/editing-flow-steps";
import { workspaceActionLabel } from "@/features/video-studio/editing-primary";
import { revisingTask } from "@/features/video-studio/editing-workbench";
import { resumableEditing } from "@/features/video-studio/editing-resume";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useEffectEvent, useRef, useState, useSyncExternalStore } from "react";
import type { CostNote } from "@/features/video-studio/credit-notes";
import { editingMessage, editingTemplateName } from "@/features/video-studio/editing-presentation";
import { isEditingSuite } from "@/features/video-studio/editing-suite";
import { matchesReferenceScript, referenceScript, type EditingMusicPreference, isEditingMusicPreference } from "@/features/video-studio/editing-options";
import { projectApi, type VideoVersion } from "@/features/video-studio/projects";
import { ApiError } from "@/lib/api/api-error";
import { apiClient } from "@/lib/api/client";
import { unwrapApiResponse } from "@/lib/api/request";
import type { GenerationJob } from "@/features/video-studio/library";
import type { components } from "@/lib/api/generated/openapi";
import { Dialog } from "./studio-primitives";
import { TranscriptEditor } from "./transcript-editor";
import { EditingFilmReview } from "./editing-film-review";
import { EditingSoundReview } from "./editing-sound-review";
import { EditingMusicPicker } from "./editing-music-picker";
import { defaultAppleOptions, type AppleCreativeOptions } from "./editing-creative-options";
import { EditingLibrary } from "./editing-library";
import { EditingNativePlans, type EditingRevisionSelection } from "./editing-native-plans";
import { EditingPlanning, type CarrySelection, type EditingPrimaryAction, type EditingPrimaryState } from "./editing-planning";
import { WritingVersionSources } from "./writing-version-sources";
import styles from "./editing-workspace.module.css";
import flow from "./editing-flow.module.css";
import { EditingTemplateGallery, type TemplateCard } from "./editing-template-gallery";
import { mediaUrl } from "@/lib/api/base-url";
import { billableLabel } from "@/features/video-studio/credit-notes";
import { TopUpLink } from "./studio-content";

type EditingTask = components["schemas"]["EditingTaskResponse"];
type TaskLinkError = { id: string; message: string };
const root = "/api/v1/video-studio/workspaces/{workspace_id}" as const;
const taskHash = /^#editing-task-([0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12})$/i;
function subscribeToHash(listener: () => void) {
  window.addEventListener("hashchange", listener);
  return () => window.removeEventListener("hashchange", listener);
}
const readTaskHash = () => taskHash.exec(window.location.hash)?.[1].toLowerCase();
const stageLabel: Record<string, string> = { queued: "排队中", preparing: "读取原片", preparing_source: "准备口播画面", preparing_foreground: "准备人物前景", transcribing: "识别口播", aligning: "校准字幕", compiling: "编排画面", rendering: "生成视频", validating: "检查视频", building_preview: "准备预览", storing: "保存视频", transcript_ready: "口播已识别", preview_ready: "预览已就绪", completed: "可下载" };
const errorLabel: Record<string, string> = {
  EDITING_ALIGNMENT_DISABLED: "字幕对齐服务尚未开启，请联系管理员。",
  EDITING_ALIGNMENT_TEXT_TIMESTAMPS_MISMATCH: "口播稿和实际声音没能逐字对上。点「重试剪辑」会改用识别到的实际声音生成字幕。",
  EDITING_ALIGNMENT_FAILED: "口播稿和实际声音没能逐字对上。点「重试剪辑」会改用识别到的实际声音生成字幕。",
  EDITING_ALIGNMENT_TIMESTAMPS_REQUIRED: "未能取得字幕时间，请检查原片声音后重试。",
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

export function EditingWorkspace({ workspaceId, projectId, saved, jobs, compact = false, onSaveProject, cost, renderCredits, workItemId }: { workspaceId: string; projectId: string; saved: boolean; jobs: GenerationJob[]; compact?: boolean; onSaveProject?: () => Promise<void>; /** 从批次「精修这一条」进入：确认高清后把这条作品更新为最终版 */ workItemId?: string; /** 编排 + 出片的价格，例如「预计 40 积分」；未定价时只说明按用量计费 */ cost?: CostNote; /** 单独出片（生成预览）的积分；null = 未定价 */ renderCredits?: number | null }) {
  const internalTools = useInternalTools();
  const [tasks, setTasks] = useState<EditingTask[]>([]);
  const [sourceDialog, setSourceDialog] = useState(false);
  const [sourceChoice, setSelected] = useState<string>();
  const requestedGeneration = useSearchParams().get("generation");
  const [file, setFile] = useState<File>();
  const [sourcePreview, setSourcePreview] = useState("");
  const [referenceVersion, setReferenceVersion] = useState("");
  const [referenceText, setReferenceText] = useState("");
  const [music, setMusic] = useState<EditingMusicPreference>("template");
  const [creativeOptions, setCreativeOptions] = useState<AppleCreativeOptions>(defaultAppleOptions);
  const [preferencesLoaded, setPreferencesLoaded] = useState(false);
  const preferenceKey = `tengli-editing-options:${workspaceId}:${projectId}`;
  useEffect(() => {
    let live = true;
    void Promise.resolve().then(() => {
      if (!live) return;
      try {
        const prior: unknown = JSON.parse(localStorage.getItem(preferenceKey) || "null");
        if (prior && typeof prior === "object") {
          if ("music" in prior && isEditingMusicPreference(prior.music)) setMusic(prior.music as EditingMusicPreference);
          if ("creativeOptions" in prior && prior.creativeOptions && typeof prior.creativeOptions === "object" && "schema_version" in prior.creativeOptions && prior.creativeOptions.schema_version === "tengli.apple-creative/1") setCreativeOptions({ ...defaultAppleOptions, ...prior.creativeOptions } as AppleCreativeOptions);
        }
      } catch { /* Saved task snapshots remain authoritative. */ }
      setPreferencesLoaded(true);
    });
    return () => { live = false; };
  }, [preferenceKey]);
  useEffect(() => {
    if (preferencesLoaded) {
      try { localStorage.setItem(preferenceKey, JSON.stringify({ music, creativeOptions })); } catch { /* Optional preference. */ }
    }
  }, [music, creativeOptions, preferenceKey, preferencesLoaded]);
  const [confirmedVersions, setConfirmedVersions] = useState<VideoVersion[] | "unavailable">();
  const [subtitles, setSubtitles] = useState<"none" | "present" | "unknown">("none");
  const [busy, setBusy] = useState(false);
  const sourceUpload = useRef<HTMLInputElement>(null);
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
  const [historyQuery, setHistoryQuery] = useState("");
  const [template, setTemplate] = useState<TemplateCard>();
  const primaryAction = useRef<EditingPrimaryAction>(null);
  const resumeAfterSave = useRef(false);
  const [primaryState, setPrimaryState] = useState<EditingPrimaryState>();
  const [continueAfterRecognition, setContinueAfterRecognition] = useState(false);
  const [planningTask, setPlanningTask] = useState("");
  const nativePanel = useRef<HTMLDetailsElement>(null);
  const [plansVersion, setPlansVersion] = useState(0);
  const [revisionSelection, setRevisionSelection] = useState<EditingRevisionSelection>();
  const [carrySelection, setCarrySelection] = useState<CarrySelection>();
  const [replanOpen, setReplanOpen] = useState(false);
  const cancelAutomatic = () => { resumeAfterSave.current = false; setContinueAfterRecognition(false); primaryAction.current?.cancel(); };
  const chooseTemplate = (card: TemplateCard) => { cancelAutomatic(); setTemplate(card); };
  useEffect(() => {
    if (nativeOpened && nativePanel.current) {
      nativePanel.current.open = true;
      nativePanel.current.scrollIntoView({ block: "start" });
    }
  }, [nativeOpened, revisionSelection]);
  const pending = useRef<{ key: string; requestId: string } | undefined>(undefined);
  const upload = useRef<{ workspaceId: string; projectId: string; file: File; versionId: string; requestId: string; sourceId?: string } | undefined>(undefined);
  const candidates = jobs.filter(job => job.project_id === projectId && job.kind === "lipsync" && job.status === "completed");
  const selected = sourceChoice ?? candidates.find(job => job.id === requestedGeneration)?.id ?? "";
  const selectedGeneration = candidates.find(job => job.id === selected);
  const referenceConfirmed = !!selectedGeneration?.confirmed_version_id
    && selectedGeneration.snapshot?.draft.drive !== "audio"
    && !!selectedGeneration.snapshot?.draft.text;
  const initializedReference = useRef("");
  useEffect(() => {
    if (!selectedGeneration || initializedReference.current === selectedGeneration.id) return;
    let live = true;
    void Promise.resolve().then(() => {
      if (!live) return;
      initializedReference.current = selectedGeneration.id;
      setReferenceText(selectedGeneration.snapshot?.draft.text || "");
    });
    return () => { live = false; };
  }, [selectedGeneration]);
  const restoredSource = selected.startsWith("source:") ? selected.slice(7) : "";
  const restoredProject = useRef("");
  const [tasksLoaded, setTasksLoaded] = useState(false);
  const [resumeJobs, setResumeJobs] = useState<Parameters<typeof resumableEditing>[1]>();
  const [restoreTemplate, setRestoreTemplate] = useState<string>();
  useEffect(() => {
    if (!saved || !projectId) return;
    let live = true;
    // One read on open: the last planning tells which speech and template to bring back.
    void apiClient.GET(`${root}/projects/{project_id}/editing-planning-tasks`, {
      params: { path: { workspace_id: workspaceId, project_id: projectId } }, signal: AbortSignal.timeout(12000),
    }).then(result => unwrapApiResponse(result)).catch(() => []).then(rows => { if (live) setResumeJobs(rows); });
    return () => { live = false; };
  }, [projectId, saved, workspaceId]);
  useEffect(() => {
    if (restoredProject.current === projectId || !tasksLoaded || !resumeJobs) return;
    restoredProject.current = projectId;
    if (selected || file) return;
    const resume = resumableEditing(tasks, resumeJobs);
    const previous = resume && tasks.find(task => task.id === resume.taskId);
    if (!previous) return;
    const generation = previous.source_origin?.kind === "generation_task" ? previous.source_origin.generation_task_id : undefined;
    if (previous.source_origin?.kind !== "upload_asset" && !generation) return;
    let live = true;
    void Promise.resolve().then(() => {
      if (!live) return;
      if (generation) {
        // Keep the transcript's own reference; the generation draft must not replace it.
        initializedReference.current = generation;
        setSelected(generation);
      } else setSelected(`source:${previous.source_id}`);
      setPlanningTask(previous.id);
      setSubtitles(previous.options.source_subtitles);
      setReferenceText(previous.options.reference_script || "");
      if (resume.templateId) setRestoreTemplate(resume.templateId);
    });
    return () => { live = false; };
  }, [file, projectId, resumeJobs, selected, tasks, tasksLoaded]);
  useEffect(() => {
    const url = file ? URL.createObjectURL(file) : "";
    let live = true;
    void Promise.resolve().then(() => { if (live) setSourcePreview(url); });
    return () => { live = false; if (url) URL.revokeObjectURL(url); };
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
    setTasksLoaded(true);
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
      let sourceId: string | undefined = restoredSource || undefined;
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
      const suppliedReference = referenceScript(referenceText);
      const key = JSON.stringify([workspaceId, projectId, sourceId ?? selected, subtitles, mode, suppliedReference]);
      if (!pending.current || pending.current.key !== key) pending.current = { key, requestId: crypto.randomUUID() };
      const body = { request_id: pending.current.requestId, ...(sourceId ? { source_id: sourceId } : { generation_task_id: selected }), options: { mode, source_subtitles: subtitles, language: "zh" as const, caption_font_id: "font-d1961be1161ea1be" as const, ...(suppliedReference ? { reference_script: suppliedReference } : {}) } };
      const task = unwrapApiResponse(await apiClient.POST(`${root}/editing-tasks`, { ...options(), body }));
      if (mode === "transcript") setPlanningTask(task.id);
      pending.current = undefined;
      setTasks(rows => [task, ...rows.filter(row => row.id !== task.id)]);
    } catch (caught) {
      setError(caught instanceof ApiError && !caught.retryable ? editingMessage(caught, "视频暂时无法处理，请检查文件后重试。") : uploadPending
        ? "上传正在确认，再次点击会继续同一次上传，不会重复上传。"
        : "正在确认结果，不会重复扣费；再次点击只会查询原请求。");
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
  // 精修后的最终版写回作品条目（契约 C2：editing_task_id 归剪辑），成片页就用这一版。
  const adoptForWorkItem = async (taskId: string) => {
    const path = { workspace_id: workspaceId, item_id: workItemId as string };
    for (let attempt = 0; attempt < 2; attempt += 1) {
      const item = unwrapApiResponse(await apiClient.GET(`${root}/work-items/{item_id}`, { ...options(), params: { path } }));
      if (item.editing_task_id === taskId) return;
      const result = await apiClient.PATCH(`${root}/work-items/{item_id}`, { ...options(), params: { path }, body: { expected_version: item.version, editing_task_id: taskId, ...(item.stage === "editing" ? { stage: "finishing" as const, status: "pending" as const } : {}) } });
      if (!result.error) return;
    }
    setError("高清已生成，但没能同步到这一批的作品里，请回到批次结果刷新。");
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
      if (action === "confirm" && workItemId) await adoptForWorkItem(task.id);
      applyTasks(await reload());
    } catch (caught) {
      if (action === "confirm" && caught instanceof ApiError && caught.code === "EDITING_EXPORT_CHANGED") markPreviewFailure(preview.id);
      setError(editingMessage(caught, "预览操作暂未完成，请刷新后重试。"));
    }
    finally { setBusy(false); }
  };
  const canSubmit = saved && selected && subtitles !== "unknown" && (selected !== "upload" || file);
  const openPlanning = () => {
    document.getElementById("editing-arrange")?.scrollIntoView({ block: "start" });
  };
  const planFromTranscript = (taskId: string) => {
    const previous = tasks.find(task => task.id === taskId);
    if (previous?.source_origin?.kind === "upload_asset") {
      setSelected(`source:${previous.source_id}`);
      setFile(undefined);
      setSubtitles(previous.options.source_subtitles);
    }
    if (previous?.source_origin?.kind === "generation_task" && previous.source_origin.generation_task_id) {
      setSelected(previous.source_origin.generation_task_id);
      setFile(undefined);
      setSubtitles(previous.options.source_subtitles);
    }
    if (previous) setReferenceText(previous.options.reference_script || "");
    setPlanningTask(taskId);
    openPlanning();
  };
  const revise = (selection: EditingRevisionSelection) => {
    setRevisionSelection(selection);
    setNativeOpened(true);
    if (nativePanel.current) nativePanel.current.open = true;
    (document.getElementById(`editing-native-plan-${selection.planId}`) ?? document.getElementById("editing-native-plans"))?.scrollIntoView({ block: "start" });
  };
  const reusableAlignment = referenceConfirmed ? tasks.find(task =>
    task.status === "completed"
    && task.options.mode === "transcript"
    && !task.options.transcript_revision_id
    && task.options.source_subtitles === subtitles
    && matchesReferenceScript(task.options, referenceText)
    && task.source_origin?.kind === "generation_task"
    && task.source_origin.generation_task_id === selectedGeneration?.id
    && task.source_origin.confirmed_version_id === selectedGeneration?.confirmed_version_id
    && task.artifacts.some(artifact => artifact.role === "transcript")
    && task.artifacts.some(artifact => artifact.role === "alignment_receipt")
  ) : undefined;
  const sourceTask = tasks.find(task => task.id === planningTask) ?? reusableAlignment;
  const transcriptReady = sourceTask?.status === "completed" && matchesReferenceScript(sourceTask.options, referenceText) && sourceTask.artifacts.some(a => a.role === "transcript");
  const activeTranscriptId = transcriptReady ? sourceTask.id : "";
  const recognizing = !!sourceTask && ["queued", "running"].includes(sourceTask.status);
  const recognitionLabel = referenceConfirmed ? "正在对齐原稿" : "正在识别口播";
  useEffect(() => {
    if (!continueAfterRecognition || !transcriptReady || primaryState?.phase !== "prepare" || primaryState.disabled) return;
    let live = true;
    void Promise.resolve().then(() => {
      if (!live) return;
      setContinueAfterRecognition(false);
      primaryAction.current?.run();
    });
    return () => { live = false; };
  }, [continueAfterRecognition, transcriptReady, primaryState]);
  // 当前这次编排生成的剪辑任务：主按钮直接确认导出或打开成片，不让用户去折叠卡片里找小按钮。
  const planTask = primaryState?.previewTaskId ? tasks.find(task => task.id === primaryState.previewTaskId) : undefined;
  const planPreview = planTask?.status === "awaiting_review" ? planTask.artifacts.find(a => a.role === "preview") : undefined;
  const planFinal = planTask?.status === "completed" ? planTask.artifacts.find(a => a.role === "final") : undefined;
  const planResult = planPreview ? "awaiting_review" as const : planFinal ? "completed" as const : undefined;
  const showTask = (id: string) => {
    const card = document.getElementById(`editing-task-${id}`);
    const details = card?.closest("details");
    if (details) details.open = true;
    card?.scrollIntoView({ block: "start" });
  };
  const begin = () => {
    if (planTask && planPreview) { void previewAction(planTask, planPreview, "confirm").then(() => showTask(planTask.id)); return; }
    if (planTask && planFinal) { showTask(planTask.id); return; }
    // A restored page may still be recognizing: the click only arms the continuation.
    if (recognizing && template) { setContinueAfterRecognition(true); return; }
    if (!saved) {
      if (onSaveProject) {
        resumeAfterSave.current = true;
        setBusy(true);
        void onSaveProject().catch(caught => { resumeAfterSave.current = false; setError(editingMessage(caught, "项目暂未保存，请稍后重试。")); }).finally(() => setBusy(false));
      }
      return;
    }
    if (!template) { document.getElementById("editing-templates")?.scrollIntoView({ block: "start" }); return; }
    if (!selected || (selected === "upload" && !file)) {
      document.getElementById("editing-source")?.scrollIntoView({ block: "start" });
      if (selected === "upload") sourceUpload.current?.click();
      else setSourceDialog(true);
      return;
    }
    if (isEditingSuite(template.engine) && subtitles === "present") {
      cancelAutomatic();
      setError("请选择无内嵌字幕的口播视频。");
      document.getElementById("editing-source")?.scrollIntoView({ block: "start" });
      return;
    }
    if (subtitles === "unknown") {
      const more = document.getElementById("editing-source-options") as HTMLDetailsElement | null;
      if (more) more.open = true;
      document.getElementById("editing-subtitles")?.focus();
      return;
    }
    if (!transcriptReady) { setContinueAfterRecognition(true); void submit("transcript"); }
    else primaryAction.current?.run();
  };
  // Reads the latest begin without re-running the effect on every render.
  const resumeBegin = useEffectEvent(() => begin());
  useEffect(() => {
    if (!saved || busy || !resumeAfterSave.current) return;
    resumeAfterSave.current = false;
    resumeBegin();
  }, [saved, busy]);
  const taskTemplateName = (task: { template_id?: string | null; template_name?: string | null }) => task.template_id ? editingTemplateName(task.template_id, task.template_name ?? undefined) : task.template_name || "";
  const historyTasks = tasks.filter(task => (task.options.mode !== "transcript" || task.id === focusedTaskId) && (!historyQuery.trim() || `${taskTemplateName(task)} ${stageLabel[task.stage] || task.status} ${new Date(task.created_at).toLocaleDateString("zh-CN")}`.includes(historyQuery.trim())));
  const renderTasks = tasks.filter(task => task.options.mode !== "transcript");
  const flowSteps = editingFlowSteps({
    hasSource: Boolean(selectedGeneration || restoredSource || (selected === "upload" ? file : selected)),
    hasTemplate: Boolean(template),
    working: recognizing || renderTasks.some(task => task.status === "queued" || task.status === "running") || primaryState?.phase === "rendering" || primaryState?.phase === "waiting",
    // 只看当前这一条剪辑；项目里别的历史成片不代表这一次已经完成。
    previewReady: !!planPreview,
    finalReady: !!planFinal,
  });
  const actionLabel = workspaceActionLabel({ busy, recognizing: recognizing && continueAfterRecognition, phase: primaryState?.phase, waitingLabel: primaryState?.label, transcriptReady, credits: cost ? cost.credits : undefined, result: planResult });
  return <section className={`${styles.panel} ${flow.workbench} ${compact ? flow.compact : ""}`} aria-label="口播剪辑">
    <ol className={flow.flowSteps} aria-label="剪辑步骤">{flowSteps.map(step => <li key={step.key} data-state={step.state}>
      <button type="button" aria-current={step.state === "current" ? "step" : undefined} onClick={() => document.getElementById(step.anchor)?.scrollIntoView({ block: "start" })}>
        <span className={flow.flowIndex}>{step.state === "done" ? <Check size={12} /> : step.index}</span><span><b>{step.label}</b><small>{step.hint}</small></span>
      </button>
    </li>)}</ol>
    <EditingTemplateGallery key={`gallery:${workspaceId}:${projectId}`} workspaceId={workspaceId} projectId={saved ? projectId : ""} selected={template?.id || ""} fallbackId={restoreTemplate} onRestore={chooseTemplate} sampleRevision={tasks.flatMap(task => task.artifacts.filter(a => a.role === "final").map(a => a.sha256)).join(",")} onSelect={chooseTemplate} />
    <section id="editing-source" className={`${flow.step} ${flow.source}`} aria-label="准备口播"><div className={flow.sourceHeading}><h2>选视频</h2><label className={flow.uploadButton}>手动上传视频<input ref={sourceUpload} disabled={busy || recognizing} aria-label="上传口播视频" type="file" accept="video/mp4,video/quicktime,video/webm" onChange={event => { cancelAutomatic(); setSelected("upload"); setFile(event.target.files?.[0]); setPlanningTask(""); setReferenceVersion(""); setReferenceText(""); setSubtitles("none"); if (!saved && onSaveProject) void onSaveProject().catch(caught => setError(editingMessage(caught, "项目暂未保存，开始剪辑时会再试一次。"))); }} /></label></div>
    {!sourcePreview && !selectedGeneration && !restoredSource && <button type="button" className={flow.dropzone} onClick={() => setSourceDialog(true)}><UserRound size={36} strokeWidth={1.5} /><b>选择口播视频</b><small>我的视频</small></button>}

    {selected && <button type="button" className={flow.changeSource} onClick={() => setSourceDialog(true)}>更换口播视频</button>}
    {sourceDialog && <Dialog title="我的视频" onClose={() => setSourceDialog(false)}>
      <div className={flow.sourceChoices}>{candidates.map(job => <button type="button" key={job.id} onClick={() => { cancelAutomatic(); setSelected(job.id); setFile(undefined); setReferenceVersion(""); setReferenceText(job.snapshot?.draft.text || ""); setPlanningTask(""); setSubtitles("none"); setSourceDialog(false); }}>
        {job.video_url && <video src={mediaUrl(job.video_url)} preload="metadata" muted playsInline />}<span><b>{job.snapshot?.draft.name || "口播视频"}</b><small>{new Date(job.created_at).toLocaleDateString("zh-CN")}</small></span>
      </button>)}</div>
      {!candidates.length && <p className={flow.chosen}>还没有已生成的口播视频，可直接上传已有视频。</p>}
      <footer className={flow.modalFooter}><button type="button" onClick={() => { setSourceDialog(false); sourceUpload.current?.click(); }}>手动上传视频</button></footer>
    </Dialog>}
    {selectedGeneration?.video_url && <video src={mediaUrl(selectedGeneration.video_url)} controls playsInline preload="metadata" aria-label="已生成口播原片预览" style={{ width: "100%", maxWidth: 280, maxHeight: 400 }} />}
    {restoredSource && <video src={mediaUrl(`/api/v1/video-studio/workspaces/${workspaceId}/editing-sources/${restoredSource}/video`)} controls playsInline preload="metadata" aria-label="已保存口播原片预览" />}
    {selected === "upload" && <>

      {sourcePreview && <video src={mediaUrl(sourcePreview)} controls playsInline preload="metadata" aria-label="上传口播原片预览" style={{ width: "100%", maxWidth: 280, maxHeight: 400 }} />}
      <details><summary>绑定参考稿（可选）</summary><label>参考确认稿（可选）<select value={referenceVersion} onChange={event => { cancelAutomatic(); setReferenceVersion(event.target.value); setPlanningTask(""); }} disabled={busy || !Array.isArray(confirmedVersions) || !confirmedVersions.length}>
        <option value="">不绑定确认稿</option>
        {Array.isArray(confirmedVersions) && confirmedVersions.map(version => <option key={version.id} value={version.id}>
          {version.snapshot.draft.name || "确认稿"} · {new Date(version.created_at).toLocaleString("zh-CN")} · 已确认
        </option>)}
      </select></label>
      <p className={styles.note}>{confirmedVersions === "unavailable" ? "暂时无法读取确认稿。重新选择上传原片可重试。" : confirmedVersions === undefined && saved ? "正在读取本项目确认稿。" : "参考稿用于回查写稿来源，字幕和词级时间轴以原片实际口播为准。"}</p>
      </details>
    </>}
    {recognizing && <p role="status">{sourceTask?.stage === "queued" ? stageLabel.queued : recognitionLabel}{continueAfterRecognition ? "，完成后自动检查素材并继续编排。" : "，完成后点击「开始智能剪辑」即可继续，不会重新识别。"}</p>}
    {sourceTask?.status === "failed" && <p role="alert" className={styles.error}>{editingMessage(errorLabel[sourceTask.error_code || ""], referenceConfirmed ? "原稿对齐未完成，请检查原稿和原片声音后重试。" : "口播识别未完成，请检查原片声音后重新开始。")}</p>}
    <details id="editing-source-options" hidden={!selected}><summary>更多选项</summary><label className={flow.sourceSubtitleChoice}><input id="editing-subtitles" type="checkbox" disabled={busy || recognizing} checked={subtitles === "present"} onChange={event => { cancelAutomatic(); setSubtitles(event.target.checked ? "present" : "none"); setPlanningTask(""); setError(""); }} />原片已有字幕</label><div className={styles.correctionActions}>
      <button type="button" onClick={() => transcriptReady ? openPlanning() : void submit("transcript")} disabled={busy || !canSubmit || recognizing}>{referenceConfirmed ? (transcriptReady ? "使用已对齐字幕" : "对齐原稿，准备动效剪辑") : "识别口播，准备动效剪辑"}</button>
      <button type="button" onClick={() => void submit("subtitles")} disabled={busy || !canSubmit}>生成基础字幕片</button>
    </div></details>
    <EditingMusicPicker value={music} onChange={value => { cancelAutomatic(); setMusic(value); }} disabled={busy || recognizing} voiceOnly={isEditingSuite(template?.engine) && !template?.capabilities?.includes("music")} templateSound={template?.engine === "bihuo-full-suite"} />
    </section>
    {error && <p className={styles.error} role="alert">{error}</p>}
    {loadError && <p className={styles.error} role="alert">{loadError}</p>}
    {taskLinkError && taskLinkError.id === focusedTaskId && <p className={styles.error} role="alert">{taskLinkError.message}</p>}
    {saved && template && <EditingPlanning key={`${workspaceId}:${projectId}`} credits={cost ? cost.credits : undefined} renderCredits={renderCredits} renderShort={!!cost?.insufficient} workspaceId={workspaceId} projectId={projectId} tasks={tasks} actionRef={primaryAction} onPrimaryState={setPrimaryState} selected={activeTranscriptId} onSelect={planFromTranscript} template={template} music={music} creativeOptions={creativeOptions} onCreativeChange={value => { cancelAutomatic(); setCreativeOptions(value); }} onInputsChanged={cancelAutomatic} referenceText={referenceText} referenceConfirmed={referenceConfirmed} referenceDisabled={busy || recognizing} onReferenceChange={value => { cancelAutomatic(); setReferenceText(value); setPlanningTask(""); }} onNativePlan={() => { setPlansVersion(value => value + 1); setNativeOpened(true); if (nativePanel.current) { nativePanel.current.open = true; nativePanel.current.scrollIntoView({ block: "start" }); } }}
      carryFrom={carrySelection?.projectId === projectId ? carrySelection : undefined} onClearCarry={() => setCarrySelection(undefined)} onPreview={previews => {
        const ids = previews.map(task => task.id);
        setTasks(rows => [...previews, ...rows.filter(row => !ids.includes(row.id))]);
        setLinkedPreviews({ projectId, ids });
        setPlansVersion(value => value + 1);
        requestAnimationFrame(() => document.getElementById("editing-results")?.scrollIntoView({ block: "start" }));
      }} />}
    {saved && nativeOpened && <details className={flow.native} ref={nativePanel}><summary>调整当前视频</summary><EditingNativePlans key={`${workspaceId}:${projectId}`} workspaceId={workspaceId} projectId={projectId} plansVersion={plansVersion}
      revisionSelection={revisionSelection} onClearRevisionSelection={() => { setRevisionSelection(undefined); setNativeOpened(false); document.getElementById("editing-results")?.scrollIntoView({ block: "start" }); }}
      subtitleTask={revisingTask(tasks, revisionSelection)}
      onCreated={async () => { applyTasks(await reload()); }} /></details>}
    <details hidden className={flow.library} onToggle={event => { if (event.currentTarget.open) setLibraryOpened(true); }}><summary>帮助与技术详情</summary><p>排查素材、字体或服务问题时使用。</p><button type="button" onClick={() => setNativeOpened(true)}>查看历史编排</button>{libraryOpened && <EditingLibrary key={`${workspaceId}:${projectId}`} workspaceId={workspaceId} projectId={projectId} saved={saved} />}</details>
    <section id="editing-results" className={`${flow.step} ${flow.history}`} aria-label="预览与下载"><h2>预览与下载 <small>{historyTasks.length} 个版本</small></h2>{planResult && <p className={styles.note}>对这一版不满意？<button type="button" className={flow.secondaryAction} disabled={busy || !!cost?.insufficient || primaryState?.phase === "waiting"} onClick={() => setReplanOpen(true)}>{billableLabel("用同样设置重新编排", cost ? cost.credits : undefined)}</button></p>}<input type="search" className={flow.templateSearch} aria-label="搜索历史视频" placeholder="搜索历史视频" value={historyQuery} onChange={event => setHistoryQuery(event.target.value)} />
    {!historyTasks.length && <GuidedEmpty title="成片会出现在这里" description="每次剪辑都会保留一个版本，可以对比、调整后再出新版。" steps={["选视频", "选模板", "开始智能剪辑，预览后确认"]} motif="edit" />}
    <div className={styles.tasks}>{historyTasks.filter((task, index) => showTaskHistory || index < 3 || task.id === focusedTaskId || ["queued", "running", "awaiting_review"].includes(task.status)).map(task => {
      const final = task.artifacts.find(a => a.role === "final");
      const poster = task.artifacts.find(a => a.role === "poster");
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
      const progress = editingTaskProgress({ status: task.status, stage: task.stage, mode: task.options.mode });
      return <details key={task.id} className={flow.taskCard} open={task.id === (focusedTaskId || tasks[0]?.id) || task.id === planTask?.id || ["queued", "running", "awaiting_review"].includes(task.status)}><summary><b>{taskTemplateName(task) && `${taskTemplateName(task)} · `}{progress.label}</b><time>{new Date(task.created_at).toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" })}</time></summary><article id={`editing-task-${task.id}`} tabIndex={-1}><div className={styles.taskHeading}><b>{progress.label}</b><time>{new Date(task.created_at).toLocaleString("zh-CN")}</time></div>
        {task.status !== "completed" && task.status !== "cancelled" && <EditingProgressSteps progress={progress} />}
        {task.planning_origin === "operator_candidate" && <p className={styles.note}>人工调整版</p>}
        {final ? <video id={`editing-film-${task.id}`} controls playsInline preload="metadata" src={mediaUrl(final.url)} poster={mediaUrl(poster?.url)} aria-label="剪辑成片预览" /> : task.status === "awaiting_review" && preview && <video key={preview.id} id={`editing-preview-${task.id}`} controls playsInline preload="metadata" src={mediaUrl(preview.url)} poster={mediaUrl(poster?.url)} aria-label="剪辑视频预览" onError={() => markPreviewFailure(preview.id)} />}
        {final && <a href={mediaUrl(final.url)} download>下载高清视频</a>}
        {task.status === "awaiting_review" && preview && <><p className={styles.note}>先看预览，不满意可调整，确认后下载高清。</p><button type="button" disabled={busy} onClick={() => void previewAction(task, preview, "confirm")}>确认效果，获取高清</button></>}
        {preview && (task.status === "awaiting_review" || task.status === "completed") && planId && <button type="button" disabled={busy} onClick={() => revise({
          planId, taskId: task.id, kind: "preview", preview: { task_id: task.id, preview_artifact_id: preview.id, preview_sha256: preview.sha256 }, edits: task.options.native_edits,
        })}>调整本版</button>}
        {internalTools && <details className={flow.technicalDetails}><summary>技术详情</summary><p>任务编号：{task.id} · 已处理 {task.attempts} 次</p>{task.error_code && <p>诊断信息：{task.error_code}</p>}
        {task.motion_counts && <p>{task.motion_counts.distinct_groups} 种动效 · {task.motion_counts.occurrences} 次</p>}
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
        {sourceReceipt && <a href={mediaUrl(sourceReceipt.url)} download>{task.source_origin?.kind === "upload_asset" ? "下载原片与参考稿核对记录" : "下载原片与配音核对记录"}</a>}
        {editReceipt && <a href={mediaUrl(editReceipt.url)} download>下载本次调整记录</a>}
        {layoutReceipt && <a href={mediaUrl(layoutReceipt.url)} download>下载版式检查记录</a>}</details>}
        {parent && <p className={styles.note}><a href={`#editing-task-${parent.task_id}`}>查看调整前的版本</a></p>}
        {task.carried_revision && <p className={styles.note}>已保留之前的调整 · <a href={`#editing-task-${task.carried_revision.preview_base.task_id}`}>查看原版本</a></p>}
        {task.options.native_edits && <p className={styles.note}>
          本次设置 · {task.options.native_edits.music === "off" ? "关闭背景音乐。" : task.options.native_edits.music === "lower" ? "背景音乐调轻。" : task.options.native_edits.music === "raise" ? "背景音乐调明显。" : ""}
          {task.options.native_edits.music_track_id && "已更换原库背景音乐。"}
          {!!task.options.native_edits.highlight_edits?.length && ("已调整 " + task.options.native_edits.highlight_edits.length + " 处重点文字。")}
          {!!task.options.native_edits.image_edits?.length && ("已替换 " + task.options.native_edits.image_edits.length + " 张配图。")}
          {!!task.options.native_edits.effect_edits?.length && `已更换 ${task.options.native_edits.effect_edits.length} 段画面效果。`}
          {!!task.options.native_edits.source_only_beat_ids?.length && `保留原景 ${task.options.native_edits.source_only_beat_ids.length} 段。`}
        </p>}
        {preview && (task.status === "awaiting_review" || task.status === "completed") && planId && task.options.native_edits && <details><summary>继承到其他规划</summary><button type="button" disabled={busy} onClick={() => {
          setCarrySelection({ projectId, sourceId: task.source_id, base: { task_id: task.id, preview_artifact_id: preview.id, preview_sha256: preview.sha256 } });
          openPlanning();
        }}>将人工调整带入另一份规划</button></details>}
        {task.status === "failed" && <p role="alert">{layoutFailed
          ? "画面中的文字排版需要调整，请修改对应片段后重新预览。"
          : errorLabel[task.error_code || ""] || "本次剪辑未完成，可以重试；已完成的配音不会重新生成。"}</p>}
        {layoutFailed && !!task.layout_findings?.length && <ul aria-label="原生排版问题">
          {task.layout_findings.map(finding => <li key={finding.shot_index}>
            {(finding.first_ms / 1000).toFixed(1)} 秒附近 · {finding.finding_count} 处文字排版需调整
          </li>)}
        </ul>}
        {layoutFailed && planId && <button type="button" disabled={busy} onClick={() => revise({
          planId, taskId: task.id, kind: "layout_failure", preview: parent, edits: task.options.native_edits, layoutFindings: task.layout_findings,
        })}>调整出错片段</button>}
        {task.status === "awaiting_review" && preview && <>
          {internalTools && audioReceipt && <EditingSoundReview key={`sound:${preview.id}:${audioReceipt.id}`} workspaceId={workspaceId} receipt={audioReceipt} media={preview} playerId={`editing-preview-${task.id}`} />}
          {previewFailures.includes(preview.id) && <button type="button" disabled={busy} onClick={() => void previewAction(task, preview, "repair")}>重新加载预览</button>}
        </>}
        {final && <>
          {internalTools && audioReceipt && <EditingSoundReview key={`sound:${final.id}:${audioReceipt.id}`} workspaceId={workspaceId} receipt={audioReceipt} media={final} playerId={`editing-film-${task.id}`} />}
          {internalTools && <EditingFilmReview key={final.id} workspaceId={workspaceId} task={task} final={final} />}
        </>}
        {task.status === "completed" && task.options.mode === "transcript" && transcript && <>
          {transcriptAudio && <audio id={`editing-transcript-audio-${task.id}`} controls preload="none" src={mediaUrl(transcriptAudio.url)} aria-label="口播原声试听" />}
          <a href={mediaUrl(transcript.url)} download>下载逐词转录</a>
          {task.source_frame?.supports_native_portrait === false
            ? <p className={styles.note} role="status">原片画幅 {task.source_frame.width}×{task.source_frame.height}。转录可试听和校对，方形像素原片也可生成保留画幅的基础字幕片。{errorLabel.EDITING_ORIENTATION_REVIEW_REQUIRED}</p>
            : <button type="button" disabled={busy} onClick={() => planFromTranscript(task.id)}>使用这段口播继续剪辑</button>}
        </>}
        {task.status === "completed" && transcript && (final || task.options.mode === "transcript") && <>
          <button type="button" onClick={() => setCorrectionTask(correctionTask === task.id ? "" : task.id)}>{correctionTask === task.id ? "收起校对" : task.options.mode === "transcript" ? "校对口播转录" : "校对字幕"}</button>
          {correctionTask === task.id && <TranscriptEditor key={task.id} workspaceId={workspaceId} taskId={task.id} options={task.options} onCreated={async () => { applyTasks(await reload()); }} />}
        </>}
        {["queued", "running"].includes(task.status) && <button type="button" disabled={busy || task.cancel_requested} onClick={() => void action(task, "cancel")}>{task.cancel_requested ? "正在取消" : "取消"}</button>}
        {["failed", "cancelled"].includes(task.status) && !layoutFailed && <button type="button" disabled={busy} onClick={() => void action(task, "retry")}>重试剪辑</button>}
      </article></details>;
    })}</div>{historyTasks.length > 3 && <button type="button" onClick={() => setShowTaskHistory(value => !value)}>{showTaskHistory ? "收起历史版本" : `查看全部 ${historyTasks.length} 个版本`}</button>}</section>
    {replanOpen && <Dialog title="用同样设置重新编排" onClose={() => setReplanOpen(false)}>
      <p>会用同一条口播、同一个模板和素材重新编排一次，{cost && isPriced(cost.credits) ? `再扣 ${cost.credits.toLocaleString("zh-CN")} 积分` : FREE_TRIAL_TEXT}。当前这一版会保留，可以对比后再决定用哪一版。</p>
      <footer className={flow.modalFooter}><button type="button" onClick={() => setReplanOpen(false)}>取消</button><button type="button" disabled={busy} onClick={() => { setReplanOpen(false); primaryAction.current?.replan(); }}>确认重新编排</button></footer>
    </Dialog>}
    <div className={flow.actionBar}>{nativeOpened ? <><button type="button" onClick={() => document.getElementById("editing-native-plans")?.scrollIntoView({ block: "start" })}>返回调整面板</button><small>调整完成后，在面板中生成新版预览，原视频保留</small></> : <><button type="button" disabled={busy || (!planResult && (!!cost?.insufficient || (!saved && !onSaveProject) || (recognizing && continueAfterRecognition) || (!!canSubmit && !!template && transcriptReady && (primaryState?.disabled ?? true))))} onClick={begin}>{actionLabel}</button><small className={flow.feeHint} role="status">{planResult === "awaiting_review" ? "确认后生成高清版，不会重新剪辑，也不再扣费" : planResult === "completed" ? "高清成片已生成，可下载，也会出现在我的作品里" : recognizing ? continueAfterRecognition ? "识别完成后自动继续编排，请保持页面打开；若中途离开，回来后点一次即可接着做，不会重新识别。" : "口播仍在识别，点击后识别完成会自动继续编排。" : transcriptReady && primaryState ? primaryState.hint : "识别 → 编排 → 渲染 → 全片预览，确认后下载高清"}{!planResult && cost && <> · {cost.text}</>}{!planResult && cost?.insufficient && <> · <TopUpLink /></>}</small></>}</div>
  </section>;
}
