"use client";
import { useDraftState } from "@/lib/hooks/use-creation-draft";

import { CreditCostHint } from "@/features/billing/components/credit-account";

import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { assetHandoffKey } from "@/lib/assets/creation-handoff";
import { useAssetHandoff } from "@/features/assets/hooks/use-asset-handoff";
import { AlertCircle, Images, LoaderCircle, ShieldCheck, Sparkles, Upload } from "lucide-react";

import { ImageDropZone } from "@/components/image-drop-zone";
import { AppShell } from "@/components/app-shell";
import { WorkspaceJobGate } from "@/components/workspace-job-gate";
import { useWorkspaceJobId } from "@/lib/jobs/use-workspace-job-id";
import { workspaceJobSnapshot } from "@/lib/jobs/workspace-restore";
import { AssetLibraryDialog } from "@/components/asset-library-picker";
import { LocalEditReview } from "@/components/local-edit-review";
import { MaskEditor, normalizeRasterImage, type MaskEditorHandle } from "@/components/mask-editor";
import { WorkspaceHeader } from "@/components/workspace-header";
import { useAsset, useAssetAccessUrl, useUploadAsset } from "@/features/assets/api/assets";
import { useCreateJob, useJob } from "@/features/jobs/api/jobs";
import { presentWorkflow, useRuntimeStatus } from "@/features/runtime/api/runtime";
import { useWorkspace } from "@/features/workspaces/api/workspaces";
import { errorMessage } from "@/lib/api/request";
import { IMAGE_UPLOAD_FORMAT_HINT } from "@/lib/image-upload";
import type { Asset } from "@/lib/api/types";
import workspaceStyles from "@/components/product-image-workspace.module.css";

export default function LocalEditPage() {
  const search = useSearchParams();
  return <LocalEditWorkspace key={assetHandoffKey(search)} />;
}

