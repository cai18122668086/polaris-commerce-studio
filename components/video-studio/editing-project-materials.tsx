"use client";

import { useEffect, useRef, useState } from "react";
import { JobAssetPreview } from "@/components/job-asset-preview";
import { useJob, useJobs } from "@/features/jobs/api/jobs";
import { apiClient } from "@/lib/api/client";
import { unwrapApiResponse } from "@/lib/api/request";
import type { components } from "@/lib/api/generated/openapi";
import styles from "./editing-workspace.module.css";

type Material = components["schemas"]["EditingMaterialResponse"];
const path = "/api/v1/video-studio/workspaces/{workspace_id}/projects/{project_id}/editing-materials" as const;
const importPath = `${path}/image-results` as const;

export function EditingProjectMaterials({ workspaceId, projectId, selected, onSelect }: {
  workspaceId: string;
  projectId: string;
  selected: string[];
  onSelect: (ids: string[]) => void;
}) {
  const [rows, setRows] = useState<Material[]>([]);
  const [offset, setOffset] = useState<number | null>(null);
  const [source, setSource] = useState<"upload" | "creative">("upload");
  const [file, setFile] = useState<File>();
  const [jobId, setJobId] = useState("");
  const [assetId, setAssetId] = useState("");
  const [label, setLabel] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const intent = useRef<{ file: File; label: string; description: string; id: string } | undefined>(undefined);
  const importIntent = useRef<{ signature: string; id: string } | undefined>(undefined);
  const jobs = useJobs(source === "creative" ? workspaceId : undefined, { type: "creative_image", statuses: ["completed", "partial"], limit: 50 });
  const job = useJob(source === "creative" ? workspaceId : undefined, jobId || undefined);
  const outputs = job.data?.assets.filter(asset => asset.direction === "output" && asset.is_deliverable) ?? [];
  const chosen = outputs.find(asset => asset.asset_id === assetId);

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
    if (!label.trim() || !description.trim()) return;
    const params = { path: { workspace_id: workspaceId, project_id: projectId } };
    const signal = AbortSignal.timeout(600000);
    const saveUpload = async (file: File) => {
      if (intent.current?.file !== file || intent.current.label !== label || intent.current.description !== description) {
        intent.current = { file, label, description, id: crypto.randomUUID() };
      }
      const form = new FormData();
      form.append("file", file); form.append("request_id", intent.current.id);
      form.append("label", label); form.append("description", description);
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
      const material = source === "upload" ? file && await saveUpload(file) : chosen && await saveImport();
      if (!material) return;
      setRows(previous => [material, ...previous.filter(row => row.id !== material.id)]);
      intent.current = undefined; importIntent.current = undefined;
      setFile(undefined); setAssetId(""); setLabel(""); setDescription("");
      if (fileInput.current) fileInput.current.value = "";
    } catch (caught) { setError(caught instanceof Error ? caught.message : "素材保存暂未确认，可重试同一请求。"); }
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

  return <details><summary>本期补充素材</summary>
    <section aria-label="本期补充素材" className={styles.materials}>
      <p className={styles.note}>上传实拍或导入已完成的创意图。素材名称和说明供规划选材。成片会使用素材原件，请选用画面里没有内部备注的版本。</p>
      <label>素材来源<select value={source} disabled={busy} onChange={event => { setSource(event.target.value === "creative" ? "creative" : "upload"); setFile(undefined); setError(""); }}>
        <option value="upload">上传文件</option><option value="creative">已有创意图</option>
      </select></label>
      {source === "upload" ? <label>素材文件<input ref={fileInput} type="file" accept="image/jpeg,image/png,image/webp,video/mp4,video/quicktime,video/webm" disabled={busy} onChange={event => setFile(event.target.files?.[0])} /></label> : <>
        <label>创意图任务<select value={jobId} disabled={busy || jobs.isPending} onChange={event => { setJobId(event.target.value); setAssetId(""); }}>
          <option value="">选择有成品的任务</option>
          {jobs.data?.items.filter(item => item.output_asset_count > 0).map(item => <option key={item.id} value={item.id}>{item.display_name || item.id} · {item.output_asset_count} 张</option>)}
        </select></label>
        <label>创意图成品<select value={assetId} disabled={busy || !outputs.length} onChange={event => setAssetId(event.target.value)}>
          <option value="">选择成品图片</option>
          {outputs.map((asset, index) => <option key={`${asset.asset_id}:${asset.ordinal}`} value={asset.asset_id}>第 {index + 1} 张</option>)}
        </select></label>
        {(jobs.isError || job.isError) && <p role="alert" className={styles.error}>暂时无法读取已有创意图。</p>}
        {jobs.data && !jobs.data.items.some(item => item.output_asset_count > 0) && <p className={styles.note}>当前工作区没有可导入的创意图成品。</p>}
        {chosen && <JobAssetPreview workspaceId={workspaceId} relation={chosen} />}
      </>}
      <label>素材名称<input value={label} maxLength={120} disabled={busy} onChange={event => setLabel(event.target.value)} /></label>
      <label>实际画面说明<textarea value={description} maxLength={400} disabled={busy} onChange={event => setDescription(event.target.value)} /></label>
      <button type="button" onClick={() => void save()} disabled={busy || !(source === "upload" ? file : chosen) || !label.trim() || !description.trim()}>{source === "upload" ? "保存补充素材" : "导入成品图片"}</button>
      {error && <p role="alert" className={styles.error}>{error}</p>}
      {!!rows.length && <p role="status">本次规划已选 {selected.length} / 24 项</p>}
      <ul className={styles.materialList}>{rows.map(row => <li key={row.id} data-material-id={row.id}>
        <label className={styles.reviewCheck}><input type="checkbox" checked={selected.includes(row.id)} disabled={!selected.includes(row.id) && selected.length >= 24} onChange={event => onSelect(event.target.checked ? [...selected, row.id] : selected.filter(id => id !== row.id))} />{row.label}</label>
        <p className={styles.note}>{row.description} · {row.width} × {row.height}{row.duration_ms !== null && ` · ${row.duration_ms / 1000} 秒`}</p>
        {row.source_job_id && <p className={styles.note}>创意示意图 · 来自任务 {row.source_job_id}</p>}
        <a href={row.url} target="_blank" rel="noreferrer">查看素材原件</a>
      </li>)}</ul>
      {offset !== null && <button type="button" disabled={busy} onClick={() => void more()}>加载更多素材</button>}
    </section>
  </details>;
}
