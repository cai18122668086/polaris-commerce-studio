"use client";

import { useState } from "react";
import { Check, ChevronDown, LoaderCircle, RotateCcw, ScanLine } from "lucide-react";
import { useCancelJob, useLocalEditDecision, useLocalEditHistory, useRetryJob } from "@/features/jobs/api/jobs";
import type { JobDetail } from "@/lib/api/types";
import { errorMessage } from "@/lib/api/request";
import { allowsJobAction } from "@/lib/jobs/actions";
import { BeforeAfterResult } from "./before-after-result";
import styles from "./local-edit-review.module.css";

type Variant = "locked" | "original";
type Candidate = { owner: JobDetail; variant: Variant; asset: JobDetail["assets"][number] };

function candidates(job: JobDetail): Candidate[] {
  const delivered = job.assets.find(asset => asset.is_deliverable && asset.direction === "output");
  const original = job.assets.find(asset => asset.role === "provider_raw");
  const lockedCandidate = job.assets.find(asset => asset.role === "locked_candidate");
  const locked = lockedCandidate
    ?? (delivered?.validation.candidate_variant !== "original" ? delivered : undefined);
  const originalAvailable = original && (
    lockedCandidate?.validation.strict_lock_success === true || delivered?.asset_id === original.asset_id
    || (job.cost.actual_credits ?? 0) > 0 || job.configuration._local_edit_generation_already_paid === true
  );
  return [
    ...(locked ? [{ owner: job, variant: "locked" as const, asset: locked }] : []),
    ...(originalAvailable ? [{ owner: job, variant: "original" as const, asset: original }] : []),
  ];
}

function preferred(job: JobDetail, choices: Candidate[]) {
  const delivered = job.assets.find(asset => asset.is_deliverable && asset.direction === "output");
  if (delivered) return choices.find(choice => choice.asset.asset_id === delivered.asset_id) ?? choices[0];
  const locked = choices.find(choice => choice.variant === "locked");
  const original = choices.find(choice => choice.variant === "original");
  return locked?.asset.validation.review_state === "reject" && original?.asset.validation.raw_visual_success === true
    ? original : locked ?? original;
}

