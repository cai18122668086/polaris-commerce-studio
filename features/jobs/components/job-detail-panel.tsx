"use client";

import { Ban, Check, FileWarning, LoaderCircle, RefreshCw, RotateCcw, ShieldAlert, X } from "lucide-react";

import { JobAssetPreview } from "@/components/job-asset-preview";
import { JobDeliverablesDownload } from "@/components/job-deliverables-download";
import { StatusBadge } from "@/components/status-badge";
import { useJob } from "@/features/jobs/api/jobs";
import { errorMessage } from "@/lib/api/request";
import type { JobDetail } from "@/lib/api/types";
import { allowsJobAction } from "@/lib/jobs/actions";
import { formatDateTime, jobStageLabel, jobTitle, jobTypeLabel } from "@/lib/jobs/presentation";
import { JobItemList } from "./job-item-list";
import { JobProgress } from "./job-progress";

const actionLabels: Record<string, string> = {
  cancel: "取消任务",
  retry: "重试失败项",
  confirm_plan: "确认方案",
  edit_plan: "编辑方案",
  clone: "复制任务",
  edit: "编辑任务",
  submit: "提交任务",
};

function isReferenceRole(role: string): boolean {
  const value = role.toLowerCase();
  return value.includes("reference") || value.includes("competitor") || value.includes("pose");
}

