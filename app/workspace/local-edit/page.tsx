"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AlertCircle, Check, CheckCircle2, ImagePlus, Images, Info, LoaderCircle, RotateCcw, ShieldCheck, Sparkles, Upload } from "lucide-react";

import { ImageDropZone } from "@/components/image-drop-zone";
import { JobProgressFeedback } from "@/components/job-progress-feedback";
import { AppShell } from "@/components/app-shell";
import { WorkspaceJobGate } from "@/components/workspace-job-gate";
import { useWorkspaceJobId } from "@/lib/jobs/use-workspace-job-id";
import { workspaceJobSnapshot } from "@/lib/jobs/workspace-restore";
import { AssetLibraryDialog } from "@/components/asset-library-picker";
import { BeforeAfterResult } from "@/components/before-after-result";
import { HelpPanel } from "@/components/help-panel";
import { JobResultImage } from "@/components/job-result-image";
import { MaskEditor, normalizeRasterImage, type MaskEditorHandle } from "@/components/mask-editor";
import { WorkspaceHeader } from "@/components/workspace-header";
import { useAsset, useAssetAccessUrl, useUploadAsset } from "@/features/assets/api/assets";
import { useCreateJob, useJob, useRetryJob } from "@/features/jobs/api/jobs";
import { presentWorkflow, useRuntimeStatus } from "@/features/runtime/api/runtime";
import { useWorkspace } from "@/features/workspaces/api/workspaces";
import { errorMessage } from "@/lib/api/request";
import { IMAGE_UPLOAD_FORMAT_HINT } from "@/lib/image-upload";
import type { Asset } from "@/lib/api/types";
import { allowsJobAction } from "@/lib/jobs/actions";
import { selectJobResultAssets } from "@/lib/jobs/results";
import workspaceStyles from "@/components/product-image-workspace.module.css";

