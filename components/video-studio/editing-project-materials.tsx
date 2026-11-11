"use client";

import { useEffect, useRef, useState } from "react";
import { JobAssetPreview } from "@/components/job-asset-preview";
import { useJob, useJobs } from "@/features/jobs/api/jobs";
import { editingMessage } from "@/features/video-studio/editing-presentation";
import { apiClient } from "@/lib/api/client";
import { unwrapApiResponse } from "@/lib/api/request";
import type { components } from "@/lib/api/generated/openapi";
import styles from "./editing-workspace.module.css";

type Material = components["schemas"]["EditingMaterialResponse"];
const path = "/api/v1/video-studio/workspaces/{workspace_id}/projects/{project_id}/editing-materials" as const;
const importPath = `${path}/image-results` as const;

export function EditingProjectMaterials({ workspaceId, projectId, selected, onSelect, expanded = false, materialMode }: {
  expanded?: boolean;
  materialMode?: "speech" | "images" | "clips" | "special";
  workspaceId: string;
  projectId: string;
  selected: string[];
  onSelect: (ids: string[]) => void;
}) {
  const [rows, setRows] = useState<Material[]>([]);
  const [offset, setOffset] = useState<number | null>(null);
  const [source, setSource] = useState<"upload" | "creative" | "feedback">("upload");
  const [file, setFile] = useState<File>();
  const [jobId, setJobId] = useState("");
  const [assetId, setAssetId] = useState("");
  const [label, setLabel] = useState("");
  const [description, setDescription] = useState("");
  const [feedbackLabel, setFeedbackLabel] = useState("");
  const [likes, setLikes] = useState("");
  const [sourceRef, setSourceRef] = useState("");
  const [observedAt, setObservedAt] = useState("");
  const [observed, setObserved] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const intent = useRef<{ file: File; label: string; description: string; feedback: string; id: string } | undefined>(undefined);
  const importIntent = useRef<{ signature: string; id: string } | undefined>(undefined);
  const jobs = useJobs(source === "creative" ? workspaceId : undefined, { type: "creative_image", statuses: ["completed", "partial"], limit: 50 });
  const job = useJob(source === "creative" ? workspaceId : undefined, jobId || undefined);
  const outputs = job.data?.assets.filter(asset => asset.direction === "output" && asset.is_deliverable) ?? [];
  const chosen = outputs.find(asset => asset.asset_id === assetId);
  const feedbackReady = feedbackLabel.trim() && /^[0-9]{1,9}$/.test(likes) && sourceRef.trim() && observedAt && observed;

  useEffect(() => {
    const controller = new AbortController();
    void apiClient.GET(path, {
      params: { path: { workspace_id: workspaceId, project_id: projectId } }, signal: controller.signal,
    }).then(result => {
      const data = unwrapApiResponse(result);
      if (!controller.signal.aborted) { setRows(data.items); setOffset(data.next_offset); }
    }).catch(() => { if (!controller.signal.aborted) setError("暂时无法读取本期素材。"); });
    return () => controller.abort();
  }, [workspaceId, projectId]);

  const save = async () => {
    if (!label.trim() || !description.trim() || (source === "feedback" && !feedbackReady)) return;
    const params = { path: { workspace_id: workspaceId, project_id: projectId } };
    const signal = AbortSignal.timeout(600000);
    const saveUpload = async (file: File) => {
      const feedback = source === "feedback" ? JSON.stringify({
        label: feedbackLabel.trim(), likes: Number(likes), source_ref: sourceRef.trim(),
        observed_at: new Date(observedAt).toISOString(), attests_observation: true,
      }) : "";
      if (intent.current?.file !== file || intent.current.label !== label || intent.current.description !== description || intent.current.feedback !== feedback) {
        intent.current = { file, label, description, feedback, id: crypto.randomUUID() };
      }
      const form = new FormData();
      form.append("file", file); form.append("request_id", intent.current.id);
      form.append("label", label); form.append("description", description);
      if (feedback) form.append("feedback_observation", feedback);
      return unwrapApiResponse(await apiClient.POST(path, {
        params, signal,
        body: {} as never, bodySerializer: () => form,
      }));
    };
    const saveImport = async () => {
      const signature = JSON.stringify([projectId, jobId, assetId, label.trim(), description.trim()]);
      if (importIntent.current?.signature !== signature) {
        importIntent.current = { signature, id: crypto.randomUUID() };
      }
      return unwrapApiResponse(await apiClient.POST(importPath, {
        params, signal,
        body: { request_id: importIntent.current.id, job_id: jobId, asset_id: assetId, label, description },
      }));
    };
    setBusy(true); setError("");
    try {
      const material = source === "creative" ? chosen && await saveImport() : file && await saveUpload(file);
      if (!material) return;
      setRows(previous => [material, ...previous.filter(row => row.id !== material.id)]);
      if (!selected.includes(material.id) && selected.length < 24) onSelect([...selected, material.id]);
      intent.current = undefined; importIntent.current = undefined;
      setFile(undefined); setAssetId(""); setLabel(""); setDescription("");
      setFeedbackLabel(""); setLikes(""); setSourceRef(""); setObservedAt(""); setObserved(false);
      if (fileInput.current) fileInput.current.value = "";
    } catch (caught) { setError(editingMessage(caught, "素材保存尚未确认，请重试同一次上传。")); }
    finally { setBusy(false); }
  };

  const more = async () => {
    if (offset === null) return;
    setBusy(true); setError("");
    try {
      const data = unwrapApiResponse(await apiClient.GET(path, {
        params: { path: { workspace_id: workspaceId, project_id: projectId }, query: { offset } }, signal: AbortSignal.timeout(12000),
      }));
      setRows(previous => [...previous, ...data.items.filter(row => !previous.some(item => item.id === row.id))]);
      setOffset(data.next_offset);
    } catch { setError("暂时无法读取更多素材。"); }
    finally { setBusy(false); }
  };

  return <div>
    <details open={expanded || undefined}><summary>＋ 添加图片或录屏</summary>
    <section aria-label="本期补充素材" className={styles.materials}>
      <p className={styles.note}>{materialMode === "speech" ? "此模板可仅用口播出片，补充素材为可选。" : materialMode === "clips" ? "请上传已分好步骤的短录屏，每段从开头使用，并覆盖对应解说时长。长录屏自动定位尚未接入。" : "按模板要求选择商品、界面或资料图，并说明各自对应内容。"}</p>
      <p className={styles.note}>上传实拍或导入已完成的创意图。素材名称和说明供规划选材。成片会使用素材原件，请选用画面里没有内部备注的版本。</p>
      <label>素材来源<select value={source} disabled={busy} onChange={event => { const value = event.target.value; setSource(value === "creative" || value === "feedback" ? value : "upload"); setFile(undefined); setObserved(false); setError(""); }}>
        <option value="upload">上传文件</option><option value="creative">已有创意图</option><option value="feedback">上传互动证据图片</option>
      </select></label>
      {source !== "creative" ? <label>素材文件<input key={source} ref={fileInput} type="file" accept={source === "feedback" ? "image/jpeg,image/png,image/webp" : "image/jpeg,image/png,image/webp,video/mp4,video/quicktime,video/webm"} disabled={busy} onChange={event => { setFile(event.target.files?.[0]); setObserved(false); }} /></label> : <>
        <label>创意图任务<select value={jobId} disabled={busy || jobs.isPending} onChange={event => { setJobId(event.target.value); setAssetId(""); }}>
          <option value="">选择有成品的任务</option>
          {jobs.data?.items.filter(item => item.output_asset_count > 0).map((item, index) => <option key={item.id} value={item.id}>{item.display_name || `创意图任务 ${index + 1}`} · {item.output_asset_count} 张</option>)}
        </select></label>
        <label>创意图成品<select value={assetId} disabled={busy || !outputs.length} onChange={event => setAssetId(event.target.value)}>
          <option value="">选择成品图片</option>
          {outputs.map((asset, index) => <option key={`${asset.asset_id}:${asset.ordinal}`} value={asset.asset_id}>第 {index + 1} 张</option>)}
        </select></label>
        {(jobs.isError || job.isError) && <p role="alert" className={styles.error}>暂时无法读取已有创意图。</p>}
        {jobs.data && !jobs.data.items.some(item => item.output_asset_count > 0) && <p className={styles.note}>当前工作区没有可导入的创意图成品。</p>}
        {chosen && <JobAssetPreview workspaceId={workspaceId} relation={chosen} />}
      </>}
      <label>素材名称<input value={label} placeholder="例如：商品正面、上传步骤" maxLength={120} disabled={busy} onChange={event => setLabel(event.target.value)} /></label>
      <label>画面说明<textarea value={description} placeholder="例如：展示商品外观，对应口播中介绍外形的部分" maxLength={400} disabled={busy} onChange={event => setDescription(event.target.value)} /></label>
      {source === "feedback" && <>
        <label>反馈短标签<input value={feedbackLabel} maxLength={16} disabled={busy} onChange={event => { setFeedbackLabel(event.target.value); setObserved(false); }} /></label>
        <label>观察到的点赞数<input value={likes} type="number" min={0} max={999999999} step={1} disabled={busy} onChange={event => { setLikes(event.target.value); setObserved(false); }} /></label>
        <label>来源链接或记录编号<input value={sourceRef} maxLength={400} disabled={busy} onChange={event => { setSourceRef(event.target.value); setObserved(false); }} /></label>
        <label>观察时间（本机时区）<input value={observedAt} type="datetime-local" step={1} disabled={busy} onChange={event => { setObservedAt(event.target.value); setObserved(false); }} /></label>
        <label className={styles.reviewCheck}><input type="checkbox" checked={observed} disabled={busy || !file} onChange={event => setObserved(event.target.checked)} />我已核对上传图片及来源对应上述记录</label>
      </>}
      <button type="button" onClick={() => void save()} disabled={busy || !(source === "creative" ? chosen : file) || !label.trim() || !description.trim() || (source === "feedback" && !feedbackReady)}>{source === "creative" ? "导入成品图片" : "保存补充素材"}</button>
    </section></details>
    {error && <p role="alert" className={styles.error}>{error}</p>}
    <section className={styles.materials} aria-label="已上传素材">
      <p role="status">{rows.length ? `已选 ${selected.length} 项素材` : materialMode === "speech" ? "尚未添加图片，可直接继续" : "还没有补充素材，点击上方添加"}</p>
      <ul className={styles.materialTiles}>{rows.filter((row, index) => showAll || index < 6 || selected.includes(row.id)).map(row => <li key={row.id} data-material-id={row.id}>
        {row.mime.startsWith("image/") ? <img src={row.url} alt={row.label} loading="lazy" className={styles.materialPreview} /> : <video src={row.url} controls playsInline preload="none" aria-label={`${row.label}素材预览`} className={styles.materialPreview} />}
        <label className={styles.reviewCheck}><input type="checkbox" checked={selected.includes(row.id)} disabled={!selected.includes(row.id) && selected.length >= 24} onChange={event => onSelect(event.target.checked ? [...selected, row.id] : selected.filter(id => id !== row.id))} />{row.label}</label>
        <details><summary>素材说明</summary><p className={styles.note}>{row.description} · {row.width} × {row.height}{row.duration_ms !== null && ` · ${row.duration_ms / 1000} 秒`}</p>
        {row.source_job_id && <p className={styles.note}>来自已有创意图</p>}
        {row.feedback_observation && <p className={styles.note}>已登记互动记录 · {row.feedback_observation.label} · {row.feedback_observation.likes} 赞 · {new Date(row.feedback_observation.observed_at).toLocaleString()} · {row.feedback_observation.source_ref}</p>}
        <a href={row.url} target="_blank" rel="noreferrer">查看素材原件</a>
        </details>
      </li>)}</ul>
      {rows.length > 6 && <button type="button" onClick={() => setShowAll(value => !value)}>{showAll ? "收起其他素材" : `查看本期其他素材（${rows.length - 6} 项）`}</button>}
      {offset !== null && <button type="button" disabled={busy} onClick={() => void more()}>加载更多素材</button>}
    </section>
  </div>;
}
