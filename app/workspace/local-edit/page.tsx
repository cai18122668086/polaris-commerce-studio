"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AlertCircle, Check, CheckCircle2, ImagePlus, Images, Info, LoaderCircle, RotateCcw, ShieldCheck, Sparkles, Upload } from "lucide-react";

import { AppShell } from "@/components/app-shell";
import { AssetLibraryDialog } from "@/components/asset-library-picker";
import { BeforeAfterResult } from "@/components/before-after-result";
import { HelpPanel } from "@/components/help-panel";
import { JobResultImage } from "@/components/job-result-image";
import { MaskEditor, normalizeRasterImage, type MaskEditorHandle } from "@/components/mask-editor";
import { StatusBadge } from "@/components/status-badge";
import { WorkspaceHeader } from "@/components/workspace-header";
import { useAssetAccessUrl, useUploadAsset } from "@/features/assets/api/assets";
import { useCreateJob, useJob, useRetryJob } from "@/features/jobs/api/jobs";
import { presentWorkflow, useRuntimeStatus } from "@/features/runtime/api/runtime";
import { useWorkspace } from "@/features/workspaces/api/workspaces";
import { errorMessage } from "@/lib/api/request";
import type { Asset } from "@/lib/api/types";
import { allowsJobAction } from "@/lib/jobs/actions";
import { jobNote } from "@/lib/jobs/presentation";
import { selectJobResultAssets } from "@/lib/jobs/results";
import workspaceStyles from "@/components/product-image-workspace.module.css";