export default function LocalEditPage() {
  const fileInput = useRef<HTMLInputElement>(null);
  const maskEditor = useRef<MaskEditorHandle>(null);
  const [draftPrompt, setPrompt] = useState("");
  const [draftQuality, setQuality] = useState<"preview" | "balanced" | "final" | "auto">("balanced");
  const [draftExecutionPath, setExecutionPath] = useState<"auto" | "deterministic" | "hybrid" | "cropped" | "full">("auto");
  const [draftSourceAsset, setSourceAsset] = useState<Asset>();
  const [previewUrl, setPreviewUrl] = useState<string>();
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [hasSelection, setHasSelection] = useState(false);
  const [editorError, setEditorError] = useState<string>();
  const { workspace } = useWorkspace();
  const [jobId, setJobId] = useWorkspaceJobId("/workspace/local-edit");
  const job = useJob(workspace?.id, jobId);
  const saved = workspaceJobSnapshot(job.data);
  const restoredSourceId = saved.id("source_asset_id");
  const restoredMaskId = saved.id("selection_mask_asset_id");
  const restoredSource = useAsset(workspace?.id, jobId ? restoredSourceId : undefined);
  const sourceAsset = jobId ? restoredSource.data : draftSourceAsset;
  const prompt = jobId ? saved.text("instruction") : draftPrompt;
  const quality = jobId ? saved.choice("quality", ["preview", "balanced", "final", "auto"], "balanced") : draftQuality;
  const executionPath = jobId ? saved.choice("execution_path", ["auto", "deterministic", "hybrid", "cropped", "full"], "auto") : draftExecutionPath;
  const upload = useUploadAsset(workspace?.id);
  const sourceAccess = useAssetAccessUrl(
    workspace?.id,
    !jobId && previewUrl ? undefined : sourceAsset?.id,
  );
  const sourceUrl = jobId ? sourceAccess.data?.url : previewUrl ?? sourceAccess.data?.url;
  const createJob = useCreateJob(workspace?.id);
  const retryJob = useRetryJob(workspace?.id);
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
    if (jobId || !sourceAsset || !hasSelection || !prompt.trim() || !workspace) return;
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
        // Legacy contract shape: configuration: { instruction: prompt.trim(), output_format: "png", quality: "balanced" }
        configuration: {
          instruction: prompt.trim(),
          output_format: "png",
          quality,
          execution_path: executionPath,
        },
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

  const requestError = restoredSource.error ?? sourceAccess.error ?? upload.error ?? createJob.error ?? retryJob.error ?? job.error;
  const busy = upload.isPending || createJob.isPending || retryJob.isPending;
  const canRetry = job.data && allowsJobAction(job.data.allowed_actions, "retry");

  return (
    <WorkspaceJobGate jobId={jobId} job={job.data} error={job.error} onRetry={() => void job.refetch()} expectedType="local_edit">
    <AppShell flush>
      <div className="workspace-page">
        <div className="workspace-main">
          <WorkspaceHeader
          jobId={jobId}
            eyebrow={jobId ? "商品图工具 · 已保存任务" : workflow.mode === "provider" ? "商品图工具 · 在线生成" : workflow.mode === "mock" ? "商品图工具 · 基础流程" : "商品图工具 · 服务状态确认中"}
            title="一句话改图"
            description={jobId ? "查看本次任务保存的原图、授权蒙版、修改要求和生成结果。" : workflow.mode === "provider" ? "当前生成服务可用；提交任务后将开始图片处理。" : workflow.mode === "mock" ? "当前支持上传、蒙版编辑和任务保存，图片生成服务暂不可用。" : "当前无法确认生成服务状态，图片生成入口暂时关闭。"}
            meta={<span className="autosave-state"><ShieldCheck size={15} />{workflow.mode === "provider" ? "生成服务可用" : workflow.mode === "mock" ? "编辑功能可用" : "服务状态确认中"}</span>}
          />
          <div className="workflow-steps">
            {["上传原图", "绘制选区", "创建任务", "查看结果"].map((step, index) => {
              const current = jobId ? 3 : !sourceAsset ? 0 : !hasSelection ? 1 : 2;
              return <div key={step} className={index < current ? "done" : index === current ? "active" : ""}><i>{index < current ? <Check size={14} /> : index + 1}</i><span>{step}</span>{index < 3 && <em />}</div>;
            })}
          </div>

          <div className="local-edit-layout">
            <section className="editor-card">
              {jobId ? <div className="job-asset-grid">
                {restoredSourceId && <JobResultImage workspaceId={workspace?.id} assetId={restoredSourceId} alt="任务原始图片" label="任务原始图片" />}
                {restoredMaskId && <JobResultImage workspaceId={workspace?.id} assetId={restoredMaskId} alt="任务授权蒙版" label="任务授权蒙版 · 白色为授权区域" />}
              </div> : <MaskEditor ref={maskEditor} sourceUrl={sourceUrl} sourceName={sourceAsset?.original_filename} onChange={onMaskChange} onError={onMaskError} />}
            </section>

            <aside className="edit-controls">
              <ImageDropZone as="section" label="局部改图原始图片" className="control-card control-card--source"
                inputRef={fileInput} disabled={!workspace || Boolean(jobId) || createJob.isPending} busy={upload.isPending}
                onFiles={(files) => onSourceFile(files[0])}>
                {({ openFileDialog, disabled: uploadDisabled, busy: uploadingFile }) => <>
                  <div className="control-card__heading"><span>1</span><div><strong>原始图片</strong><p>{sourceAsset ? `${sourceAsset.width} × ${sourceAsset.height} 标准化画布` : IMAGE_UPLOAD_FORMAT_HINT}</p></div></div>
                  <div className={`${workspaceStyles.uploadActions} local-edit-upload-actions`} data-has-library>
                    <button type="button" onClick={openFileDialog} disabled={uploadDisabled}>
                      {uploadingFile ? <LoaderCircle className="spin" size={15} /> : <Upload size={15} />}
                      {sourceAsset ? "重新上传" : "上传图片"}
                    </button>
                    <button type="button" data-library aria-haspopup="dialog" onClick={() => setLibraryOpen(true)} disabled={!workspace || Boolean(jobId) || uploadingFile || createJob.isPending}>
                      <Images size={15} />
                      从素材库选择
                    </button>
                  </div>
                </>}
              </ImageDropZone>
              <section className="control-card">
                <div className="control-card__heading"><span>2</span><div><strong>修改要求</strong><p>蒙版外像素会由服务端锁定</p></div></div>
                <div className="textarea-wrap"><textarea disabled={Boolean(jobId)} value={prompt} placeholder="例如：将授权选区改为深灰色磨砂金属，保留商品结构与光影。" maxLength={500} onChange={(event) => setPrompt(event.target.value)} aria-label="修改要求" /><span>{prompt.length} / 500</span></div>
              </section>
              <section className="control-card local-edit-options">
                <div className="control-card__heading"><span>3</span><div><strong>生成路径</strong><p>按 Skill 选择速度与细节</p></div></div>
                <div className="local-edit-option-grid">
                  <label>质量
                    <select disabled={Boolean(jobId)} value={quality} onChange={(event) => setQuality(event.target.value as typeof quality)} aria-label="生成质量">
                      <option value="preview">快速预览</option>
                      <option value="balanced">平衡</option>
                      <option value="final">最终质量</option>
                      <option value="auto">自动</option>
                    </select>
                  </label>
                  <label>执行路径
                    <select disabled={Boolean(jobId)} value={executionPath} onChange={(event) => setExecutionPath(event.target.value as typeof executionPath)} aria-label="执行路径">
                      <option value="auto">自动选择</option>
                      <option value="cropped">局部裁剪</option>
                      <option value="hybrid">混合修复</option>
                      <option value="deterministic">确定性修复</option>
                      <option value="full">全画布模型</option>
                    </select>
                  </label>
                </div>
              </section>
              <div className="cost-bar"><span>本次服务<Info size={14} /></span><strong>{jobId ? "已保存任务 · 输入参数已锁定" : workflow.mode === "provider" ? "在线生成 · 按套餐计费" : workflow.mode === "mock" ? "任务保存 · 暂不生成图片" : "生成服务暂不可用"}</strong></div>
              {(requestError || editorError) && <div className="generation-feedback error" role="alert"><span><AlertCircle size={16} /></span><div><strong>请求未完成</strong><p>{editorError ?? errorMessage(requestError ?? new Error("未知错误"))}</p></div></div>}
              <JobProgressFeedback job={job.data} pending={createJob.isPending} error={job.error}
                lastSyncedAt={job.dataUpdatedAt} refreshing={job.isFetching} onRefresh={jobId ? () => void job.refetch() : undefined} />
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
                <button className="primary-button generate-button" onClick={() => void submit()} disabled={Boolean(jobId) || !workflowAvailable || !sourceAsset || !hasSelection || !prompt.trim() || busy} aria-busy={busy}>
                  {busy ? <LoaderCircle className="spin" size={17} /> : <Sparkles size={17} />}{jobId ? "当前为已保存任务" : busy ? "正在创建任务" : workflow.mode === "provider" ? "开始生成" : workflow.mode === "mock" ? "保存任务" : "服务状态确认中，暂不可创建"}
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
        {!jobId && <HelpPanel
          mode="local-edit"
          taskTitle={prompt.trim() || "等待填写修改要求"}
          assetSummary={!sourceAsset ? "尚未上传" : hasSelection ? "1 张 · 已选区" : "1 张 · 待绘制选区"}
        />}
      </div>
    </AppShell>
    </WorkspaceJobGate>
  );
}