export function LocalEditReview({ workspaceId, job, sourceUrl, onJobChange, onContinueEditing, onRevise, onAdopted }: {
  workspaceId: string; job: JobDetail; sourceUrl: string; onJobChange: (jobId: string) => void;
  onContinueEditing?: () => void; onRevise?: () => void;
  onAdopted?: () => void;
}) {
  const history = useLocalEditHistory(workspaceId, job);
  const decision = useLocalEditDecision(workspaceId);
  const regenerate = useRetryJob(workspaceId);
  const cancel = useCancelJob(workspaceId);
  const [selectedAssetId, setSelectedAssetId] = useState<string>();
  const [actionError, setActionError] = useState<string>();
  const [regeneration, setRegeneration] = useState<{ jobId: string; instruction: string }>();
  const editing = regeneration?.jobId === job.id;
  const [retained, setRetained] = useState<{ forJobId: string; candidate: Candidate }>();
  const seenAssets = new Set<string>();
  const choices = [
    ...[job, ...(history.data ?? [])].flatMap(candidates),
    ...(retained?.forJobId === job.id ? [retained.candidate] : []),
  ].filter(choice => {
    if (seenAssets.has(choice.asset.asset_id)) return false;
    seenAssets.add(choice.asset.asset_id);
    return true;
  });
  const activeOutput = job.assets.find(asset => asset.is_deliverable && asset.direction === "output");
  const savedChoice = activeOutput && (choices.find(choice => choice.asset.asset_id === activeOutput.asset_id) ?? {
    owner: job, variant: activeOutput.validation.candidate_variant === "original" ? "original" as const : "locked" as const,
    asset: activeOutput,
  });
  const selected = choices.find(choice => choice.asset.asset_id === selectedAssetId)
    ?? savedChoice ?? preferred(job, choices.filter(choice => choice.owner.id === job.id)) ?? choices[0];
  const image = selected?.asset;
  const originalSelected = selected?.variant === "original";
  const versions = [...new Map(choices.map(choice => [choice.owner.id, choice.owner])).values()];
  const ownerChoices = choices.filter(choice => choice.owner.id === selected?.owner.id);
  const latest = candidates(job).find(choice => choice.variant === "locked")?.asset;
  const pending = job.status === "awaiting_final_review";
  const busy = decision.isPending || regenerate.isPending || cancel.isPending;
  const summary = originalSelected
    ? "审图意见针对局部合成版。"
    : image?.validation.visual_review_summary;
  const alreadyAdopted = image?.asset_id === activeOutput?.asset_id && Boolean(activeOutput);

  const act = async (action: "accept" | "review" | "regenerate" | "retry" | "cancel") => {
    if (busy) return;
    if (action === "regenerate" && (!editing || !regeneration.instruction.trim())) return;
    setActionError(undefined);
    try {
      if (action === "regenerate" || action === "retry") {
        if (image) setSelectedAssetId(image.asset_id);
        const next = await regenerate.mutateAsync({
          jobId: job.id, allowedActions: job.allowed_actions, scope: "failed",
          ...(action === "regenerate" ? { localEditInstruction: regeneration!.instruction.trim() } : {}),
        });
        if (selected) setRetained({ forJobId: next.id, candidate: selected });
        setRegeneration(undefined);
        onJobChange(next.id);
      } else if (action === "cancel") {
        const next = await cancel.mutateAsync({ jobId: job.id, allowedActions: job.allowed_actions });
        onJobChange(next.id);
      } else {
        const sha = action === "review" ? latest?.validation.sha256 : image?.validation.sha256;
        if (typeof sha !== "string") throw new Error("候选信息尚未就绪，请刷新任务后重试。");
        const next = await decision.mutateAsync({
          jobId: job.id, allowedActions: job.allowed_actions, action, candidateSha256: sha,
          candidateVariant: action === "review" ? "locked" : selected?.variant ?? "locked",
          allowOutsideSelectionChanges: action === "accept" && originalSelected,
        });
        onJobChange(next.id);
        if (action === "accept") onAdopted?.();
      }
    } catch (caught) {
      setActionError(errorMessage(caught));
    }
  };

  const completed = job.status === "completed";
  const abandoned = job.status === "cancelled";
  const failed = job.status === "failed";
  const selectedLatest = selected?.owner.id === job.id;
  const credits = job.cost.estimated_credits;
  const charged = job.cost.actual_credits;
  const reusedPaidGeneration = job.configuration._local_edit_generation_already_paid === true;
  const selectedPaid = selected?.owner.cost.actual_credits;
  const canDownload = Boolean(alreadyAdopted || (typeof selectedPaid === "number" && selectedPaid > 0) || selected?.owner.configuration._local_edit_generation_already_paid === true);
  const instruction = ((selected?.owner ?? job).configuration.settings as Record<string, unknown> | undefined)?.instruction;
  const canAdopt = (pending || completed) && job.allowed_actions.includes("accept_local_edit") && image && !alreadyAdopted;

  return <div className={styles.panel} aria-label="修改候选与版本选择">
    <div className={styles.preview}>
      <div className={styles.previewBar}>
        <span>{alreadyAdopted ? "当前使用结果" : "效果预览"}</span>
        {versions.length > 1 && <label className={styles.versions}>版本
          <select value={selected?.owner.id ?? ""} onChange={event => {
            const available = choices.filter(choice => choice.owner.id === event.target.value);
            const choice = available.find(choice => choice.variant === selected?.variant) ?? available[0];
            setSelectedAssetId(choice?.asset.asset_id);
          }} disabled={busy}>
            {versions.map((version, index) => <option key={version.id} value={version.id}>{version.id === job.id ? "最新版本" : `保留版本 ${versions.length - index}`}</option>)}
          </select>
        </label>}
      </div>
      {ownerChoices.length > 1 && <div className={styles.variantTabs} role="group" aria-label="同次生成的两种效果">
        {ownerChoices.map(choice => <button key={choice.asset.asset_id} type="button" aria-pressed={choice.asset.asset_id === image?.asset_id}
          disabled={busy} onClick={() => setSelectedAssetId(choice.asset.asset_id)}>
          {choice.variant === "original" ? "完整生成版" : "局部合成版"}
        </button>)}
      </div>}
      {image ? <BeforeAfterResult key={image.asset_id} workspaceId={workspaceId} sourceUrl={sourceUrl} assetId={image.asset_id}
        downloadable={canDownload} preview={!alreadyAdopted} />
        : (failed || abandoned || completed) ? <img className={styles.sourcePreview} src={sourceUrl} alt="本次修改原图" /> : <div className={styles.loading}><LoaderCircle className="spin" size={24} /><span>正在生成修改版…</span></div>}
      {history.error && <p role="alert" className={styles.error}>历史版本加载失败。<button type="button" onClick={() => void history.refetch()}>重新加载</button></p>}
    </div>
    <aside className={styles.decision}>
      <span className={`${styles.status} ${pending ? styles.waiting : ""}`}><i />{pending ? "待确认" : completed ? alreadyAdopted ? "已采用" : "可切换" : abandoned ? "已放弃" : failed ? "需调整" : "处理中"}</span>
      <div className={styles.heading}><h3>{editing ? "调整后再生成" : pending ? "确认修改效果" : completed ? !image ? "任务已保存" : alreadyAdopted ? "修改已保存" : "切换使用结果" : abandoned ? "本次修改已放弃" : failed ? "这次修改未完成" : "正在生成修改版"}</h3>
        {!editing && <p>{originalSelected ? "完整生成版会保留选区外变化。" : pending ? "局部合成版保留选区外原貌。" : completed ? image ? "可以下载，或继续修改。" : "当前任务没有图片结果。" : abandoned ? (typeof charged === "number" && charged > 0 ? "图片已保留，生成费用已结算。" : "预留积分已释放。") : failed ? job.error_message ?? "可重试，或调整选区和要求。" : "完成后即可比较选择。"}</p>}
      </div>
      {editing && <form className={styles.regeneration} onSubmit={event => { event.preventDefault(); void act("regenerate"); }}>
        <label htmlFor={`regeneration-${job.id}`}>修改要求</label>
        <textarea id={`regeneration-${job.id}`} autoFocus rows={4} maxLength={4000} value={regeneration.instruction} disabled={busy}
          onChange={event => setRegeneration({ jobId: job.id, instruction: event.target.value })} />
        <div className={styles.regenerationActions}>
          <button type="button" disabled={busy} onClick={() => setRegeneration(undefined)}>取消</button>
          <button type="submit" className={styles.primary} disabled={busy || !regeneration.instruction.trim()}>
            {regenerate.isPending ? <LoaderCircle className="spin" size={15} /> : <RotateCcw size={15} />}生成新版本{typeof credits === "number" && <small> · {credits} 积分</small>}
          </button>
        </div>
      </form>}
      {!editing && (pending || canAdopt) && <div className={styles.actions}>
        {canAdopt && <button className={styles.primary} type="button" disabled={busy} onClick={() => void act("accept")}><Check size={17} />{originalSelected ? "采用完整生成版" : "采用这版"}</button>}
        {pending && <div className={styles.secondaryActions}>
          {job.allowed_actions.includes("review_local_edit") && selectedLatest && !originalSelected && <button type="button" disabled={busy || !latest} onClick={() => void act("review")}><ScanLine size={15} />复核这版</button>}
          {allowsJobAction(job.allowed_actions, "retry") && <button type="button" disabled={busy} onClick={() => setRegeneration({ jobId: job.id, instruction: typeof instruction === "string" ? instruction : "" })}><RotateCcw size={15} />调整要求再生成</button>}
        </div>}
        <div className={styles.price}><span>{reusedPaidGeneration ? "已付费版本" : "已结算"}</span><strong>{reusedPaidGeneration ? "未重复收费" : typeof charged === "number" ? `${charged} 积分` : "按生成计费"}</strong></div>
        {pending && job.allowed_actions.includes("cancel") && <button className={styles.abandon} type="button" disabled={busy} onClick={() => void act("cancel")}>放弃本次修改</button>}
      </div>}
      {completed && alreadyAdopted && onContinueEditing && <button className={styles.primary} type="button" onClick={onContinueEditing}>继续修改这张图</button>}
      {(abandoned || failed) && allowsJobAction(job.allowed_actions, "retry") && <button className={styles.primary} type="button" disabled={busy} onClick={() => void act("retry")}><RotateCcw size={15} />重试本次修改</button>}
      {(abandoned || failed) && onRevise && <button className={styles.abandon} type="button" onClick={onRevise}>重新圈选</button>}
      {busy && <p className={styles.loadingText} role="status"><LoaderCircle className="spin" size={14} />正在处理…</p>}
      {pending && !editing && <details className={styles.disclosure}><summary>审图意见<ChevronDown size={14} /></summary><p>{typeof summary === "string" ? summary : "请以预览效果为准。"}</p>
      </details>}
      {!editing && typeof instruction === "string" && <details className={styles.disclosure}><summary>修改要求<ChevronDown size={14} /></summary><p>{instruction}</p></details>}
      {actionError && <p className={styles.error} role="alert">{actionError}</p>}
    </aside>
  </div>;
}