export default function LocalEditPage() {
  const fileInput = useRef<HTMLInputElement>(null);
  const maskEditor = useRef<MaskEditorHandle>(null);
  const [prompt, setPrompt] = useState("");
  const [sourceAsset, setSourceAsset] = useState<Asset>();
  const [previewUrl, setPreviewUrl] = useState<string>();
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [hasSelection, setHasSelection] = useState(false);
  const [editorError, setEditorError] = useState<string>();
  const [jobId, setJobId] = useState<string>();
  const { workspace } = useWorkspace();
  const upload = useUploadAsset(workspace?.id);
  const sourceAccess = useAssetAccessUrl(
    workspace?.id,
    previewUrl ? undefined : sourceAsset?.id,
  );
  const sourceUrl = previewUrl ?? sourceAccess.data?.url;
  const createJob = useCreateJob(workspace?.id);
  const retryJob = useRetryJob(workspace?.id);
  const job = useJob(workspace?.id, jobId);
  const runtime = useRuntimeStatus();
  const workflow = presentWorkflow(runtime.data?.capabilities.local_edit);
  const workflowAvailable = workflow.mode === "mock" || workflow.mode === "provider";
  const resultAsset = selectJobResultAssets(job.data)[0];
  const rawCandidateAsset = job.data?.assets.find(
    (asset) =>
      asset.direction === "intermediate" && asset.role === "provider_raw",
  );
  const rawReviewSuccess = rawCandidateAsset?.validation.raw_visual_success;
  const rawReviewSummary =
    typeof rawCandidateAsset?.validation.visual_review_summary === "string"
      ? rawCandidateAsset.validation.visual_review_summary
      : undefined;

  useEffect(() => () => {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
  }, [previewUrl]);

  const onMaskChange = useCallback((selected: boolean) => {
    setHasSelection(selected);
    setEditorError(undefined);
  }, []);
  const onMaskError = useCallback((message?: string) => setEditorError(message), []);

  const onSourceFile = async (file?: File) => {
    if (!file) return;
    setSourceAsset(undefined);
    setHasSelection(false);
    setEditorError(undefined);
    setJobId(undefined);
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setPreviewUrl(undefined);
    try {
      const normalized = await normalizeRasterImage(file);
      setPreviewUrl(URL.createObjectURL(normalized));
      setSourceAsset(await upload.mutateAsync({ file: normalized, mediaKind: "image" }));
    } catch (error) {
      setEditorError(errorMessage(error));
    } finally {
      if (fileInput.current) fileInput.current.value = "";
    }
  };

  const submit = async () => {
    if (!sourceAsset || !hasSelection || !prompt.trim() || !workspace) return;
    setEditorError(undefined);
    try {
      const maskFile = await maskEditor.current?.exportMaskFile();
      if (!maskFile) throw new Error("蒙版编辑器尚未就绪。");
      const mask = await upload.mutateAsync({ file: maskFile, mediaKind: "mask" });
      const created = await createJob.mutateAsync({
        type: "local_edit",
        intent: "submit",
        display_name: `一句话改图 · ${sourceAsset.original_filename}`,
        input: { source_asset_id: sourceAsset.id, selection_mask_asset_id: mask.id },
        configuration: { instruction: prompt.trim(), output_format: "png", quality: "balanced" },
      });
      setJobId(created.id);
    } catch (error) {
      if (!(upload.error || createJob.error)) setEditorError(errorMessage(error));
    }
  };

  const retry = async () => {
    if (!job.data || !allowsJobAction(job.data.allowed_actions, "retry")) return;
    const retried = await retryJob.mutateAsync({
      jobId: job.data.id,
      allowedActions: job.data.allowed_actions,
      scope: "failed",
    });
    setJobId(retried.id);
  };

  const requestError = sourceAccess.error ?? upload.error ?? createJob.error ?? retryJob.error ?? job.error;
  const busy = upload.isPending || createJob.isPending || retryJob.isPending;
  const canRetry = job.data && allowsJobAction(job.data.allowed_actions, "retry");

  return (
    <AppShell flush>
      <div className="workspace-page">
        <div className="workspace-main">
          <WorkspaceHeader
            eyebrow={workflow.mode === "provider" ? "商品图工具 · 在线生成" : workflow.mode === "mock" ? "商品图工具 · 基础流程" : "商品图工具 · 服务状态确认中"}
            title="一句话改图"
            description={workflow.mode === "provider" ? "当前生成服务可用；提交任务后将开始图片处理。" : workflow.mode === "mock" ? "当前支持上传、蒙版编辑和任务保存，图片生成服务暂不可用。" : "当前无法确认生成服务状态，图片生成入口暂时关闭。"}
            meta={<span className="autosave-state"><ShieldCheck size={15} />{workflow.mode === "provider" ? "生成服务可用" : workflow.mode === "mock" ? "编辑功能可用" : "服务状态确认中"}</span>}
          />
          <div className="workflow-steps">
            {["上传原图", "绘制选区", "创建任务", "查看结果"].map((step, index) => {
              const current = !sourceAsset ? 0 : !hasSelection ? 1 : !jobId ? 2 : 3;
              return <div key={step} className={index < current ? "done" : index === current ? "active" : ""}><i>{index < current ? <Check size={14} /> : index + 1}</i><span>{step}</span>{index < 3 && <em />}</div>;
            })}
          </div>

          <div className="local-edit-layout">
            <section className="editor-card">
              <MaskEditor ref={maskEditor} sourceUrl={sourceUrl} sourceName={sourceAsset?.original_filename} onChange={onMaskChange} onError={onMaskError} />
            </section>

            <aside className="edit-controls">
              <section className="control-card control-card--source">
                <div className="control-card__heading"><span>1</span><div><strong>原始图片</strong><p>{sourceAsset ? `${sourceAsset.width} × ${sourceAsset.height} 标准化画布` : "选择 JPG / PNG / WEBP"}</p></div></div>
                <div className={`${workspaceStyles.uploadActions} local-edit-upload-actions`} data-has-library>
                  <button type="button" onClick={() => fileInput.current?.click()} disabled={!workspace || upload.isPending}>
                    {upload.isPending ? <LoaderCircle className="spin" size={15} /> : <Upload size={15} />}
                    {sourceAsset ? "重新上传" : "上传图片"}
                  </button>
                  <button type="button" data-library aria-haspopup="dialog" onClick={() => setLibraryOpen(true)} disabled={!workspace || upload.isPending}>
                    <Images size={15} />
                    从素材库选择
                  </button>
                </div>
                <input ref={fileInput} className="visually-hidden" type="file" accept="image/jpeg,image/png,image/webp" onChange={(event) => void onSourceFile(event.target.files?.[0])} />
              </section>
              <section className="control-card">
                <div className="control-card__heading"><span>2</span><div><strong>修改要求</strong><p>蒙版外像素会由服务端锁定</p></div></div>
                <div className="textarea-wrap"><textarea value={prompt} placeholder="例如：将授权选区改为深灰色磨砂金属，保留商品结构与光影。" maxLength={500} onChange={(event) => setPrompt(event.target.value)} aria-label="修改要求" /><span>{prompt.length} / 500</span></div>
              </section>
              <div className="cost-bar"><span>本次服务<Info size={14} /></span><strong>{workflow.mode === "provider" ? "在线生成 · 按套餐计费" : workflow.mode === "mock" ? "任务保存 · 暂不生成图片" : "生成服务暂不可用"}</strong></div>
              {(requestError || editorError) && <div className="generation-feedback error" role="alert"><span><AlertCircle size={16} /></span><div><strong>请求未完成</strong><p>{editorError ?? errorMessage(requestError ?? new Error("未知错误"))}</p></div></div>}
              {job.data && <div className={`generation-feedback ${["failed", "partial"].includes(job.data.status) ? "error" : job.data.status === "completed" ? "success" : "active"}`} aria-live="polite"><span>{job.data.status === "completed" ? <CheckCircle2 size={16} /> : <LoaderCircle size={16} className={["queued", "planning", "processing"].includes(job.data.status) ? "spin" : ""} />}</span><div><strong><StatusBadge status={job.data.status} /></strong><p>{jobNote(job.data)} · {job.data.progress}%</p></div></div>}
              {rawCandidateAsset && (
                <div className={`generation-feedback ${rawReviewSuccess === true ? "success" : rawReviewSuccess === false ? "error" : "active"}`}>
                  <span>{rawReviewSuccess === true ? <CheckCircle2 size={16} /> : <ShieldCheck size={16} />}</span>
                  <div>
                    <strong>{rawReviewSuccess === true ? "视觉验收通过" : rawReviewSuccess === false ? "视觉验收未通过" : "视觉验收未完成"}</strong>
                    <p>{rawReviewSummary ?? "原始候选已保留；只有验收通过的严格合成结果才可交付。"}</p>
                  </div>
                </div>
              )}
              {canRetry ? (
                <button className="primary-button generate-button" onClick={() => void retry()} disabled={retryJob.isPending}>{retryJob.isPending ? <LoaderCircle className="spin" size={17} /> : <RotateCcw size={17} />}重试失败项目</button>
              ) : (
                <button className="primary-button generate-button" onClick={() => void submit()} disabled={!workflowAvailable || !sourceAsset || !hasSelection || !prompt.trim() || busy} aria-busy={busy}>
                  {busy ? <LoaderCircle className="spin" size={17} /> : <Sparkles size={17} />}{busy ? "正在创建任务" : workflow.mode === "provider" ? "开始生成" : workflow.mode === "mock" ? "保存任务" : "服务状态确认中，暂不可创建"}
                </button>
              )}
              <p className="privacy-line"><ShieldCheck size={13} />黑色区域锁定，白色区域授权；服务端仍会校验尺寸与像素锁。</p>
            </aside>
          </div>

          {resultAsset && sourceUrl && <section className="result-preview-card"><div className="planning-head"><div><span className="number-chip number-chip--violet">4</span><div><h2>生成结果</h2><p>拖动滑块对比原图与生成结果。</p></div></div></div><BeforeAfterResult workspaceId={workspace?.id} sourceUrl={sourceUrl} assetId={resultAsset.asset_id} /></section>}
          {rawCandidateAsset && <section className="detail-form-card"><div className="form-section-head"><span className="number-chip number-chip--violet">R</span><div><h2>原始生成候选</h2><p>仅供视觉诊断，不是像素锁定后的可交付结果。</p></div></div><div className="job-results-grid"><JobResultImage workspaceId={workspace?.id} assetId={rawCandidateAsset.asset_id} alt="一句话改图原始候选" label="原始候选 · 不可交付" /></div></section>}
          {job.data?.status === "completed" && workflow.mode === "mock" && !resultAsset && <div className="api-state"><ImagePlus size={22} /><p>任务流程已完成，当前生成服务未返回图片结果。</p></div>}
        </div>
        {libraryOpen ? (
          <AssetLibraryDialog
            workspaceId={workspace?.id}
            title="选择原始图片"
            description="选择需要进行一句话改图的图片。"
            selectedIds={sourceAsset ? [sourceAsset.id] : []}
            maxItems={1}
            disabled={upload.isPending}
            onClose={() => setLibraryOpen(false)}
            onConfirm={(_, assets) => {
              const selectedAsset = assets[0];
              if (!selectedAsset) return;
              setSourceAsset(selectedAsset);
              setHasSelection(false);
              setEditorError(undefined);
              setJobId(undefined);
              if (previewUrl) URL.revokeObjectURL(previewUrl);
              setPreviewUrl(undefined);
              setLibraryOpen(false);
            }}
          />
        ) : null}
        <HelpPanel
          mode="local-edit"
          taskTitle={prompt.trim() || "等待填写修改要求"}
          assetSummary={!sourceAsset ? "尚未上传" : hasSelection ? "1 张 · 已选区" : "1 张 · 待绘制选区"}
        />
      </div>
    </AppShell>
  );
}
