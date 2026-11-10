"use client";

import { useEffect, useRef, useState } from "react";
import { apiClient } from "@/lib/api/client";
import { unwrapApiResponse } from "@/lib/api/request";
import type { components } from "@/lib/api/generated/openapi";
import styles from "./editing-workspace.module.css";

type Revision = components["schemas"]["EditingTranscriptRevisionResponse"];
type Options = components["schemas"]["EditingOptions"];
type View = {
  artifact_id: string;
  source_id: string;
  text: string;
  text_status: string;
  text_revision_id: string | null;
  alignment_available: boolean;
  analysis_audio_offset_ms?: number;
  utterances: { id: string; text: string; start_ms: number; end_ms: number }[];
};
const root = "/api/v1/video-studio/workspaces/{workspace_id}" as const;
const statusLabel = (status: string) => status === "user_corrected" ? "用户已校对文字" : status === "operator_candidate" ? "待核对候选" : "自动识别文字";
const timeLabel = (ms: number) => `${Math.floor(ms / 60000).toString().padStart(2, "0")}:${Math.floor(ms / 1000 % 60).toString().padStart(2, "0")}`;

export function TranscriptEditor({ workspaceId, taskId, options, onCreated }: {
  workspaceId: string; taskId: string; options: Options; onCreated: () => Promise<void>;
}) {
  const [view, setView] = useState<View>();
  const [revisions, setRevisions] = useState<Revision[]>([]);
  const [text, setText] = useState("");
  const [reviewed, setReviewed] = useState(false);
  const [selected, setSelected] = useState<Revision>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const transcriptionOnly = options.mode === "transcript";
  const saveIntent = useRef<{ key: string; id: string } | undefined>(undefined);
  const renderIntent = useRef<{ key: string; id: string } | undefined>(undefined);
  const path = { workspace_id: workspaceId, task_id: taskId };
  useEffect(() => {
    let live = true;
    const load = async () => {
      const opts = { params: { path: { workspace_id: workspaceId, task_id: taskId } }, signal: AbortSignal.timeout(12000) };
      const [data, versions] = await Promise.all([
        apiClient.GET(`${root}/editing-tasks/{task_id}/transcript`, opts),
        apiClient.GET(`${root}/editing-tasks/{task_id}/transcript-revisions`, opts),
      ]);
      const current = unwrapApiResponse(data) as unknown as View;
      const saved = unwrapApiResponse(versions);
      if (live) { setView(current); setText(current.text); setRevisions(saved); }
    };
    void load().catch(() => { if (live) setError("暂时无法读取字幕记录，请关闭后重试。"); });
    return () => { live = false; };
  }, [workspaceId, taskId]);
  const save = async () => {
    if (!view) return;
    setBusy(true); setError(""); setMessage("");
    try {
      const parentId = selected?.id || view.text_revision_id;
      const key = JSON.stringify([view.artifact_id, parentId, text, reviewed]);
      if (!saveIntent.current || saveIntent.current.key !== key) saveIntent.current = { key, id: crypto.randomUUID() };
      const result = unwrapApiResponse(await apiClient.POST(`${root}/editing-tasks/{task_id}/transcript-revisions`, {
        params: { path }, signal: AbortSignal.timeout(12000),
        body: { request_id: saveIntent.current.id, base_transcript_artifact_id: view.artifact_id, parent_revision_id: parentId, corrected_text: text,
          text_status: reviewed ? "user_corrected" : "operator_candidate", attests_spoken_text: reviewed },
      }));
      setSelected(result); setRevisions(rows => [result, ...rows.filter(r => r.id !== result.id)]);
      saveIntent.current = undefined;
      setMessage("文字新版本已保存，可以用此版本重新对齐。");
    } catch (caught) { setError(caught instanceof Error ? caught.message : "保存结果暂未确认，再次保存会查询同一请求。"); }
    finally { setBusy(false); }
  };
  const render = async () => {
    if (!view || !selected || selected.corrected_text !== text || options.mode === "native_plan") return;
    setBusy(true); setError(""); setMessage("");
    try {
      const nextOptions = { ...options, language: "zh" as const, transcript_revision_id: selected.id };
      const key = JSON.stringify([view.source_id, nextOptions]);
      if (!renderIntent.current || renderIntent.current.key !== key) renderIntent.current = { key, id: crypto.randomUUID() };
      unwrapApiResponse(await apiClient.POST(`${root}/editing-tasks`, {
        params: { path: { workspace_id: workspaceId } }, signal: AbortSignal.timeout(12000),
        body: { request_id: renderIntent.current.id, source_id: view.source_id, options: nextOptions },
      }));
      renderIntent.current = undefined;
      setMessage(transcriptionOnly ? "已提交口播重新对齐任务。" : "已提交字幕重新对齐与出片任务。");
      await onCreated();
    } catch (caught) { setError(caught instanceof Error ? caught.message : "任务提交暂未确认，再次点击会查询同一请求。"); }
    finally { setBusy(false); }
  };
  const seek = (ms: number) => {
    const player = document.getElementById(transcriptionOnly ? `editing-transcript-audio-${taskId}` : `editing-film-${taskId}`);
    if (player instanceof HTMLMediaElement) {
      const offset = transcriptionOnly ? view?.analysis_audio_offset_ms ?? 0 : 0;
      player.currentTime = Math.max(0, (ms - offset) / 1000);
      void player.play().catch(() => setError("请先打开播放器，再定位试听。"));
    }
  };
  return <section className={styles.correction} aria-label="字幕校对">
    <b>字幕校对</b>
    <p className={styles.note}>{transcriptionOnly ? "对照原声修正错字。文字保存为独立版本，重新对齐后可用于规划。" : "对照原声修正错字。文字会保存为独立版本，重新生成后再检查时间和画面。"}</p>
    {!view && !error && <p role="status">正在读取字幕…</p>}
    {view && <>
      <p className={styles.note}>当前字幕：{statusLabel(view.text_status)}。时间点尚未人工验收。</p>
      <div className={styles.utterances} aria-label="原声分句定位">{view.utterances.map(u => <button key={u.id} type="button" onClick={() => seek(u.start_ms)}><time>{timeLabel(u.start_ms)}</time>{u.text}</button>)}</div>
      {revisions.length > 0 && <label>已有文字版本<select aria-label="已有文字版本" value={selected?.id || ""} onChange={event => {
        const revision = revisions.find(r => r.id === event.target.value);
        setSelected(revision); setText(revision?.corrected_text ?? view.text); setReviewed(false); setMessage("");
      }}><option value="">当前视频的字幕</option>{revisions.map(r => <option key={r.id} value={r.id}>{statusLabel(r.text_status)} · {new Date(r.created_at).toLocaleString("zh-CN")}</option>)}</select></label>}
      <label>校对文字<textarea aria-label="校对文字" rows={9} maxLength={20000} value={text} onChange={event => { setText(event.target.value); setReviewed(false); setMessage(""); }} /></label>
      <label className={styles.reviewCheck}><input type="checkbox" checked={reviewed} onChange={event => setReviewed(event.target.checked)} />我已对照原声核对这份文字；这不代表成片和时间点已验收</label>
      <div className={styles.correctionActions}><button type="button" disabled={busy || !text.trim() || (selected?.corrected_text === text && selected.text_status === (reviewed ? "user_corrected" : "operator_candidate"))} onClick={() => void save()}>{reviewed ? "保存已校对文字" : "保存待核对版本"}</button>
        <button type="button" disabled={busy || !view.alignment_available || !selected || selected.corrected_text !== text || (!transcriptionOnly && options.source_subtitles !== "none") || options.mode === "native_plan"} onClick={() => void render()}>{transcriptionOnly ? "按此版本重新对齐口播" : "按此版本重新生成字幕"}</button></div>
      {options.mode === "native_plan" && <p className={styles.note}>这条成片使用冻结的动效编排。可保存文字新版本，重新出片前需按新词点保存新的动效编排。</p>}
      {selected && <p className={styles.note}>已选择：{statusLabel(selected.text_status)}。{selected.corrected_text !== text ? "有未保存的修改，请先保存。" : "重新生成会使用这份已保存文字。"}</p>}
      {!view.alignment_available && <p className={styles.note}>校对文字可以保存；重新对齐服务尚未启用。</p>}
      {!transcriptionOnly && options.source_subtitles !== "none" && <p className={styles.note}>原画面已有字幕，修改文字不能擦除画面中的字。重新生成字幕需要无硬字幕的原片。</p>}
    </>}
    {message && <p role="status">{message}</p>}
    {error && <p className={styles.error} role="alert">{error}</p>}
  </section>;
}
