"use client";

import { useState } from "react";
import { Check, ChevronDown, LoaderCircle, RotateCcw, ScanLine } from "lucide-react";
import { useCancelJob, useLocalEditDecision, useLocalEditHistory, useRetryJob } from "@/features/jobs/api/jobs";
import type { JobDetail } from "@/lib/api/types";
import { errorMessage } from "@/lib/api/request";
import { BeforeAfterResult } from "./before-after-result";
import styles from "./local-edit-review.module.css";

function preview(job: JobDetail) {
  return job.assets.find(asset => asset.is_deliverable && asset.direction === "output")
    ?? job.assets.find(asset => asset.role === "locked_candidate");
}

export function LocalEditReview({ workspaceId, job, sourceUrl, onJobChange, onContinueEditing, onRevise }: {
  workspaceId: string; job: JobDetail; sourceUrl: string; onJobChange: (jobId: string) => void;
  onContinueEditing?: () => void; onRevise?: () => void;
}) {
  const history = useLocalEditHistory(workspaceId, job);
  const decision = useLocalEditDecision(workspaceId);
  const regenerate = useRetryJob(workspaceId);
  const cancel = useCancelJob(workspaceId);
  const [selectedAssetId, setSelectedAssetId] = useState<string>();
  const [actionError, setActionError] = useState<string>();
  const [rawOpen, setRawOpen] = useState(false);
  const seenAssets = new Set<string>();
  const versions = [job, ...(history.data ?? [])].filter(version => {
    const asset = preview(version);
    if (!asset || seenAssets.has(asset.asset_id)) return false;
    seenAssets.add(asset.asset_id);
    return true;
  });
  const selected = versions.find(version => preview(version)?.asset_id === selectedAssetId) ?? versions[0];
  const image = selected && preview(selected);
  const latest = preview(job);
  const pending = job.status === "awaiting_final_review";
  const busy = decision.isPending || regenerate.isPending || cancel.isPending;
  const sourceJob = selected ?? job;
  const candidateOwner = image && [job, ...(history.data ?? [])].find(version =>
    version.assets.some(asset => asset.role === "locked_candidate" && asset.asset_id === image.asset_id));
  const raw = (candidateOwner ?? sourceJob).assets.find(asset => asset.role === "provider_raw");
  const summary = image?.validation.visual_review_summary;

  const act = async (action: "accept" | "review" | "regenerate" | "cancel") => {
    if (busy) return;
    setActionError(undefined);
    try {
      if (action === "regenerate") {
        if (image) setSelectedAssetId(image.asset_id);
        const next = await regenerate.mutateAsync({ jobId: job.id, allowedActions: job.allowed_actions, scope: "failed" });
        onJobChange(next.id);
      } else if (action === "cancel") {
        const next = await cancel.mutateAsync({ jobId: job.id, allowedActions: job.allowed_actions });
        onJobChange(next.id);
      } else {
        const sha = action === "review" ? latest?.validation.sha256 : image?.validation.sha256;
        if (typeof sha !== "string") throw new Error("候选信息尚未就绪，请刷新任务后重试。");
        const next = await decision.mutateAsync({ jobId: job.id, allowedActions: job.allowed_actions, action, candidateSha256: sha });
        onJobChange(next.id);
      }
    } catch (caught) {
      setActionError(errorMessage(caught));
    }
  };

  const completed = job.status === "completed";
  const abandoned = job.status === "cancelled";
  const failed = job.status === "failed";
  const selectedLatest = selected?.id === job.id;
  const credits = job.cost.estimated_credits;
  const charged = job.cost.actual_credits;
  const reusedPaidGeneration = job.configuration._local_edit_generation_already_paid === true;
  const canDownload = Boolean(image?.is_deliverable || (typeof charged === "number" && charged > 0) || reusedPaidGeneration);
  const instruction = (job.configuration.settings as Record<string, unknown> | undefined)?.instruction;

  return <div className={styles.panel} aria-label="修改候选与版本选择">
    <div className={styles.preview}>
      <div className={styles.previewBar}>
        <span>{image?.is_deliverable ? "修改结果" : "效果预览"}</span>
        {versions.length > 1 && <label className={styles.versions}>版本
          <select value={image?.asset_id ?? ""} onChange={event => setSelectedAssetId(event.target.value)} disabled={busy}>
            {versions.map((version, index) => <option key={version.id} value={preview(version)!.asset_id}>{version.id === job.id ? "最新版本" : `保留版本 ${versions.length - index}`}</option>)}
          </select>
        </label>}
      </div>
      {image ? <BeforeAfterResult workspaceId={workspaceId} sourceUrl={sourceUrl} assetId={image.asset_id}
        downloadable={canDownload} preview={!image.is_deliverable} />
        : (failed || abandoned) ? <img className={styles.sourcePreview} src={sourceUrl} alt="本次修改原图" /> : <div className={styles.loading}><LoaderCircle className="spin" size={24} /><span>正在生成修改版…</span></div>}
      {history.error && <p role="alert" className={styles.error}>历史版本加载失败。<button type="button" onClick={() => void history.refetch()}>重新加载</button></p>}
    </div>
    <aside className={styles.decision}>
      <span className={`${styles.status} ${pending ? styles.waiting : ""}`}><i />{pending ? "待确认" : completed ? "已采用" : abandoned ? "已放弃" : failed ? "需调整" : "处理中"}</span>
      <div className={styles.heading}><h3>{pending ? "这版符合你的预期吗？" : completed ? "修改已保存" : abandoned ? "换个选区再试试" : failed ? "这次修改未完成" : image ? "正在检查修改效果" : "正在准备新版本"}</h3>
        <p>{pending ? "拖动滑块，看看修改前后的变化。" : completed ? "可以下载结果，或继续调整。" : abandoned ? (typeof charged === "number" && charged > 0 ? "图片已保留，已完成的生成费用已结算。" : "未完成生成，预留积分已释放。") : failed ? "可调整选区或要求，再生成一版。" : "旧版会保留，完成后再比较选择。"}</p>
      </div>
      {pending && <div className={styles.actions}>
        {job.allowed_actions.includes("accept_local_edit") && image && <button className={styles.primary} type="button" disabled={busy} onClick={() => void act("accept")}><Check size={17} />采用这版</button>}
        <div className={styles.secondaryActions}>
          {job.allowed_actions.includes("review_local_edit") && selectedLatest && <button type="button" disabled={busy || !latest} onClick={() => void act("review")}><ScanLine size={15} />复核这版</button>}
          {job.allowed_actions.includes("retry") && <button type="button" disabled={busy} onClick={() => void act("regenerate")}><RotateCcw size={15} />再生成一版{typeof credits === "number" && <small> · {credits} 积分</small>}</button>}
        </div>
        <div className={styles.price}><span>{reusedPaidGeneration ? "复用已付费版本" : "本版已结算"}</span><strong>{reusedPaidGeneration ? "未重复收费" : typeof charged === "number" ? `${charged} 积分` : "按生成计费"}</strong></div>
        {job.allowed_actions.includes("cancel") && <button className={styles.abandon} type="button" disabled={busy} onClick={() => void act("cancel")}>放弃本次修改</button>}
      </div>}
      {completed && onContinueEditing && <button className={styles.primary} type="button" onClick={onContinueEditing}>继续修改这张图</button>}
      {(abandoned || failed) && onRevise && <button className={styles.primary} type="button" onClick={onRevise}>重新圈选或修改要求</button>}
      {busy && <p className={styles.loadingText} role="status"><LoaderCircle className="spin" size={14} />正在处理…</p>}
      {pending && <details className={styles.disclosure}><summary>查看审图意见<ChevronDown size={14} /></summary><p>{typeof summary === "string" ? summary : "审图暂未给出确定结论，可先查看预览再决定。"}</p>
        <small>每次成功生成单独计费；采用或复核同一张图不重复收费。</small>
      </details>}
      {typeof instruction === "string" && <details className={styles.disclosure}><summary>本次修改要求<ChevronDown size={14} /></summary><p>{instruction}</p></details>}
      {raw && <details className={styles.disclosure} onToggle={event => setRawOpen(event.currentTarget.open)}><summary>原始生成候选<ChevronDown size={14} /></summary>
        <p>仅供诊断，选区外内容可能变化。采用时使用左侧已锁定选区外像素的预览图。</p>
        {rawOpen && <BeforeAfterResult workspaceId={workspaceId} sourceUrl={sourceUrl} assetId={raw.asset_id} downloadable={false} preview />}
      </details>}
      {actionError && <p className={styles.error} role="alert">{actionError}</p>}
    </aside>
  </div>;
}
