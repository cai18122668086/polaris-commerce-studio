"use client";

import { AlertTriangle, RotateCcw } from "lucide-react";
import { StatusBadge } from "@/components/status-badge";
import type { JobDetail, JobStatus } from "@/lib/api/types";
import { allowsJobAction } from "@/lib/jobs/actions";
import { jobAssetRoleLabel, jobItemLabel, jobItemStageLabel, jobItemStatusLabel, safeJobFailureSummary } from "@/lib/jobs/presentation";

// Item states have their own words; only the badge style is borrowed from a
// job status (a skipped page is "not generated", never a "draft").
function itemBadge(status: JobDetail["items"][number]["status"]): { status: JobStatus; label?: string } {
  switch (status) {
    case "succeeded": case "reused": return { status: "completed" };
    case "running": return { status: "processing" };
    case "queued": return { status: "queued" };
    case "cancelled": return { status: "cancelled" };
    case "failed": return { status: "failed" };
    case "retry_wait": return { status: "queued", label: "等待重试" };
    case "skipped": return { status: "draft", label: "未生成" };
    default: return { status: "queued", label: "等待生成" };
  }
}

export function JobItemList({ job, onRetryItem, retryPending }: { job: JobDetail; onRetryItem: (itemId: string) => void; retryPending: boolean }) {
  if (!job.items.length) return <div className="job-empty-panel">暂无可展示的项目。</div>;
  return <div className="job-item-list">{job.items.map((item) => {
    const itemAssets = job.assets.filter((asset) => asset.job_item_id === item.id);
    const outputs = itemAssets.filter((asset) => asset.direction === "output" && asset.is_deliverable);
    const intermediateCount = itemAssets.filter((asset) => asset.direction === "intermediate" || (asset.direction === "output" && !asset.is_deliverable)).length;
    const roles = itemAssets.filter((asset) => asset.direction === "input").map((asset) => jobAssetRoleLabel(asset.role));
    const canRetry = item.status === "failed" && allowsJobAction(job.allowed_actions, "retry");
    const stage = jobItemStageLabel(item.stage);
    return <article className="job-item-card" key={item.id}>
      <div className="job-item-card__head"><div><span className="job-item-card__ordinal">#{item.ordinal + 1}</span><strong>{jobItemLabel(item.item_key, item.ordinal)}</strong><p>{roles.length ? roles.join("、") : "未关联输入素材"}</p></div><div className="job-item-card__status"><StatusBadge {...itemBadge(item.status)} /><span>{jobItemStatusLabel(item.status)}</span></div></div>
      {stage && <div className="job-item-card__stage">处理阶段：{stage}</div>}
      {(outputs.length > 0 || intermediateCount > 0) && <div className="job-item-card__assets"><span>可交付输出：{outputs.length}</span>{intermediateCount > 0 ? <span>中间产物：{intermediateCount}</span> : null}</div>}
      {item.status === "failed" && <div className="job-item-failure" role="alert"><AlertTriangle size={16} /><div><strong>{safeJobFailureSummary(item.error_code)}</strong>{item.error_code && <small>错误码：{item.error_code}</small>}</div>{canRetry && <button type="button" className="secondary-button" onClick={() => onRetryItem(item.id)} disabled={retryPending}><RotateCcw size={14} />重试此项</button>}</div>}
    </article>;
  })}</div>;
}
