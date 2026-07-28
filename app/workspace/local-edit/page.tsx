"use client";

import { useEffect, useRef, useState } from "react";
import {
  AlertCircle,
  Brush,
  Check,
  CheckCircle2,
  ImagePlus,
  Info,
  LoaderCircle,
  RotateCcw,
  ShieldCheck,
  Sparkles,
  Upload,
} from "lucide-react";

import { AppShell } from "@/components/app-shell";
import { HelpPanel } from "@/components/help-panel";
import { StatusBadge } from "@/components/status-badge";
import { WorkspaceHeader } from "@/components/workspace-header";
import { useUploadAsset } from "@/features/assets/api/assets";
import { useCreateJob, useJob } from "@/features/jobs/api/jobs";
import { useWorkspace } from "@/features/workspaces/api/workspaces";
import { errorMessage } from "@/lib/api/request";
import type { Asset } from "@/lib/api/types";
import { jobNote } from "@/lib/jobs/presentation";

const qualities = [
  { key: "preview", label: "快速预览", desc: "mock runner", cost: "不计费" },
  { key: "balanced", label: "均衡", desc: "mock runner", cost: "不计费" },
  { key: "final", label: "最终质量", desc: "mock runner", cost: "不计费" },
] as const;

async function createMaskFile(): Promise<File> {
  const canvas = document.createElement("canvas");
  canvas.width = 512;
  canvas.height = 512;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("浏览器无法创建选区蒙版。");
  context.fillStyle = "#000";
  context.fillRect(0, 0, 512, 512);
  context.fillStyle = "#fff";
  context.beginPath();
  context.ellipse(330, 260, 110, 150, 0, 0, Math.PI * 2);
  context.fill();
  const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/png"));
  if (!blob) throw new Error("选区蒙版编码失败。");
  return new File([blob], "selection-mask.png", { type: "image/png" });
}

