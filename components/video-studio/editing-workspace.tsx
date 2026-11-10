"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { preferredDistinctMotionGroups } from "@/features/video-studio/editing-density";
import { apiClient } from "@/lib/api/client";
import { unwrapApiResponse } from "@/lib/api/request";
import type { GenerationJob } from "@/features/video-studio/library";
import type { components } from "@/lib/api/generated/openapi";
import { TranscriptEditor } from "./transcript-editor";
import { EditingLibrary } from "./editing-library";
import { EditingNativePlans, type EditingRevisionSelection } from "./editing-native-plans";
import { EditingPlanning } from "./editing-planning";
import styles from "./editing-workspace.module.css";

type EditingTask = components["schemas"]["EditingTaskResponse"];
const root = "/api/v1/video-studio/workspaces/{workspace_id}" as const;
const stageLabel: Record<string, string> = { queued: "等待剪辑", preparing: "准备原片", transcribing: "识别实际口播", aligning: "按校对文字重新对齐", compiling: "编排画面与字幕", rendering: "生成视频", validating: "检查成片", building_preview: "生成代理预览", storing: "保存产物", transcript_ready: "口播转录已就绪", preview_ready: "代理预览已就绪", completed: "成片已生成" };
const errorLabel: Record<string, string> = {
  EDITING_SOUND_OUTPUT_INVALID: "成片声音与原始口播或已选音效、背景乐不一致。请重试剪辑后复核。",
  EDITING_DECODE_SOUND_CHECK_FAILED: "暂时无法核对成片声音。请重试剪辑。",
  EDITING_CONDITION_ANCHOR_INCOMPLETE: "本次动效文字遗漏了实录适用条件。请核对原转录和动效强调词。",
  EDITING_NEGATION_ANCHOR_INCOMPLETE: "本次动效文字遗漏了实录的否定表达。请核对原转录和动效强调词。",
  EDITING_QUANTITY_ANCHOR_INCOMPLETE: "本次动效文字截断了实录数量或单位。请核对原转录和动效强调词。",
  EDITING_ORIENTATION_REVIEW_REQUIRED: "原生模板需要方形像素的 9:16 竖屏原片。请选择符合画幅的原片。",
  EDITING_VIDEO_FRAME_CLOCK_INVALID: "无法核对原片的显示时钟，请更换原片或联系管理员。",
  EDITING_MATERIAL_FRAME_CLOCK_INVALID: "无法核对补充视频的显示时钟，请检查素材或联系管理员。",
  EDITING_MEASURE_VIDEO_FRAME_CLOCK_FAILED: "无法读取原片的显示时间，请检查视频文件。",
  EDITING_NORMALIZE_VIDEO_FRAME_CLOCK_FAILED: "原片的变帧率取帧轨未能生成，请联系管理员。",
  EDITING_GENERATION_SCRIPT_CHANGED: "这条原口播的确认稿无法核对，请检查原生成任务。", EDITING_IMAGE_EDIT_INVALID: "这次选择的配图无法用于原图槽，请核对图片是否重复及透明图要求。", EDITING_MATERIAL_CHANGED: "配图原件已缺失或变化，请回到本期素材核对。", EDITING_HIGHLIGHT_INVALID: "这次选择的实录短语无法用于原动效，请返回编排重新选择。", EDITING_NO_SPEECH_RECOGNIZED: "没有识别到清晰口播，请检查原片声音。", EDITING_SOURCE_CHANGED: "原片已变化，请重新选择视频。", EDITING_CLOCK_REVIEW_REQUIRED: "原片音画起点需要校正，请更换原片或联系管理员。", EDITING_SOURCE_AUDIO_TAIL_REVIEW_REQUIRED: "请核对原片末尾的音画。画面结束后仍有声音，或音画时长差超出自动处理范围。", EDITING_ROTATION_REVIEW_REQUIRED: "此视频的旋转信息需要校正，请联系管理员。", EDITING_ORIGINAL_BROWSER_ASSETS_REQUIRED: "所选动效缺少会进入画面的原库图片，请联系管理员补齐原件。", EDITING_NATIVE_INPUTS_REQUIRED: "当前编排所需的原生参数或素材尚未备齐，请先补全编排。", EDITING_PLAN_SOURCE_CHANGED: "编排绑定的原片或转录已变化，请恢复原产物或保存新编排。", EDITING_NATIVE_PLAN_NOT_FOUND: "编排暂不可用，请联系管理员核对版本与运行配置。", EDITING_CAPTION_CAPACITY_REVIEW_REQUIRED: "当前识别词组超出字幕容量，请核对文字或联系管理员调整排版。", EDITING_CAPTION_DICTIONARY_MISSING: "剪辑服务缺少中文分词依赖，请联系管理员。", EDITING_CAPTION_DICTIONARY_CHANGED: "剪辑分词词典版本不匹配，请联系管理员核对。", EDITING_CAPTION_FONT_MISSING: "剪辑服务缺少已选定的原字幕字体，请联系管理员。", EDITING_CAPTION_FONT_CHANGED: "字幕字体与原库记录不一致，请联系管理员核对。", EDITING_CAPTION_LAYOUT_MISMATCH: "字幕换行与原生检查不一致，请先核对编排。" };

