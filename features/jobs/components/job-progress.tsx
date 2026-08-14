import type { Job, JobDetail } from "@/lib/api/types";
import { StatusBadge } from "@/components/status-badge";
import { jobCount, jobStageLabel } from "@/lib/jobs/presentation";

export function JobProgress({ job }: { job: Job | JobDetail }) {
  const progress = Math.max(0, Math.min(100, job.progress));
  const failedText = job.failed_item_count ? `${job.failed_item_count} 项失败` : "暂无失败项";
  return (
    <section className="job-progress-card" aria-label="任务真实进度">
      <div className="job-progress-card__head"><div><span className="job-section-eyebrow">后端进度</span><div className="job-progress-card__status"><StatusBadge status={job.status} /><strong>{jobStageLabel(job.stage, job.status)}</strong></div></div><strong className="job-progress-card__value">{progress}%</strong></div>
      <div className="job-progress-bar" role="progressbar" aria-label={`任务进度 ${progress}%`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress}><i style={{ width: `${progress}%` }} /></div>
      <div className="job-progress-card__meta"><span>{jobCount(job)} 已完成 / 预计</span><span>{failedText}</span></div>
      <p className="job-progress-card__hint">进度和阶段来自任务详情 API?页面不会用动画虚构或插值补齐百分比。</p>
    </section>
  );
}