function LocalEditWorkspace() {
  const fileInput = useRef<HTMLInputElement>(null);
  const maskEditor = useRef<MaskEditorHandle>(null);
  const { workspace } = useWorkspace();
  const [draftPrompt, setDraftPrompt] = useDraftState(workspace?.id, "local-edit", "prompt", "");
  const [promptEdited, setPromptEdited] = useState(false);
  const setPrompt = (value: string) => { setDraftPrompt(value); setPromptEdited(true); };
  const [sourceOverridden, setSourceOverridden] = useState(false);
  const [draftSourceAsset, setSourceAsset] = useState<Asset>();
  const [previewUrl, setPreviewUrl] = useState<string>();
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [hasSelection, setHasSelection] = useState(false);
  const [editorError, setEditorError] = useState<string>();
  const [jobId, setJobId] = useWorkspaceJobId("/workspace/local-edit");
  const handoff = useAssetHandoff(workspace?.id, 1, jobId);
  const job = useJob(workspace?.id, jobId);
  const saved = workspaceJobSnapshot(job.data);
  const restoredSourceId = saved.id("source_asset_id");
  const restoredSource = useAsset(workspace?.id, jobId ? restoredSourceId : undefined);
  const sourceAsset = jobId ? restoredSource.data : draftSourceAsset ?? (!sourceOverridden ? handoff.data?.sources[0]?.asset : undefined);
  const prompt = jobId ? saved.text("instruction") : promptEdited ? draftPrompt : handoff.data?.instruction ?? draftPrompt;
  const upload = useUploadAsset(workspace?.id);
  const sourceAccess = useAssetAccessUrl(
    workspace?.id,
    !jobId && previewUrl ? undefined : sourceAsset?.id,
  );
  const sourceUrl = jobId ? sourceAccess.data?.url : previewUrl ?? sourceAccess.data?.url;
  const createJob = useCreateJob(workspace?.id);
  const runtime = useRuntimeStatus();
  const workflow = presentWorkflow(runtime.data?.capabilities.local_edit);
  const workflowAvailable = workflow.mode === "mock" || workflow.mode === "provider";

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
    setSourceOverridden(true);
    setSourceAsset(undefined);
    setHasSelection(false);
    setEditorError(undefined);
    if (jobId) setJobId(undefined);
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
        inspiration_case_id: handoff.data?.caseId,
        intent: "submit",
        display_name: `一句话改图 · ${sourceAsset.original_filename}`,
        input: { source_asset_id: sourceAsset.id, selection_mask_asset_id: mask.id },
        configuration: { instruction: prompt.trim(), output_format: "png", quality: "balanced", execution_path: "auto" },
      });
      setJobId(created.id);
    } catch (error) {
      if (!(upload.error || createJob.error)) setEditorError(errorMessage(error));
    }
  };

  const requestError = handoff.error ?? restoredSource.error ?? sourceAccess.error ?? upload.error ?? createJob.error ?? job.error;
  const busy = handoff.loading || upload.isPending || createJob.isPending;

  const revise = () => {
    if (sourceAsset) setSourceAsset(sourceAsset);
    setSourceOverridden(true);
    setPrompt(prompt);
    setJobId(undefined);
    setHasSelection(false);
    setEditorError(undefined);
  };

  return (
    <WorkspaceJobGate jobId={jobId} job={job.data} error={job.error} onRetry={() => void job.refetch()} expectedType="local_edit">
    <AppShell flush>
      <div className="workspace-page local-edit-page">
        <div className="workspace-main">
          <WorkspaceHeader
          jobId={jobId}
            eyebrow="商品图工具"
            title="一句话改图"
            description={jobId ? "选择效果，或调整要求再生成。" : workflow.mode === "provider" ? "圈选位置，描述修改。" : workflow.mode === "mock" ? "当前支持上传、蒙版编辑和任务保存，暂不生成图片。" : "生成服务暂不可用，请稍后重试。"}
          />

          {!jobId && <div className="local-edit-layout">
            <section className="editor-card">
              <MaskEditor ref={maskEditor} sourceUrl={sourceUrl} sourceName={sourceAsset?.original_filename} onChange={onMaskChange} onError={onMaskError} />
            </section>

            <aside className="edit-controls">
              <ImageDropZone as="section" label="局部改图原始图片" className="control-card control-card--source"
                inputRef={fileInput} disabled={!workspace || Boolean(jobId) || busy || createJob.isPending} busy={upload.isPending}
                onFiles={(files) => onSourceFile(files[0])}>
                {({ openFileDialog, disabled: uploadDisabled, busy: uploadingFile }) => <>
                  <div className="control-card__heading"><span>1</span><div><strong>原始图片</strong><p>{sourceAsset ? `${sourceAsset.width} × ${sourceAsset.height}` : IMAGE_UPLOAD_FORMAT_HINT}</p></div></div>
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
                <div className="control-card__heading"><span>2</span><div><strong>修改要求</strong></div></div>
                <div className="textarea-wrap"><textarea disabled={busy} value={prompt} placeholder="例如：把标题改为“清爽保湿”，保持字体和位置。" maxLength={500} onChange={(event) => setPrompt(event.target.value)} aria-label="修改要求" /><span>{prompt.length} / 500</span></div>
                {!jobId && <div className="local-edit-examples" aria-label="修改要求示例">
                  {[
                    ["换颜色", "将选区改为奶油白色，保留原有纹理、商品结构和自然光影。"],
                    ["换材质", "将选区改为深灰色磨砂金属，保留商品轮廓、结构与光影。"],
                    ["去杂物", "移除选区内的杂物，用周围背景自然补齐，保持光线与纹理一致。"],
                  ].map(([label, value]) => <button key={label} type="button" disabled={busy} aria-pressed={prompt === value} onClick={() => setPrompt(value)}>{label}</button>)}
                </div>}
              </section>
              <div className="cost-bar"><span>本次生成</span><CreditCostHint jobType="local_edit" count={1} fallback={<strong>{workflow.mode === "provider" ? "按套餐计费" : workflow.mode === "mock" ? "暂不生成图片" : "生成服务暂不可用"}</strong>} /></div>
              {(requestError || editorError) && <div className="generation-feedback error" role="alert"><span><AlertCircle size={16} /></span><div><strong>请求未完成</strong><p>{editorError ?? errorMessage(requestError ?? new Error("未知错误"))}</p></div></div>}
                <button className="primary-button generate-button" onClick={() => void submit()} disabled={Boolean(jobId) || !workflowAvailable || !sourceAsset || !hasSelection || !prompt.trim() || busy} aria-busy={busy}>
                  {busy ? <LoaderCircle className="spin" size={17} /> : <Sparkles size={17} />}{busy ? "正在创建任务" : workflow.mode === "provider" ? "开始生成" : workflow.mode === "mock" ? "保存任务" : "服务状态确认中，暂不可创建"}
                </button>
              <p className="privacy-line"><ShieldCheck size={13} />成功出图即计费，采用不另收费。</p>
            </aside>
          </div>}

          {job.data && sourceUrl && workspace && <section className="result-preview-card"><LocalEditReview workspaceId={workspace.id} job={job.data} sourceUrl={sourceUrl} onJobChange={setJobId} onRevise={revise} /></section>}

          {jobId && requestError && <div className="api-state" role="alert">{errorMessage(requestError)}</div>}
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
              setSourceOverridden(true);
              setHasSelection(false);
              setEditorError(undefined);
              if (jobId) setJobId(undefined);
              if (previewUrl) URL.revokeObjectURL(previewUrl);
              setPreviewUrl(undefined);
              setLibraryOpen(false);
            }}
          />
        ) : null}
      </div>
    </AppShell>
    </WorkspaceJobGate>
  );
}