export function JobDetailPanel({
  workspaceId,
  jobId,
  onClose,
  onCancel,
  onRetry,
  onRetryItem,
  onConfirmPlan,
  cancelPending,
  retryPending,
  confirmPending,
}: {
  workspaceId: string;
  jobId: string;
  onClose: () => void;
  onCancel: (job: JobDetail) => void;
  onRetry: (job: JobDetail) => void;
  onRetryItem: (job: JobDetail, itemId: string) => void;
  onConfirmPlan: (job: JobDetail) => void;
  cancelPending: boolean;
  retryPending: boolean;
  confirmPending: boolean;
}) {
  const detail = useJob(workspaceId, jobId);
  const job = detail.data;
  const inputAssets = job?.assets.filter((asset) => asset.direction === "input") ?? [];
  const referenceAssets = inputAssets.filter((asset) => isReferenceRole(asset.role));
  const sourceAssets = inputAssets.filter((asset) => !isReferenceRole(asset.role));
  const deliverableCount = job?.assets.filter((asset) => asset.direction === "output" && asset.is_deliverable).length ?? 0;
  const permittedActions = job?.allowed_actions ?? [];

  return (
    <>
      <button className="drawer-overlay" onClick={onClose} aria-label="关闭任务详情" />
      <aside className="task-drawer open job-detail-drawer" role="dialog" aria-modal="true" aria-label="任务详情">
        <div className="drawer-head">
          <div><p>生成记录</p><strong>{job ? jobTitle(job) : "正在加载任务"}</strong></div>
          <button className="icon-button" onClick={onClose} aria-label="关闭任务详情"><X size={19} /></button>
        </div>
        {detail.isPending && !job && <div className="api-state"><LoaderCircle className="spin" /><p>正在加载任务详情...</p></div>}
        {detail.error && !job && (
          <div className="api-state api-state--error" role="alert">
            <FileWarning /><p>{errorMessage(detail.error)}</p>
            <button className="secondary-button" onClick={() => void detail.refetch()}>重试</button>
          </div>
        )}
        {job && (
          <div className="job-detail-content">
            <div className="job-detail-heading">
              <div><StatusBadge status={job.status} /><span>{jobTypeLabel(job.type)}</span></div>
              <button type="button" className="icon-button" onClick={() => void detail.refetch()} disabled={detail.isFetching} aria-label="刷新任务详情" title="刷新">
                <RefreshCw size={16} className={detail.isFetching ? "spin" : ""} />
              </button>
            </div>
            <JobProgress job={job} />
            <section className="job-detail-section">
              <div className="job-detail-section__head"><div><span className="job-section-eyebrow">任务信息</span><h3>执行事实</h3></div><small>{detail.isFetching ? "同步中..." : "自动同步中"}</small></div>
              <dl className="job-detail-facts">
                <div><dt>任务编号</dt><dd>{job.id}</dd></div>
                <div><dt>任务类型</dt><dd>{jobTypeLabel(job.type)}</dd></div>
                <div><dt>后端阶段</dt><dd>{jobStageLabel(job.stage, job.status)}</dd></div>
                <div><dt>创建时间</dt><dd>{formatDateTime(job.created_at)}</dd></div>
                <div><dt>开始时间</dt><dd>{formatDateTime(job.started_at)}</dd></div>
                <div><dt>更新时间</dt><dd>{formatDateTime(job.updated_at)}</dd></div>
                <div><dt>完成时间</dt><dd>{formatDateTime(job.finished_at)}</dd></div>
                <div><dt>成功 / 失败 / 总数</dt><dd>{job.succeeded_item_count} / {job.failed_item_count} / {job.expected_item_count}</dd></div>
              </dl>
            </section>
            <section className="job-detail-actions" aria-label="任务操作">
              <div className="job-detail-section__head"><div><span className="job-section-eyebrow">权限控制</span><h3>可用操作</h3></div></div>
              <div className="job-action-buttons">
                {allowsJobAction(permittedActions, "retry") && <button type="button" className="secondary-button" onClick={() => onRetry(job)} disabled={retryPending}><RotateCcw size={15} />重试失败项</button>}
                {allowsJobAction(permittedActions, "cancel") && <button type="button" className="secondary-button danger-button" onClick={() => onCancel(job)} disabled={cancelPending}><Ban size={15} />取消任务</button>}
                {allowsJobAction(permittedActions, "confirm_plan") && job.plan && <button type="button" className="primary-button" onClick={() => onConfirmPlan(job)} disabled={confirmPending}><Check size={15} />确认方案</button>}
                {!permittedActions.length && <p className="job-no-actions"><ShieldAlert size={15} />当前任务没有可用操作</p>}
              </div>
              {permittedActions.length > 0 && <p className="job-action-source">操作由后端 allowed_actions 授权:{permittedActions.map((action) => actionLabels[action] ?? action).join("?")}</p>}
            </section>
            <section className="job-detail-section">
              <div className="job-detail-section__head"><div><span className="job-section-eyebrow">输入与参考</span><h3>任务素材</h3></div><small>{inputAssets.length} 项</small></div>
              {sourceAssets.length > 0 && <div className="job-asset-group"><h4>源素材</h4><div className="job-asset-grid">{sourceAssets.map((asset) => <JobAssetPreview key={`${asset.asset_id}-${asset.ordinal}`} workspaceId={workspaceId} relation={asset} />)}</div></div>}
              {referenceAssets.length > 0 && <div className="job-asset-group"><h4>参考素材</h4><div className="job-asset-grid">{referenceAssets.map((asset) => <JobAssetPreview key={`${asset.asset_id}-${asset.ordinal}`} workspaceId={workspaceId} relation={asset} />)}</div></div>}
              {inputAssets.length === 0 && <div className="job-empty-panel">No input or reference assets were returned by the backend.</div>}
            </section>
            {job.error_message && <section className="job-detail-error" role="alert"><FileWarning size={18} /><div><strong>任务级错误</strong><p>{job.error_message}</p>{job.error_code && <small>错误码:{job.error_code}</small>}{job.error_details && <pre>{JSON.stringify(job.error_details, null, 2)}</pre>}</div></section>}
            <section className="job-detail-section">
              <div className="job-detail-section__head"><div><span className="job-section-eyebrow">执行明细</span><h3>Job items 与结果</h3></div><small>{job.items.length} 项</small></div>
              <JobItemList job={job} workspaceId={workspaceId} onRetryItem={(itemId) => onRetryItem(job, itemId)} retryPending={retryPending} />
              {deliverableCount > 0 && <JobDeliverablesDownload workspaceId={workspaceId} jobId={job.id} />}
            </section>
          </div>
        )}
      </aside>
    </>
  );
}