export default function LocalEditPage() {
  const fileInput = useRef<HTMLInputElement>(null);
  const [quality, setQuality] = useState<"preview" | "balanced" | "final">("final");
  const [prompt, setPrompt] = useState("将授权选区改为深灰色磨砂金属，保留商品结构与光影。");
  const [sourceAsset, setSourceAsset] = useState<Asset>();
  const [previewUrl, setPreviewUrl] = useState<string>();
  const [selectionConfirmed, setSelectionConfirmed] = useState(false);
  const [jobId, setJobId] = useState<string>();
  const { workspace } = useWorkspace();
  const upload = useUploadAsset(workspace?.id);
  const createJob = useCreateJob(workspace?.id);
  const job = useJob(workspace?.id, jobId);

  useEffect(() => () => { if (previewUrl) URL.revokeObjectURL(previewUrl); }, [previewUrl]);

  const onSourceFile = (file?: File) => {
    if (!file) return;
    setSelectionConfirmed(false);
    setJobId(undefined);
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setPreviewUrl(URL.createObjectURL(file));
    upload.mutate(
      { file, mediaKind: "image" },
      { onSuccess: (asset) => setSourceAsset(asset) },
    );
  };

  const submit = async () => {
    if (!sourceAsset || !selectionConfirmed || !prompt.trim() || !workspace) return;
    try {
      const mask = await upload.mutateAsync({ file: await createMaskFile(), mediaKind: "mask" });
      const created = await createJob.mutateAsync({
        type: "local_edit",
        intent: "submit",
        display_name: `局部修改 · ${sourceAsset.original_filename}`,
        input: { source_asset_id: sourceAsset.id, selection_mask_asset_id: mask.id },
        configuration: { instruction: prompt.trim(), output_format: "png", quality },
      });
      setJobId(created.id);
    } catch {
      // Mutations expose the mapped error below.
    }
  };

  const requestError = upload.error ?? createJob.error ?? job.error;
  const busy = upload.isPending || createJob.isPending;

  return (
    <AppShell flush>
      <div className="workspace-page">
        <div className="workspace-main">
          <WorkspaceHeader
            eyebrow="商品图工具 · 内部 mock"
            title="局部修改"
            description="上传与任务状态使用真实 API；本轮不会调用图片 Provider，也不会产生真实生成结果。"
            meta={<span className="autosave-state"><ShieldCheck size={15} />零付费 mock runner</span>}
          />
          <div className="workflow-steps">
            {["上传原图", "确认选区", "创建任务", "观察状态"].map((step, index) => {
              const current = !sourceAsset ? 0 : !selectionConfirmed ? 1 : !jobId ? 2 : 3;
              return <div key={step} className={index < current ? "done" : index === current ? "active" : ""}><i>{index < current ? <Check size={14} /> : index + 1}</i><span>{step}</span>{index < 3 && <em />}</div>;
            })}
          </div>

          <div className="local-edit-layout">
            <section className="editor-card">
              <div className="card-toolbar">
                <div className="toolbar-group"><button className="active" aria-label="画笔工具"><Brush size={17} /></button></div>
                <strong>{sourceAsset ? sourceAsset.original_filename : "等待上传原图"}</strong>
              </div>
              <div className="image-editor">
                <button
                  className="canvas-frame tool-brush"
                  onClick={() => sourceAsset && setSelectionConfirmed((value) => !value)}
                  disabled={!sourceAsset}
                  aria-pressed={selectionConfirmed}
                >
                  {previewUrl ? (
                    <div className="canvas-content"><img src={previewUrl} alt="待修改的上传商品图" />{selectionConfirmed && <div className="mask-shape mask-shape--right" />} {selectionConfirmed && <div className="selection-outline"><span className="selection-label"><Brush size={13} />已授权示例选区</span></div>}</div>
                  ) : (
                    <div className="empty-state"><ImagePlus size={30} /><h3>先上传商品原图</h3><p>上传成功后可点击画布确认本轮示例选区。</p></div>
                  )}
                </button>
                <div className="canvas-status"><span className="safe"><ShieldCheck size={14} />{selectionConfirmed ? "选区已授权" : "尚未授权选区"}</span></div>
              </div>
            </section>

            <aside className="edit-controls">
              <section className="control-card">
                <div className="control-card__heading"><span>1</span><div><strong>原始图片</strong><p>{sourceAsset ? "已写入资产 API" : "选择 JPG / PNG / WEBP"}</p></div></div>
                <button className="link-button" onClick={() => fileInput.current?.click()} disabled={!workspace || upload.isPending}>
                  {upload.isPending ? <LoaderCircle className="spin" size={15} /> : <Upload size={15} />}{sourceAsset ? "重新上传" : "上传素材"}
                </button>
                <input ref={fileInput} className="visually-hidden" type="file" accept="image/*" onChange={(event) => onSourceFile(event.target.files?.[0])} />
              </section>
              <section className="control-card">
                <div className="control-card__heading"><span>2</span><div><strong>修改要求</strong><p>会作为真实任务配置保存</p></div></div>
                <div className="textarea-wrap"><textarea value={prompt} maxLength={500} onChange={(event) => setPrompt(event.target.value)} aria-label="修改要求" /><span>{prompt.length} / 500</span></div>
              </section>
              <section className="control-card">
                <div className="control-card__heading"><span>3</span><div><strong>质量标签</strong><p>仅供 mock 任务契约验证</p></div></div>
                <div className="quality-options">
                  {qualities.map((item) => <button key={item.key} className={quality === item.key ? "selected" : ""} onClick={() => setQuality(item.key)}><i>{quality === item.key && <Check size={12} />}</i><span><strong>{item.label}</strong><small>{item.desc}</small></span><em>{item.cost}</em></button>)}
                </div>
              </section>
              <div className="cost-bar"><span>本次环境<Info size={14} /></span><strong>零付费 mock</strong></div>
              {requestError && <div className="generation-feedback error" role="alert"><span><AlertCircle size={16} /></span><div><strong>请求未完成</strong><p>{errorMessage(requestError)}</p></div></div>}
              {job.data && <div className={`generation-feedback ${job.data.status === "failed" ? "error" : job.data.status === "completed" ? "success" : "active"}`} aria-live="polite"><span>{job.data.status === "completed" ? <CheckCircle2 size={16} /> : <LoaderCircle size={16} className={["queued", "planning", "processing"].includes(job.data.status) ? "spin" : ""} />}</span><div><strong><StatusBadge status={job.data.status} /></strong><p>{jobNote(job.data)} · {job.data.progress}%</p>{["queued", "planning", "processing"].includes(job.data.status) && <i><span style={{ width: `${job.data.progress}%` }} /></i>}</div></div>}
              <button className="primary-button generate-button" onClick={() => void submit()} disabled={!sourceAsset || !selectionConfirmed || !prompt.trim() || busy} aria-busy={busy}>
                {busy ? <LoaderCircle className="spin" size={17} /> : jobId ? <RotateCcw size={17} /> : <Sparkles size={17} />}
                {busy ? "正在写入 API" : jobId ? "创建新的 mock 任务" : "创建内部 mock 任务"}
              </button>
              <p className="privacy-line"><ShieldCheck size={13} />不会调用真实 Provider；页面不会展示伪造的生成图。</p>
            </aside>
          </div>
        </div>
        <HelpPanel mode="local-edit" />
      </div>
    </AppShell>
  );
}
