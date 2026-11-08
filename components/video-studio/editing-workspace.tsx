"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiClient } from "@/lib/api/client";
import { unwrapApiResponse } from "@/lib/api/request";
import type { GenerationJob } from "@/features/video-studio/library";
import styles from "./editing-workspace.module.css";

type Artifact = { id: string; role: string; url: string; bytes: number; duration_ms: number | null };
type EditingTask = { id: string; source_id: string; status: string; stage: string; error_code: string | null; cancel_requested: boolean; created_at: string; artifacts: Artifact[] };
const root = "/api/v1/video-studio/workspaces/{workspace_id}" as const;
const stageLabel: Record<string, string> = { queued: "等待剪辑", preparing: "准备原片", transcribing: "识别实际口播", compiling: "对齐字幕", rendering: "生成视频", validating: "检查成片", storing: "保存成片", completed: "成片已生成" };
const errorLabel: Record<string, string> = { EDITING_NO_SPEECH_RECOGNIZED: "没有识别到清晰口播，请检查原片声音。", EDITING_SOURCE_CHANGED: "原片已变化，请重新选择视频。", EDITING_CLOCK_REVIEW_REQUIRED: "原片音画起点需要校正，请更换原片或联系管理员。", EDITING_ROTATION_REVIEW_REQUIRED: "此视频的旋转信息需要校正，请联系管理员。" };

export function EditingWorkspace({ workspaceId, projectId, saved, jobs }: { workspaceId: string; projectId: string; saved: boolean; jobs: GenerationJob[] }) {
  const [tasks, setTasks] = useState<EditingTask[]>([]);
  const [selected, setSelected] = useState("");
  const [file, setFile] = useState<File>();
  const [subtitles, setSubtitles] = useState<"none" | "present" | "unknown">("unknown");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [loadError, setLoadError] = useState("");
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
  return <section className={styles.panel} aria-label="口播剪辑">
    <div className={styles.intro}><b>口播剪辑 · 基础字幕试运行</b><p>从已有口播或上传视频开始，按真实录音生成字幕，保留原声节奏。</p></div>
    {!saved && <p role="status">请先保存当前项目，再开始剪辑。</p>}
    <label>选择原片<select value={selected} onChange={event => { setSelected(event.target.value); setFile(undefined); }}><option value="">请选择已完成的口播</option>{candidates.map(job => <option key={job.id} value={job.id}>{job.snapshot?.draft.name || "口播视频"} · {new Date(job.created_at).toLocaleString("zh-CN")}</option>)}<option value="upload">上传真人口播或已有视频</option></select></label>
    {selected === "upload" && <label>视频文件<input type="file" accept="video/mp4,video/quicktime,video/webm" onChange={event => setFile(event.target.files?.[0])} /></label>}
    <label>原片已有字幕吗？<select value={subtitles} onChange={event => setSubtitles(event.target.value as typeof subtitles)}><option value="unknown">请先查看原片后选择</option><option value="none">没有，生成主字幕</option><option value="present">已有，保留画面中的字幕</option></select></label>
    <p className={styles.note}>本轮先验证字幕和成片流程。语义重点、动效与音乐编排将在后续接入。</p>
    <button type="button" onClick={() => void submit()} disabled={busy || !saved || !selected || subtitles === "unknown" || (selected === "upload" && !file)}>{busy ? "正在处理…" : "开始剪辑"}</button>
    {error && <p className={styles.error} role="alert">{error}</p>}
    {loadError && <p className={styles.error} role="alert">{loadError}</p>}
    <div className={styles.tasks}>{tasks.map(task => {
      const final = task.artifacts.find(a => a.role === "final");
      return <article key={task.id}><div className={styles.taskHeading}><b>{task.status === "failed" ? "剪辑未完成" : task.status === "cancelled" ? "已取消" : stageLabel[task.stage] || "正在剪辑"}</b><time>{new Date(task.created_at).toLocaleString("zh-CN")}</time></div>
        {task.status === "failed" && <p role="alert">{errorLabel[task.error_code || ""] || "本次剪辑未完成，可以重试；已完成的配音不会重新生成。"}</p>}
        {final && <><video controls preload="metadata" src={final.url} aria-label="剪辑成片预览" /><p className={styles.note}>成片已通过文件与音视频检查，字幕准确性和画面效果请预览验收。</p><a href={final.url} download>下载成片</a></>}
        {["queued", "running"].includes(task.status) && <button type="button" disabled={busy || task.cancel_requested} onClick={() => void action(task, "cancel")}>{task.cancel_requested ? "正在取消" : "取消"}</button>}
        {["failed", "cancelled"].includes(task.status) && <button type="button" disabled={busy} onClick={() => void action(task, "retry")}>重试剪辑</button>}
      </article>;
    })}</div>
  </section>;
}
