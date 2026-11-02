"use client";

import { TaskWorkspaceLink } from "./task-workspace-link";
import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowUpRight, LoaderCircle, RotateCcw, Sparkles, X } from "lucide-react";
import { useAsset, useAssetAccessUrl, useUploadAsset } from "@/features/assets/api/assets";
import { useCreateJob, useJob, useRetryJob } from "@/features/jobs/api/jobs";
import { CreditCostHint } from "@/features/billing/components/credit-account";
import { presentWorkflow, useRuntimeStatus } from "@/features/runtime/api/runtime";
import { errorMessage } from "@/lib/api/request";
import type { LocalEditJobCreate } from "@/lib/api/types";
import { useBodyScrollLock } from "@/lib/hooks/use-body-scroll-lock";
import { allowsJobAction } from "@/lib/jobs/actions";
import { selectJobResultAssets } from "@/lib/jobs/results";
import { BeforeAfterResult } from "./before-after-result";
import { JobProgressFeedback } from "./job-progress-feedback";
import { MaskEditor, type MaskEditorHandle } from "./mask-editor";
import styles from "./local-edit-dialog.module.css";

type SourceImage = { assetId: string; title: string };
type PendingSubmission = { instruction: string; maskFile?: File; maskId?: string; request?: LocalEditJobCreate };

const EXAMPLES = [
  ["改文字", "将选区内的文字改为“清爽保湿”，保持原有字体风格、位置与背景。"],
  ["修商品细节", "修复选区内模糊或破损的细节，保留商品原有结构、颜色与光影。"],
  ["去杂物", "移除选区内的杂物，用周围背景自然补齐，保持光线与纹理一致。"],
] as const;