export function EditingWorkspace({ workspaceId, projectId, saved, jobs }: { workspaceId: string; projectId: string; saved: boolean; jobs: GenerationJob[] }) {
  const [tasks, setTasks] = useState<EditingTask[]>([]);
  const [selected, setSelected] = useState("");
  const [file, setFile] = useState<File>();
  const [subtitles, setSubtitles] = useState<"none" | "present" | "unknown">("unknown");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [loadError, setLoadError] = useState("");
  const [correctionTask, setCorrectionTask] = useState("");
  const [libraryOpened, setLibraryOpened] = useState(false);
  const [planningOpened, setPlanningOpened] = useState(false);
  const [planningTask, setPlanningTask] = useState("");
  const planningPanel = useRef<HTMLDetailsElement>(null);
  const [plansVersion, setPlansVersion] = useState(0);
  const [revisionSelection, setRevisionSelection] = useState<EditingRevisionSelection>();
  const pending = useRef<{ key: string; requestId: string; sourceId?: string } | undefined>(undefined);
  const candidates = jobs.filter(job => job.project_id === projectId && job.kind === "lipsync" && job.status === "completed");
  const options = useCallback(() => ({ params: { path: { workspace_id: workspaceId } }, signal: AbortSignal.timeout(12000) }), [workspaceId]);
  const [linkedPreviews, setLinkedPreviews] = useState<{ projectId: string; ids: string[] }>();
  const reload = useCallback(async () => {
    const result = await apiClient.GET(`${root}/editing-tasks`, { ...options(), params: { path: { workspace_id: workspaceId }, query: { project_id: projectId } } });
    const rows = unwrapApiResponse(result);
    if (linkedPreviews?.projectId !== projectId) return rows;
    const missing = linkedPreviews.ids.filter(id => !rows.some(row => row.id === id));
    const details = await Promise.allSettled(missing.map(async id => unwrapApiResponse(await apiClient.GET(`${root}/editing-tasks/{task_id}`, {
      ...options(), params: { path: { workspace_id: workspaceId, task_id: id } },
    }))));
    return [...details.flatMap(detail => detail.status === "fulfilled" && detail.value.project_id === projectId ? [detail.value] : []), ...rows];
  }, [workspaceId, projectId, options, linkedPreviews]);
  useEffect(() => {
    let live = true;
    const update = () => { void reload().then(rows => { if (live) { setTasks(rows); setLoadError(""); } }).catch(() => { if (live) setLoadError("暂时无法读取剪辑任务，请稍后重试。"); }); };
    update();
    const timer = setInterval(update, 5000);
    return () => { live = false; clearInterval(timer); };
  }, [reload]);
  const submit = async (mode: "transcript" | "subtitles") => {
    setBusy(true); setError("");
    try {
      const key = JSON.stringify([projectId, selected, file?.name, file?.size, file?.lastModified, subtitles, mode]);
      if (!pending.current || pending.current.key !== key) pending.current = { key, requestId: crypto.randomUUID() };
      const intent = pending.current;
      if (selected === "upload" && file && !intent.sourceId) {
        const form = new FormData(); form.append("project_id", projectId); form.append("file", file);
        const uploaded = unwrapApiResponse(await apiClient.POST(`${root}/editing-sources`, { ...options(), signal: AbortSignal.timeout(600000), body: {} as never, bodySerializer: () => form })) as { id: string };
        intent.sourceId = uploaded.id;
      }
      const body = { request_id: intent.requestId, ...(selected === "upload" ? { source_id: intent.sourceId } : { generation_task_id: selected }), options: { mode, source_subtitles: subtitles, language: "zh" as const, caption_font_id: "font-d1961be1161ea1be" as const } };
      unwrapApiResponse(await apiClient.POST(`${root}/editing-tasks`, { ...options(), body }));
      pending.current = undefined;
      setTasks(await reload());
    } catch (caught) { setError(caught instanceof Error ? caught.message : "剪辑提交暂未确认，再次点击会查询同一请求。"); }
    finally { setBusy(false); }
  };
  const action = async (task: EditingTask, kind: "cancel" | "retry") => {
    setBusy(true); setError("");
    try {
      const opts = { ...options(), params: { path: { workspace_id: workspaceId, task_id: task.id } } };
      const result = kind === "cancel" ? await apiClient.POST(`${root}/editing-tasks/{task_id}/cancel`, opts) : await apiClient.POST(`${root}/editing-tasks/{task_id}/retry`, opts);
      unwrapApiResponse(result); setTasks(await reload());
    } catch { setError("操作暂未确认，请刷新任务后重试。"); }
    finally { setBusy(false); }
  };
  const confirmExport = async (task: EditingTask, preview: components["schemas"]["EditingArtifactResponse"]) => {
    setBusy(true); setError("");
    try {
      unwrapApiResponse(await apiClient.POST(`${root}/editing-tasks/{task_id}/confirm-export`, {
        ...options(), params: { path: { workspace_id: workspaceId, task_id: task.id } },
        body: { preview_artifact_id: preview.id, preview_sha256: preview.sha256 },
      }));
      setTasks(await reload());
    } catch (caught) { setError(caught instanceof Error ? caught.message : "高清确认暂未完成，请刷新后重试。"); }
    finally { setBusy(false); }
  };
  const canSubmit = saved && selected && subtitles !== "unknown" && (selected !== "upload" || file);
  const planFromTranscript = (taskId: string) => {
    setPlanningTask(taskId);
    setPlanningOpened(true);
    if (planningPanel.current) {
      planningPanel.current.open = true;
      planningPanel.current.scrollIntoView({ block: "start" });
    }
  };
  const revise = (selection: EditingRevisionSelection) => {
    setRevisionSelection(selection);
    (document.getElementById(`editing-native-plan-${selection.planId}`) ?? document.getElementById("editing-native-plans"))?.scrollIntoView({ block: "start" });
  };
  return <section className={styles.panel} aria-label="口播剪辑">
    <div className={styles.intro}><b>口播剪辑 · 试运行</b><p>从已有口播或上传视频开始，识别实际语音，保留原声节奏。</p></div>
    {!saved && <p role="status">请先保存当前项目，再开始剪辑。</p>}
    <label>选择原片<select aria-label="选择原片" value={selected} onChange={event => { setSelected(event.target.value); setFile(undefined); }}><option value="">请选择已完成的口播</option>{candidates.map(job => <option key={job.id} value={job.id}>{job.snapshot?.draft.name || "口播视频"} · {new Date(job.created_at).toLocaleString("zh-CN")}{job.confirmed_version_id && (" · 确认稿 " + job.confirmed_version_id.slice(0, 8))}</option>)}<option value="upload">上传真人口播或已有视频</option></select></label>
    {selected === "upload" && <label>视频文件<input type="file" accept="video/mp4,video/quicktime,video/webm" onChange={event => setFile(event.target.files?.[0])} /></label>}
    <label>原片已有字幕吗？<select value={subtitles} onChange={event => setSubtitles(event.target.value as typeof subtitles)}><option value="unknown">请先查看原片后选择</option><option value="none">没有，生成主字幕</option><option value="present">已有，保留画面中的字幕</option></select></label>
    <p className={styles.note}>先识别口播可得到词级时间轴。动效模板和基础字幕片目前使用方形像素的 9:16 竖屏原片。</p>
    <div className={styles.correctionActions}>
      <button type="button" onClick={() => void submit("transcript")} disabled={busy || !canSubmit}>识别口播，准备动效剪辑</button>
      <button type="button" onClick={() => void submit("subtitles")} disabled={busy || !canSubmit}>生成基础字幕片</button>
    </div>
    {error && <p className={styles.error} role="alert">{error}</p>}
    {loadError && <p className={styles.error} role="alert">{loadError}</p>}
    {saved && <EditingNativePlans key={`${workspaceId}:${projectId}`} workspaceId={workspaceId} projectId={projectId} plansVersion={plansVersion}
      revisionSelection={revisionSelection} onClearRevisionSelection={() => setRevisionSelection(undefined)}
      onCreated={async () => { setTasks(await reload()); }} />}
    {saved && <details ref={planningPanel} onToggle={event => { if (event.currentTarget.open) setPlanningOpened(true); }}><summary>语义规划任务</summary>{planningOpened && <EditingPlanning key={`${workspaceId}:${projectId}`} workspaceId={workspaceId} projectId={projectId} tasks={tasks} selected={planningTask} onSelect={setPlanningTask} onNativePlan={() => setPlansVersion(value => value + 1)} onPreview={previews => {
      const ids = previews.map(task => task.id);
      setTasks(rows => [...previews, ...rows.filter(row => !ids.includes(row.id))]);
      setLinkedPreviews({ projectId, ids });
      setPlansVersion(value => value + 1);
    }} />}</details>}
    <details onToggle={event => { if (event.currentTarget.open) setLibraryOpened(true); }}><summary>原库目录与项目选组备忘</summary>{libraryOpened && <EditingLibrary key={`${workspaceId}:${projectId}`} workspaceId={workspaceId} projectId={projectId} saved={saved} />}</details>
    <div className={styles.tasks}>{tasks.map(task => {
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
      return <article key={task.id} id={`editing-task-${task.id}`}><div className={styles.taskHeading}><b>{task.status === "failed" ? "剪辑未完成" : task.status === "cancelled" ? "已取消" : stageLabel[task.stage] || "正在剪辑"}</b><time>{new Date(task.created_at).toLocaleString("zh-CN")}</time></div>
        {task.source_origin?.kind === "generation_task" && <p className={styles.note}>
          原口播任务 <code title={task.source_origin.generation_task_id ?? undefined}>{task.source_origin.generation_task_id?.slice(0, 8)}</code>
          {task.source_origin.confirmed_version_id && <> · 确认稿 <code title={task.source_origin.confirmed_version_id}>{task.source_origin.confirmed_version_id.slice(0, 8)}</code></>}
          {task.source_origin.writing_origin && <> · 事实卡 <code title={task.source_origin.writing_origin.facts_document_id}>{task.source_origin.writing_origin.facts_document_id.slice(0, 8)}</code></>}
        </p>}
        {sourceReceipt && <a href={sourceReceipt.url} download>下载原片与配音核对记录</a>}
        {task.options.mode === "native_plan" && <p className={styles.note}>动效编排试片 · 语义及视觉待验收</p>}
        {task.motion_counts && <p className={styles.note}>原生出片核验 {task.motion_counts.distinct_groups} 种动效，共出现 {task.motion_counts.occurrences} 次。{task.motion_counts.distinct_groups < preferredDistinctMotionGroups && `低于优先目标 ${preferredDistinctMotionGroups} 种。`}</p>}
        {parent && <p className={styles.note}>基于预览 <a href={`#editing-task-${parent.task_id}`}>{parent.task_id.slice(0, 8)}</a></p>}
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
          <video id={`editing-preview-${task.id}`} controls preload="metadata" src={preview.url} aria-label="剪辑代理预览" />
          <p className={styles.note}>代理使用较小画幅，保留本版编排和音轨。</p>
          <button type="button" disabled={busy} onClick={() => void confirmExport(task, preview)}>确认并开放高清下载</button>
        </>}
        {preview && (task.status === "awaiting_review" || task.status === "completed") && planId && <button type="button" disabled={busy} onClick={() => revise({
          planId, taskId: task.id, kind: "preview", preview: { task_id: task.id, preview_artifact_id: preview.id, preview_sha256: preview.sha256 }, edits: task.options.native_edits,
        })}>沿用此版继续调整</button>}
        {final && <><video id={`editing-film-${task.id}`} controls preload="metadata" src={final.url} aria-label="剪辑成片预览" /><p className={styles.note}>成片已通过文件与音视频检查，字幕准确性和画面效果请预览验收。</p><a href={final.url} download>下载成片</a>
          {editReceipt && <a href={editReceipt.url} download>下载本次调整记录</a>}
          {audioReceipt && <><p className={styles.note}>原生混音已通过技术检查，听感待验收。</p><a href={audioReceipt.url} download>下载声音校验记录</a></>}
        </>}
        {task.status === "completed" && task.options.mode === "transcript" && transcript && <>
          {transcriptAudio && <audio id={`editing-transcript-audio-${task.id}`} controls preload="none" src={transcriptAudio.url} aria-label="口播原声试听" />}
          <a href={transcript.url} download>下载逐词转录</a>
          {task.source_frame?.supports_native_portrait === false
            ? <p className={styles.note} role="status">原片画幅 {task.source_frame.width}×{task.source_frame.height}。转录可试听和校对。{errorLabel.EDITING_ORIENTATION_REVIEW_REQUIRED}</p>
            : <button type="button" disabled={busy} onClick={() => planFromTranscript(task.id)}>使用此转录开始规划</button>}
        </>}
        {task.status === "completed" && transcript && (final || task.options.mode === "transcript") && <>
          <button type="button" onClick={() => setCorrectionTask(correctionTask === task.id ? "" : task.id)}>{correctionTask === task.id ? "收起校对" : task.options.mode === "transcript" ? "校对口播转录" : "校对字幕"}</button>
          {correctionTask === task.id && <TranscriptEditor key={task.id} workspaceId={workspaceId} taskId={task.id} options={task.options} onCreated={async () => { setTasks(await reload()); }} />}
        </>}
        {["queued", "running"].includes(task.status) && <button type="button" disabled={busy || task.cancel_requested} onClick={() => void action(task, "cancel")}>{task.cancel_requested ? "正在取消" : "取消"}</button>}
        {["failed", "cancelled"].includes(task.status) && !layoutFailed && <button type="button" disabled={busy} onClick={() => void action(task, "retry")}>重试剪辑</button>}
      </article>;
    })}</div>
  </section>;
}
