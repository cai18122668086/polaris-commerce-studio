"use client";

import { useEffect, useRef, useState, type DragEvent } from "react";
import { Upload, Plus, ImageIcon, FileVideo, Play, Search, Check, ArrowUpRight } from "lucide-react";
import { Dialog } from "./studio-primitives";
import { JobAssetPreview } from "@/components/job-asset-preview";
import { useJob, useJobs } from "@/features/jobs/api/jobs";
import { editingMessage } from "@/features/video-studio/editing-presentation";
import { apiClient } from "@/lib/api/client";
import { unwrapApiResponse } from "@/lib/api/request";
import type { components } from "@/lib/api/generated/openapi";
import legacy from "./editing-workspace.module.css";
import materialStyles from "./editing-materials.module.css";
const styles = { ...legacy, ...materialStyles };

type Material = components["schemas"]["EditingMaterialResponse"];
const path = "/api/v1/video-studio/workspaces/{workspace_id}/projects/{project_id}/editing-materials" as const;
const importPath = `${path}/image-results` as const;

export function EditingProjectMaterials({ workspaceId, projectId, selected, onSelect, expanded = false, materialMode, imagesOnly = false }: {
  imagesOnly?: boolean;
  expanded?: boolean;
  materialMode?: "speech" | "images" | "clips" | "special";
  workspaceId: string;
  projectId: string;
  selected: string[];
  onSelect: (ids: string[]) => void;
}) {
  const [adding, setAdding] = useState(expanded);
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
  const [filter, setFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [preview, setPreview] = useState<Material>();
  const [dragging, setDragging] = useState(false);
  const [filePreview, setFilePreview] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);
  const intent = useRef<{ file: File; label: string; description: string; feedback: string; id: string } | undefined>(undefined);
  const importIntent = useRef<{ signature: string; id: string } | undefined>(undefined);
  const jobs = useJobs(source === "creative" ? workspaceId : undefined, { type: "creative_image", statuses: ["completed", "partial"], limit: 50 });
  const job = useJob(source === "creative" ? workspaceId : undefined, jobId || undefined);
  const outputs = job.data?.assets.filter(asset => asset.direction === "output" && asset.is_deliverable) ?? [];
  const chosen = outputs.find(asset => asset.asset_id === assetId);
  const feedbackReady = feedbackLabel.trim() && /^[0-9]{1,9}$/.test(likes) && sourceRef.trim() && observedAt && observed;
  const imageUpload = imagesOnly || source === "feedback";
  const accept = imageUpload ? "image/jpeg,image/png,image/webp" : "image/jpeg,image/png,image/webp,video/mp4,video/quicktime,video/webm";
  useEffect(() => () => { if (filePreview) URL.revokeObjectURL(filePreview); }, [filePreview]);
  const pickFile = (picked?: File) => {
    if (picked && !(imageUpload ? /\.(jpe?g|png|webp)$/i : /\.(jpe?g|png|webp|mp4|mov|webm)$/i).test(picked.name)) {
      setError(imageUpload ? "请选择 JPG、PNG 或 WebP 图片。" : "请选择 JPG、PNG、WebP 图片或 MP4、MOV、WebM 视频。"); return;
    }
    setFile(picked); setFilePreview(picked ? URL.createObjectURL(picked) : ""); setError(""); setObserved(false);
    if (picked && !label) setLabel(picked.name.replace(/\.[^.]+$/, ""));
  };
  const drop = (event: DragEvent<HTMLLabelElement>) => {
    event.preventDefault(); setDragging(false);
    if (busy) return;
    if (event.dataTransfer.files.length > 1) { setError("每次添加一份素材，方便分别填写对应内容。"); return; }
    pickFile(event.dataTransfer.files[0]);
  };
  const matching = rows.filter(row => (filter === "all" || (filter === "image" ? row.mime.startsWith("image/") : row.mime.startsWith("video/"))) && (!query.trim() || `${row.label} ${row.description}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())));
  const visible = matching.filter((row, index) => showAll || query.trim() || filter !== "all" || index < 6 || selected.includes(row.id));
  const hiddenCount = matching.length - visible.length;

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
    if (!label.trim() || (source === "feedback" && !feedbackReady)) return;
    if (imagesOnly && file && !file.type.startsWith("image/")) {
      setError("此模板的配图槽支持图片，请选择图片文件。"); return;
    }
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
      form.append("label", label); form.append("description", description.trim() || label.trim());
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
        body: { request_id: importIntent.current.id, job_id: jobId, asset_id: assetId, label, description: description.trim() || label.trim() },
      }));
    };
    setBusy(true); setError("");
    try {
      const material = source === "creative" ? chosen && await saveImport() : file && await saveUpload(file);
      if (!material) return;
      setRows(previous => [material, ...previous.filter(row => row.id !== material.id)]);
      if (!selected.includes(material.id) && selected.length < 24) onSelect([...selected, material.id]);
      intent.current = undefined; importIntent.current = undefined;
      setFile(undefined); setAssetId(""); setLabel(""); setDescription(""); setAdding(false);
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

  return <div className={styles.materialBrowser}>
    <div className={styles.materialToolbar}><div><b>本期素材</b><span>{selected.length ? `已选 ${selected.length} / 24` : "图片和视频可混用"}</span></div><button type="button" className={styles.addMaterial} onClick={() => setAdding(true)}><Plus size={15} /> 添加素材</button></div>
    {adding && <Dialog title="添加素材" className={styles.materialUploadDialog} closeDisabled={busy} onClose={() => { if (!busy) setAdding(false); }}>
    <section aria-label="本期补充素材" className={styles.materials}>
      <p className={styles.note}>{materialMode === "speech" ? "此模板可仅用口播出片，补充素材为可选。" : materialMode === "clips" ? "请上传已分好步骤的短录屏，每段从开头使用，并覆盖对应解说时长。长录屏自动定位尚未接入。" : "按模板要求选择商品、界面或资料图，并说明各自对应内容。"}</p>
      <div className={styles.sourceTabs} role="group" aria-label="素材来源">{([['upload', '上传文件'], ['creative', '已有创意图'], ['feedback', '互动证据图片']] as const).map(([value, name]) => <button type="button" key={value} aria-pressed={source === value} disabled={busy} onClick={() => { setSource(value); setFile(undefined); setObserved(false); setError(""); }}>{name}</button>)}</div>
      {source !== "creative" ? <>
        <label className={`${styles.uploadDropzone} ${dragging ? styles.dragging : ""}`} onDragOver={event => { event.preventDefault(); if (!busy) setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={drop}>
          <input key={source} ref={fileInput} type="file" aria-label="素材文件" accept={accept} disabled={busy} onChange={event => pickFile(event.target.files?.[0])} />
          {file ? <><span className={styles.pickedFile}>{file.type.startsWith("image/") && filePreview ? <img src={filePreview} alt="待上传素材预览" /> : <FileVideo size={30} />}<b>{file.name}</b><small>{(file.size / 1024 / 1024).toFixed(1)} MB · 点击更换</small></span></> : <><Upload size={27} /><b>点击选择{imageUpload ? "图片" : "图片或视频"}，或拖放到这里</b><small>{imageUpload ? "JPG / PNG / WebP" : "JPG / PNG / WebP · MP4 / MOV / WebM"}</small></>}
        </label>
        <p className={styles.note}>{source === "feedback" ? "上传与互动记录对应的图片，再填写观察信息。" : "图片与视频均可添加。视频使用画面，声音保留口播原声。"}</p>
      </> : <>
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
      <label>补充说明（可选）<textarea value={description} placeholder="例如：复制商品链接的操作，放到介绍复制链接的那句话" maxLength={400} disabled={busy} onChange={event => setDescription(event.target.value)} /></label>
      {source === "feedback" && <>
        <label>反馈短标签<input value={feedbackLabel} maxLength={16} disabled={busy} onChange={event => { setFeedbackLabel(event.target.value); setObserved(false); }} /></label>
        <label>观察到的点赞数<input value={likes} type="number" min={0} max={999999999} step={1} disabled={busy} onChange={event => { setLikes(event.target.value); setObserved(false); }} /></label>
        <label>来源链接或记录编号<input value={sourceRef} maxLength={400} disabled={busy} onChange={event => { setSourceRef(event.target.value); setObserved(false); }} /></label>
        <label>观察时间（本机时区）<input value={observedAt} type="datetime-local" step={1} disabled={busy} onChange={event => { setObservedAt(event.target.value); setObserved(false); }} /></label>
        <label className={styles.reviewCheck}><input type="checkbox" checked={observed} disabled={busy || !file} onChange={event => setObserved(event.target.checked)} />我已核对上传图片及来源对应上述记录</label>
      </>}
      {error && <p role="alert" className={styles.error}>{error}</p>}
      <footer className={styles.uploadFooter}><button type="button" className={styles.secondaryAction} disabled={busy} onClick={() => setAdding(false)}>取消</button><button type="button" onClick={() => void save()} disabled={busy || !(source === "creative" ? chosen : file) || !label.trim() || (source === "feedback" && !feedbackReady)}>{busy ? "正在保存…" : source === "creative" ? "导入成品图片" : "保存并选用"}</button></footer>
    </section></Dialog>}
    {error && !adding && <p role="alert" className={styles.error}>{error}</p>}
    <section className={styles.materials} aria-label="已上传素材">
      {!!rows.length && <div className={styles.materialFilters}><div role="group" aria-label="素材类型">{[['all','全部'],['image','图片'],['video','视频']].map(([value,name]) => <button type="button" key={value} aria-pressed={filter === value} onClick={() => { setFilter(value); setShowAll(false); }}>{name}</button>)}</div><label className={styles.materialSearch}><Search size={14} /><input type="search" aria-label="搜索素材" placeholder="搜索名称、说明" value={query} onChange={event => setQuery(event.target.value)} /></label></div>}
      <p className={styles.materialCount} role="status">{rows.length ? `${matching.length} 份素材 · 已选 ${selected.length} 项` : materialMode === "speech" ? "尚未添加图片或视频，可直接继续" : "还没有补充素材"}</p>
      {!rows.length && <button type="button" className={styles.emptyMaterials} onClick={() => setAdding(true)}><Plus size={24} /><b>添加图片或视频</b><span>选与台词有关的商品、界面或资料</span></button>}
      {!!rows.length && !matching.length && <div className={styles.noMaterials}><Search size={22} /><p>没有找到相关素材</p><button type="button" onClick={() => { setFilter("all"); setQuery(""); }}>清除筛选</button></div>}
      <ul className={styles.materialTiles}>{visible.map(row => <li key={row.id} data-material-id={row.id} data-selected={selected.includes(row.id)}>
        <button type="button" className={styles.materialThumb} aria-label={`预览素材 · ${row.label}`} onClick={() => setPreview(row)}>{row.mime.startsWith("image/") ? <img src={row.url} alt={row.label} loading="lazy" decoding="async" /> : <span className={styles.videoPlaceholder}><FileVideo size={30} /><span>点击播放视频</span></span>}<span className={styles.mediaType}>{row.mime.startsWith("image/") ? <ImageIcon size={11} /> : <Play size={10} fill="currentColor" />}{row.mime.startsWith("image/") ? "图片" : `${((row.duration_ms || 0) / 1000).toFixed(1)}s`}</span>{selected.includes(row.id) && <span className={styles.materialSelected}><Check size={12} /></span>}</button>
        <label className={styles.materialSelect}><input type="checkbox" checked={selected.includes(row.id)} disabled={!selected.includes(row.id) && (selected.length >= 24 || (imagesOnly && !row.mime.startsWith("image/")))} onChange={event => onSelect(event.target.checked ? [...selected, row.id] : selected.filter(id => id !== row.id))} /><span>{row.label}{imagesOnly && !row.mime.startsWith("image/") && "（此模板使用图片）"}</span></label><p className={styles.materialDescription}>{row.description}</p>
      </li>)}</ul>
      {(hiddenCount > 0 || showAll) && <button type="button" className={styles.secondaryAction} onClick={() => setShowAll(value => !value)}>{showAll ? "收起其他素材" : `查看其他 ${hiddenCount} 份素材`}</button>}
      {offset !== null && <button type="button" disabled={busy} onClick={() => void more()}>加载更多素材</button>}
    </section>
    {preview && <Dialog title={preview.label} className={styles.materialPreviewDialog} onClose={() => setPreview(undefined)}><div className={styles.materialFullPreview}>{preview.mime.startsWith("image/") ? <img src={preview.url} alt={preview.label} /> : <video key={preview.id} src={preview.url} controls autoPlay muted playsInline aria-label={`${preview.label}素材预览`} />}</div><div className={styles.previewInfo}><p>{preview.description}</p><small>{preview.width} × {preview.height}{preview.duration_ms !== null && ` · ${(preview.duration_ms / 1000).toFixed(1)} 秒`}{preview.source_job_id && " · 来自已有创意图"}</small>{preview.feedback_observation && <p>已登记互动记录 · {preview.feedback_observation.label} · {preview.feedback_observation.likes} 赞 · {new Date(preview.feedback_observation.observed_at).toLocaleString()} · {preview.feedback_observation.source_ref}</p>}<a href={preview.url} target="_blank" rel="noreferrer">查看素材原件 <ArrowUpRight size={12} /></a></div></Dialog>}
  </div>;
}
