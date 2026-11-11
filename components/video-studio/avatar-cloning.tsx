"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowRight, Check, ImagePlus, LoaderCircle, Upload, Video } from "lucide-react";
import type { GenerationJob, useVideoLibrary } from "@/features/video-studio/library";
import type { UploadProgress } from "@/lib/api/upload";
import { ApiError } from "@/lib/api/api-error";
import { Dialog } from "./studio-primitives";
import styles from "./video-studio.module.css";
import cloneStyles from "./avatar-cloning.module.css";

export function AvatarCloneDialog({ library, userId, workspaceId, onClose, onCreated }: { library: ReturnType<typeof useVideoLibrary>; userId: string; workspaceId: string; onClose: () => void; onCreated: (job: GenerationJob) => void }) {
  const [kind, setKind] = useState<"image" | "video">("image");
  const [name, setName] = useState("");
  const [file, setFile] = useState<File>();
  const [preview, setPreview] = useState("");
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [attempted, setAttempted] = useState(false);
  const [upload, setUpload] = useState<UploadProgress>();
  const [error, setError] = useState("");
  const requestId = useRef("");
  const pendingKey = `polaris-avatar-creation:${userId}:${workspaceId}`;
  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview); }, [preview]);
  const submit = async () => {
    if (busy || !file || !name.trim() || !consent) return;
    if (!requestId.current) {
      try { requestId.current = sessionStorage.getItem(pendingKey) || crypto.randomUUID(); sessionStorage.setItem(pendingKey, requestId.current); } catch { requestId.current ||= crypto.randomUUID(); }
    }
    const original = library.jobs.find(job => job.request_id === requestId.current);
    if (original) { try { sessionStorage.removeItem(pendingKey); } catch {} onCreated(original); return; }
    setBusy(true); setAttempted(true); setError("");
    try {
      const result = await library.createAvatar(file, name.trim(), requestId.current, setUpload);
      try { sessionStorage.removeItem(pendingKey); } catch {}
      onCreated(result);
    } catch (reason) {
      if (reason instanceof ApiError && reason.status && reason.status >= 400 && reason.status < 500 && reason.status !== 409) {
        requestId.current = ""; setAttempted(false); setUpload(undefined);
        try { sessionStorage.removeItem(pendingKey); } catch {}
        setError(reason.message);
      } else setError("提交结果待确认。请核对原提交或在我的作品中查看进度。");
    } finally { setBusy(false); }
  };
  const percent = upload?.total ? Math.min(100, Math.round(upload.loaded / upload.total * 100)) : undefined;
  return <Dialog title="创建我的形象" onClose={onClose}>
    <p className={cloneStyles.intro}>一张清晰照片，或一段自然出镜的视频。</p>
    <div className={cloneStyles.tabs} role="tablist" aria-label="形象素材类型">{(["image", "video"] as const).map(value => <button key={value} type="button" role="tab" aria-selected={kind === value} disabled={busy || attempted} onClick={() => { if (kind === value) return; setKind(value); setFile(undefined); setPreview(""); setError(""); }}>{value === "image" ? <ImagePlus size={18} /> : <Video size={18} />}<span>{value === "image" ? "上传图片" : "上传视频"}</span><small>{value === "image" ? "从照片生成自然动作" : "保留你本人的出镜动作"}</small>{kind === value && <Check size={14} />}</button>)}</div>
    <label className={cloneStyles.name}>形象名称<input aria-label="形象名称" value={name} disabled={busy || attempted} maxLength={30} placeholder="给你的数字分身起个名字" onChange={event => setName(event.target.value)} /></label>
    <label className={`${cloneStyles.drop} ${file ? cloneStyles.selected : ""}`}>
      {file && preview ? kind === "image" ? <img src={preview} alt="所选形象图片" /> : <video src={preview} muted playsInline preload="metadata" /> : <span className={cloneStyles.uploadIcon}><Upload size={25} /></span>}
      <b>{file?.name || (kind === "image" ? "选择一张清晰照片" : "选择一段出镜视频")}</b>
      <span>{file ? "已选择素材 · 点击可更换" : kind === "image" ? "正面或微侧脸，面部无遮挡，光线均匀" : "单人出镜、机位稳定，保持自然动作"}</span>
      <input aria-label={kind === "image" ? "选择形象图片" : "选择形象视频"} type="file" disabled={busy || attempted} accept={kind === "image" ? ".jpg,.jpeg,.png,.webp,image/jpeg,image/png,image/webp" : ".mp4,.mov,.webm,video/mp4,video/quicktime,video/webm"} onChange={event => {
        const value = event.target.files?.[0]; if (!value) return;
        const valid = kind === "image" ? /\.(jpe?g|png|webp)$/i.test(value.name) : /\.(mp4|mov|webm)$/i.test(value.name);
        if (!valid || value.size > (kind === "image" ? 10 : 50) * 1024 * 1024) { setError(kind === "image" ? "请选择 10 MB 以内的 JPG、PNG 或 WebP 图片。" : "请选择 50 MB 以内的 MP4、MOV 或 WebM 视频。"); return; }
        setFile(value); setPreview(URL.createObjectURL(value)); setError("");
      }} />
    </label>
    <p className={cloneStyles.help}>{kind === "image" ? "JPG、PNG、WebP · 最大 10 MB · 边长至少 256 像素" : "MP4、MOV、WebM · 2～120 秒 · 最大 50 MB"}</p>
    <ol className={cloneStyles.flow} aria-label="形象创建流程">{[kind === "image" ? "上传照片" : "上传视频", kind === "image" ? "生成动作" : "检查素材", "预览确认", "加入形象库"].map((step,index) => <li key={step}><span>{index + 1}</span>{step}</li>)}</ol>
    <label className={cloneStyles.consent}><input type="checkbox" checked={consent} disabled={busy || attempted} onChange={event => setConsent(event.target.checked)} /><span>我拥有此形象的使用授权，同意处理该素材并创建专属数字人。</span></label>
    <p className={cloneStyles.help}>{kind === "image" ? "点击生成后会上传照片并调用动作生成服务，按实际用量计费；预览满意后再登记形象。" : "先上传预览，确认加入形象库时调用登记服务并计费。"}</p>
    {busy && <div className={cloneStyles.uploadProgress} role="status"><span><LoaderCircle size={15} />{upload?.complete ? "正在检查素材" : "正在上传素材"}<small>{percent === undefined ? "" : `${percent}%`}</small></span><progress aria-label="素材上传进度" max={100} value={upload?.complete ? undefined : percent} /></div>}
    {error && <p className={cloneStyles.error} role="alert">{error}</p>}
    <footer className={styles.dialogFooter}><button className={styles.outlineButton} type="button" disabled={busy} onClick={onClose}>取消</button><button className={styles.primaryButton} type="button" disabled={busy || !file || !name.trim() || !consent} onClick={() => { void submit(); }}>{busy ? <><LoaderCircle className={cloneStyles.spinner} size={16} />正在处理</> : <>{attempted ? "核对原提交" : kind === "image" ? "生成形象动作（计费）" : "上传并预览"}<ArrowRight size={15} /></>}</button></footer>
  </Dialog>;
}
