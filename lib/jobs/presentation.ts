import type { Job, JobDetail, JobType } from "@/lib/api/types";

export function jobTypeLabel(type: JobType): string {
  return type === "local_edit" ? "局部修改" : "详情套图";
}

export function jobTitle(job: Job | JobDetail): string {
  return job.display_name?.trim() || `${jobTypeLabel(job.type)} · ${job.id.slice(0, 8)}`;
}

export function jobCount(job: Job | JobDetail): string {
  return `${job.succeeded_item_count} / ${job.expected_item_count} 项`;
}

export function jobNote(job: Job | JobDetail): string {
  if (job.status === "partial") return "部分项目成功，可仅重试失败项。";
  if (job.status === "failed") {
    return ("error_message" in job && job.error_message) || "任务失败，可查看详情后重试。";
  }
  if (job.status === "awaiting_confirmation") return "规划已就绪，等待在 mock 内测环境确认。";
  if (job.status === "cancelling") return "正在安全取消任务。";
  if (job.status === "cancelled") return "任务已取消，未继续处理。";
  if (job.status === "completed") return "零付费 mock runner 已完成任务状态流转。";
  return job.stage ? `当前阶段：${job.stage}` : "任务正在内部 mock runner 中处理。";
}

export function formatDate(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}
