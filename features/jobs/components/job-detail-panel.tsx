"use client";

import { FileWarning, LoaderCircle, RefreshCw, X } from "lucide-react";
import Link from "next/link";

import { JobAssetPreview } from "@/components/job-asset-preview";
import { StatusBadge } from "@/components/status-badge";
import { useJob } from "@/features/jobs/api/jobs";
import { errorMessage } from "@/lib/api/request";
import { formatDateTime, jobStageLabel, jobTitle, jobTypeLabel } from "@/lib/jobs/presentation";
import { jobWorkspaceHref } from "@/lib/jobs/workspace-link";
import { JobProgress } from "./job-progress";

function isReferenceRole(role: string): boolean {
  const value = role.toLowerCase();
  return value.includes("reference") || value.includes("competitor") || value.includes("pose");
}

export function JobDetailPanel({
  workspaceId,
  jobId,
  onClose,
}: {
  workspaceId: string;
  jobId: string;
  onClose: () => void;
}) {
  const detail = useJob(workspaceId, jobId);
  const job = detail.data;
  const inputAssets = job?.assets.filter((asset) => asset.direction === "input") ?? [];
  const referenceAssets = inputAssets.filter((asset) => isReferenceRole(asset.role));
  const sourceAssets = inputAssets.filter((asset) => !isReferenceRole(asset.role));

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
            <Link className="secondary-button" href={jobWorkspaceHref(job)}>打开对应工作台</Link>
            <section className="job-detail-section">
              <div className="job-detail-section__head"><div><span className="job-section-eyebrow">任务信息</span><h3>任务概况</h3></div><small>{detail.isFetching ? "更新中…" : "实时更新"}</small></div>
              <dl className="job-detail-facts">
                <div><dt>任务编号</dt><dd>{job.id}</dd></div>
                <div><dt>任务类型</dt><dd>{jobTypeLabel(job.type)}</dd></div>
                <div><dt>阶段</dt><dd>{jobStageLabel(job.stage, job.status)}</dd></div>
                <div><dt>创建时间</dt><dd>{formatDateTime(job.created_at)}</dd></div>
                <div><dt>完成时间</dt><dd>{formatDateTime(job.finished_at)}</dd></div>
                <div><dt>成功 / 失败 / 总数</dt><dd>{job.succeeded_item_count} / {job.failed_item_count} / {job.expected_item_count}</dd></div>
              </dl>
            </section>
            <section className="job-detail-section">
              <div className="job-detail-section__head"><div><span className="job-section-eyebrow">输入与参考</span><h3>任务素材</h3></div><small>{inputAssets.length} 项</small></div>
              {sourceAssets.length > 0 && <div className="job-asset-group"><div className="job-asset-grid">{sourceAssets.map((asset) => <JobAssetPreview key={`${asset.asset_id}-${asset.ordinal}`} workspaceId={workspaceId} relation={asset} />)}</div></div>}
              {referenceAssets.length > 0 && <div className="job-asset-group"><h4>参考素材</h4><div className="job-asset-grid">{referenceAssets.map((asset) => <JobAssetPreview key={`${asset.asset_id}-${asset.ordinal}`} workspaceId={workspaceId} relation={asset} />)}</div></div>}
              {inputAssets.length === 0 && <div className="job-empty-panel">暂无输入或参考素材。</div>}
            </section>
            {job.error_message && <section className="job-detail-error" role="alert"><FileWarning size={18} /><div><strong>任务级错误</strong><p>{job.error_message}</p>{job.error_code && <small>错误码:{job.error_code}</small>}{job.error_details && <pre>{JSON.stringify(job.error_details, null, 2)}</pre>}</div></section>}

          </div>
        )}
      </aside>
    </>
  );
}