export function LocalEditDialog({ workspaceId, source: initialSource, open, onClose }: {
  workspaceId: string;
  source: SourceImage;
  open: boolean;
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const editor = useRef<MaskEditorHandle>(null);
  const submitting = useRef(false);
  // Keep the same mask and request after a lost response so retrying cannot
  // create another paid intent with a newly uploaded mask.
  const pendingSubmission = useRef<PendingSubmission | null>(null);
  const [source, setSource] = useState(initialSource);
  const [instruction, setInstruction] = useState("");
  const [hasSelection, setHasSelection] = useState(false);
  const [prepared, setPrepared] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string>();
  const [jobId, setJobId] = useState<string>();
  const asset = useAsset(workspaceId, source.assetId);
  const access = useAssetAccessUrl(workspaceId, source.assetId);
  const upload = useUploadAsset(workspaceId);
  const createJob = useCreateJob(workspaceId);
  const retryJob = useRetryJob(workspaceId);
  const job = useJob(workspaceId, jobId);
  const runtime = useRuntimeStatus();
  const workflow = presentWorkflow(runtime.data?.capabilities.local_edit);
  const available = workflow.mode === "provider" || workflow.mode === "mock";
  const busy = isSubmitting || upload.isPending || createJob.isPending || retryJob.isPending;
  const sourceReady = asset.data?.media_kind === "image" && asset.data.lifecycle_status === "ready" && Boolean(access.data?.url);
  const locked = prepared || Boolean(jobId);
  const result = selectJobResultAssets(job.data)[0];
  const canRetry = !result && job.data && allowsJobAction(job.data.allowed_actions, "retry");
  const loadError = asset.error ?? access.error;
  const sourceUrl = access.data?.url;

  useBodyScrollLock(open);
  useEffect(() => {
    const element = dialog.current;
    if (!element) return;
    if (open && !element.open) element.showModal();
    if (!open && element.open) element.close();
  }, [open]);

  const onSelection = useCallback((selected: boolean) => {
    setHasSelection(selected);
    setError(undefined);
  }, []);
  const onEditorError = useCallback((message?: string) => setError(message), []);
  const close = () => { if (!submitting.current) onClose(); };

  const submit = async () => {
    if (submitting.current || jobId || !sourceReady || !available || (!prepared && (!hasSelection || !instruction.trim()))) return;
    submitting.current = true;
    setIsSubmitting(true);
    setPrepared(true);
    setError(undefined);
    const pending = pendingSubmission.current ?? { instruction: instruction.trim() };
    pendingSubmission.current = pending;
    try {
      if (!pending.maskFile) {
        const file = await editor.current?.exportMaskFile();
        if (!file) throw new Error("图片尚未就绪，请稍后重试。");
        pending.maskFile = file;
      }
      if (!pending.maskId) {
        const mask = await upload.mutateAsync({ file: pending.maskFile, mediaKind: "mask" });
        pending.maskId = mask.id;
      }
      pending.request ??= {
        type: "local_edit",
        intent: "submit",
        display_name: `一句话改图 · ${source.title}`,
        input: { source_asset_id: source.assetId, selection_mask_asset_id: pending.maskId },
        configuration: { instruction: pending.instruction, output_format: "png", quality: "balanced", execution_path: "auto" },
      };
      const created = await createJob.mutateAsync(pending.request);
      setJobId(created.id);
    } catch (caught) {
      setError(errorMessage(caught));
      if (!pending.maskFile) {
        pendingSubmission.current = null;
        setPrepared(false);
      }
    } finally {
      submitting.current = false;
      setIsSubmitting(false);
    }
  };

  const retry = async () => {
    if (submitting.current || !job.data || !canRetry) return;
    submitting.current = true;
    setIsSubmitting(true);
    setError(undefined);
    try {
      const created = await retryJob.mutateAsync({ jobId: job.data.id, allowedActions: job.data.allowed_actions, scope: "failed" });
      setJobId(created.id);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      submitting.current = false;
      setIsSubmitting(false);
    }
  };

  const continueEditing = () => {
    if (!result) return;
    setSource({ assetId: result.asset_id, title: `${source.title} · 修改版` });
    setJobId(undefined);
    setInstruction("");
    setHasSelection(false);
    setPrepared(false);
    setError(undefined);
    pendingSubmission.current = null;
    createJob.reset();
    retryJob.reset();
  };

  return <dialog ref={dialog} className={styles.dialog} aria-labelledby="local-edit-dialog-title" aria-describedby="local-edit-dialog-description"
    onCancel={event => { event.preventDefault(); close(); }} onClose={onClose}
    onClick={event => { if (event.target === event.currentTarget) close(); }}>
    <div className={styles.content}>
      <header className={styles.header}>
        <div><h2 id="local-edit-dialog-title">局部修改</h2><p id="local-edit-dialog-description">一句话改图 · {source.title}</p></div>
        <button type="button" className={styles.close} onClick={close} disabled={busy} aria-label="关闭局部修改"><X size={20} /></button>
      </header>
      <div className={styles.body}>
        <section className={styles.canvas} aria-label={result ? "修改前后对比" : "圈选要修改的位置"}>
          {loadError ? <div className={styles.loadState} role="alert"><p>{errorMessage(loadError)}</p><button type="button" onClick={() => { void asset.refetch(); void access.refetch(); }}>重新加载图片</button></div>
            : !sourceReady ? <div className={styles.loadState}><LoaderCircle className="spin" size={24} /><p>{asset.data && asset.data.lifecycle_status !== "ready" ? "这张图片暂不可编辑，请重新选择已完成的图片。" : "正在加载原图…"}</p></div>
              : result && sourceUrl ? <BeforeAfterResult workspaceId={workspaceId} sourceUrl={sourceUrl} assetId={result.asset_id} />
                : <div className={styles.editor} inert={locked ? true : undefined}><MaskEditor key={source.assetId} ref={editor} sourceUrl={sourceUrl} sourceName={source.title} onChange={onSelection} onError={onEditorError} /></div>}
        </section>
        <aside className={styles.controls}>
          <div><h3>{result ? "修改结果已生成" : "想怎么修改？"}</h3><p className={styles.hint}>{result ? "拖动滑块对比，也可以下载或继续修改。" : "先圈出要改的位置，再描述希望发生的变化。选区外保持原样。"}</p></div>
          <fieldset className={styles.form} disabled={locked || busy}>
            <div className={styles.examples} aria-label="修改要求示例">{EXAMPLES.map(([label, text]) => <button key={label} type="button" onClick={() => setInstruction(text)}>{label}</button>)}</div>
            <label htmlFor="local-edit-dialog-instruction">修改要求</label>
            <textarea id="local-edit-dialog-instruction" value={instruction} onChange={event => setInstruction(event.target.value)} maxLength={500} rows={5} placeholder="例如：把选区里的标题改为“清爽保湿”，保持字体和位置。" />
            <span className={styles.count}>{instruction.length} / 500</span>
          </fieldset>
          {!jobId && <div className={styles.cost}><span>本次修改</span><CreditCostHint jobType="local_edit" count={1} fallback={<span>与一句话改图同价</span>} /></div>}
          <p className={styles.hint}>按一句话改图计费，按成功出图结算。</p>
          {error && <p className={styles.error} role="alert">{error}</p>}
          <JobProgressFeedback job={job.data} pending={busy} error={job.error} refreshing={job.isFetching} lastSyncedAt={job.dataUpdatedAt} onRefresh={jobId ? () => void job.refetch() : undefined} />
          {result ? <button type="button" className={styles.primary} onClick={continueEditing}><Sparkles size={16} />继续修改这张图</button>
            : canRetry ? <button type="button" className={styles.primary} disabled={busy} onClick={() => void retry()}>{busy ? <LoaderCircle className="spin" size={16} /> : <RotateCcw size={16} />}重试失败项目</button>
              : !jobId && <button type="button" className={styles.primary} disabled={busy || !sourceReady || !available || (!prepared && (!hasSelection || !instruction.trim()))} onClick={() => void submit()} aria-busy={busy}>
                {busy ? <LoaderCircle className="spin" size={16} /> : <Sparkles size={16} />}{busy ? "正在提交" : prepared ? "重试提交" : workflow.mode === "mock" ? "保存修改任务" : "生成修改版"}
              </button>}
          {!jobId && !available && <p className={styles.hint} role="status">{runtime.isPending ? "正在确认生成服务状态…" : "一句话改图服务暂不可用，请稍后重试。"}</p>}
          {!jobId && workflow.mode === "mock" && <p className={styles.hint}>当前支持保存任务，暂不生成图片。</p>}
          {jobId && <TaskWorkspaceLink className={styles.taskLink} href={`/workspace/local-edit?jobId=${encodeURIComponent(jobId)}`}>查看完整修改记录<ArrowUpRight size={14} /></TaskWorkspaceLink>}
        </aside>
      </div>
      <footer className={styles.footer}><span>{jobId ? "任务已保存，关闭弹窗后可从任务中心继续查看。" : prepared ? "已保留本次修改内容，重试会继续提交同一次任务。" : "图片已自动带入，无需重新上传。"}</span><button type="button" onClick={close} disabled={busy}>关闭</button></footer>
    </div>
  </dialog>;
}
