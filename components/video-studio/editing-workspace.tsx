"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiClient } from "@/lib/api/client";
import { unwrapApiResponse } from "@/lib/api/request";
import type { GenerationJob } from "@/features/video-studio/library";
import type { components } from "@/lib/api/generated/openapi";
import { TranscriptEditor } from "./transcript-editor";
import { EditingLibrary } from "./editing-library";
import { EditingNativePlans } from "./editing-native-plans";
import { EditingPlanning } from "./editing-planning";
import styles from "./editing-workspace.module.css";

type Artifact = { id: string; role: string; url: string; sha256: string; bytes: number; duration_ms: number | null };
type EditingTask = { id: string; source_id: string; status: string; stage: string; error_code: string | null; cancel_requested: boolean; created_at: string; artifacts: Artifact[]; options: components["schemas"]["EditingOptions"] };
const root = "/api/v1/video-studio/workspaces/{workspace_id}" as const;
const stageLabel: Record<string, string> = { queued: "等待剪辑", preparing: "准备原片", transcribing: "识别实际口播", aligning: "按校对文字重新对齐", compiling: "编排画面与字幕", rendering: "生成视频", validating: "检查成片", building_preview: "生成代理预览", storing: "保存产物", preview_ready: "代理预览已就绪", completed: "成片已生成" };
const errorLabel: Record<string, string> = { EDITING_NO_SPEECH_RECOGNIZED: "没有识别到清晰口播，请检查原片声音。", EDITING_SOURCE_CHANGED: "原片已变化，请重新选择视频。", EDITING_CLOCK_REVIEW_REQUIRED: "原片音画起点需要校正，请更换原片或联系管理员。", EDITING_ROTATION_REVIEW_REQUIRED: "此视频的旋转信息需要校正，请联系管理员。", EDITING_NATIVE_INPUTS_REQUIRED: "当前编排所需的原生参数或素材尚未备齐，请先补全编排。", EDITING_PLAN_SOURCE_CHANGED: "编排绑定的原片或转录已变化，请恢复原产物或保存新编排。", EDITING_NATIVE_PLAN_NOT_FOUND: "编排暂不可用，请联系管理员核对版本与运行配置。", EDITING_CAPTION_CAPACITY_REVIEW_REQUIRED: "当前识别词组超出字幕容量，请核对文字或联系管理员调整排版。", EDITING_CAPTION_DICTIONARY_MISSING: "剪辑服务缺少中文分词依赖，请联系管理员。", EDITING_CAPTION_DICTIONARY_CHANGED: "剪辑分词词典版本不匹配，请联系管理员核对。", EDITING_CAPTION_FONT_MISSING: "剪辑服务缺少已选定的原字幕字体，请联系管理员。", EDITING_CAPTION_FONT_CHANGED: "字幕字体与原库记录不一致，请联系管理员核对。", EDITING_CAPTION_LAYOUT_MISMATCH: "字幕换行与原生检查不一致，请先核对编排。" };

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
  const [plansVersion, setPlansVersion] = useState(0);
  const pending = useRef<{ key: string; requestId: string; sourceId?: string } | undefined>(undefined);
  const candidates = jobs.filter(job => job.project_id === projectId && job.kind === "lipsync" && job.status === "completed");
  const options = useCallback(() => ({ params: { path: { workspace_id: workspaceId } }, signal: AbortSignal.timeout(12000) }), [workspaceId]);
  const reload = useCallback(async () => {
    const result = await apiClient.GET(`${root}/editing-tasks`, { ...options(), params: { path: { workspace_id: workspaceId }, query: { project_id: projectId } } });
    return unwrapApiResponse(result) as EditingTask[];
  }, [workspaceId, projectId, options]);
  useEffect(() => {
    let live = true;
    const update = () => { void reload().then(rows => { if (live) { setTasks(rows); setLoadError(""); } }).catch(() => { if (live) setLoadError("暂时无法读取剪辑任务，请稍后重试。"); }); };
    update();
    const timer = setInterval(update, 5000);
    return () => { live = false; clearInterval(timer); };
  }, [reload]);
  const submit = async () => {
    setBusy(true); setError("");
    try {
      const key = JSON.stringify([projectId, selected, file?.name, file?.size, file?.lastModified, subtitles]);
      if (!pending.current || pending.current.key !== key) pending.current = { key, requestId: crypto.randomUUID() };
      const intent = pending.current;
      if (selected === "upload" && file && !intent.sourceId) {
        const form = new FormData(); form.append("project_id", projectId); form.append("file", file);
        const uploaded = unwrapApiResponse(await apiClient.POST(`${root}/editing-sources`, { ...options(), signal: AbortSignal.timeout(600000), body: {} as never, bodySerializer: () => form })) as { id: string };
        intent.sourceId = uploaded.id;
      }
      const body = { request_id: intent.requestId, ...(selected === "upload" ? { source_id: intent.sourceId } : { generation_task_id: selected }), options: { mode: "subtitles" as const, source_subtitles: subtitles, language: "zh" as const, caption_font_id: "font-d1961be1161ea1be" as const } };
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
  const confirmExport = async (task: EditingTask, preview: Artifact) => {
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
  return <section className={styles.panel} aria-label="口播剪辑">
    <div className={styles.intro}><b>口播剪辑 · 试运行</b><p>从已有口播或上传视频开始，按真实录音生成字幕，保留原声节奏。</p></div>
    {!saved && <p role="status">请先保存当前项目，再开始剪辑。</p>}
    <label>选择原片<select value={selected} onChange={event => { setSelected(event.target.value); setFile(undefined); }}><option value="">请选择已完成的口播</option>{candidates.map(job => <option key={job.id} value={job.id}>{job.snapshot?.draft.name || "口播视频"} · {new Date(job.created_at).toLocaleString("zh-CN")}</option>)}<option value="upload">上传真人口播或已有视频</option></select></label>
    {selected === "upload" && <label>视频文件<input type="file" accept="video/mp4,video/quicktime,video/webm" onChange={event => setFile(event.target.files?.[0])} /></label>}
    <label>原片已有字幕吗？<select value={subtitles} onChange={event => setSubtitles(event.target.value as typeof subtitles)}><option value="unknown">请先查看原片后选择</option><option value="none">没有，生成主字幕</option><option value="present">已有，保留画面中的字幕</option></select></label>
    <p className={styles.note}>基础剪辑按原声生成主字幕。已保存的动效编排可在下方另行出片。</p>
    <button type="button" onClick={() => void submit()} disabled={busy || !saved || !selected || subtitles === "unknown" || (selected === "upload" && !file)}>{busy ? "正在处理…" : "开始剪辑"}</button>
    {error && <p className={styles.error} role="alert">{error}</p>}
    {loadError && <p className={styles.error} role="alert">{loadError}</p>}
    {saved && <EditingNativePlans key={`${workspaceId}:${projectId}`} workspaceId={workspaceId} projectId={projectId} plansVersion={plansVersion} onCreated={async () => { setTasks(await reload()); }} />}
    {saved && <details onToggle={event => { if (event.currentTarget.open) setPlanningOpened(true); }}><summary>语义规划任务</summary>{planningOpened && <EditingPlanning key={`${workspaceId}:${projectId}`} workspaceId={workspaceId} projectId={projectId} tasks={tasks} onNativePlan={() => setPlansVersion(value => value + 1)} />}</details>}
    <details onToggle={event => { if (event.currentTarget.open) setLibraryOpened(true); }}><summary>原库目录与项目选组备忘</summary>{libraryOpened && <EditingLibrary key={`${workspaceId}:${projectId}`} workspaceId={workspaceId} projectId={projectId} saved={saved} />}</details>
    <div className={styles.tasks}>{tasks.map(task => {
      const final = task.artifacts.find(a => a.role === "final");
      const preview = task.artifacts.find(a => a.role === "preview");
      const audioReceipt = task.artifacts.find(a => a.role === "audio_receipt");
      const layoutReceipt = task.artifacts.find(a => a.role === "layout_receipt");
      const editReceipt = task.options.native_edits && task.artifacts.find(a => a.role === "compile_receipt");
      return <article key={task.id}><div className={styles.taskHeading}><b>{task.status === "failed" ? "剪辑未完成" : task.status === "cancelled" ? "已取消" : stageLabel[task.stage] || "正在剪辑"}</b><time>{new Date(task.created_at).toLocaleString("zh-CN")}</time></div>
        {task.options.mode === "native_plan" && <p className={styles.note}>动效编排试片 · 语义及视觉待验收</p>}
        {task.options.native_edits && <p className={styles.note}>
          本次设置 · {task.options.native_edits.music === "off" ? "关闭背景音乐。" : task.options.native_edits.music === "lower" ? "背景音乐降低 6 dB。" : ""}
          {!!task.options.native_edits.source_only_beat_ids?.length && `保留原景 ${task.options.native_edits.source_only_beat_ids.length} 段。`}
        </p>}
        {layoutReceipt && <p className={styles.note}>本次保留了原组设计里的前后叠字。 <a href={layoutReceipt.url} download>下载叠字版式记录</a></p>}
        {task.status === "failed" && <p role="alert">{errorLabel[task.error_code || ""] || "本次剪辑未完成，可以重试；已完成的配音不会重新生成。"}</p>}
        {task.status === "awaiting_review" && preview && <>
          <video id={`editing-preview-${task.id}`} controls preload="metadata" src={preview.url} aria-label="剪辑代理预览" />
          <p className={styles.note}>代理使用较小画幅，保留原编排和音轨。需要修改时可回到候选重新生成预览。</p>
          <button type="button" disabled={busy} onClick={() => void confirmExport(task, preview)}>确认并开放高清下载</button>
        </>}
        {final && <><video id={`editing-film-${task.id}`} controls preload="metadata" src={final.url} aria-label="剪辑成片预览" /><p className={styles.note}>成片已通过文件与音视频检查，字幕准确性和画面效果请预览验收。</p><a href={final.url} download>下载成片</a>
          {editReceipt && <a href={editReceipt.url} download>下载本次调整记录</a>}
          {audioReceipt && <><p className={styles.note}>原生混音已通过技术检查，听感待验收。</p><a href={audioReceipt.url} download>下载声音校验记录</a></>}
          {task.artifacts.some(a => a.role === "transcript") && <button type="button" onClick={() => setCorrectionTask(correctionTask === task.id ? "" : task.id)}>{correctionTask === task.id ? "收起校对" : "校对字幕"}</button>}
          {correctionTask === task.id && <TranscriptEditor key={task.id} workspaceId={workspaceId} taskId={task.id} options={task.options} onCreated={async () => { setTasks(await reload()); }} />}</>}
        {["queued", "running"].includes(task.status) && <button type="button" disabled={busy || task.cancel_requested} onClick={() => void action(task, "cancel")}>{task.cancel_requested ? "正在取消" : "取消"}</button>}
        {["failed", "cancelled"].includes(task.status) && <button type="button" disabled={busy} onClick={() => void action(task, "retry")}>重试剪辑</button>}
      </article>;
    })}</div>
  </section>;
}
