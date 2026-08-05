import type { Job, JobDetail, JobType } from "@/lib/api/types";

const JOB_TYPE_LABELS: Record<JobType, string> = {
  local_edit: "局部修改",
  product_image: "万能生图",
  reference_remix: "参考图二创",
  creative_image: "电商创意图",
  detail_pack: "详情套图",
  amazon_visual_suite: "Amazon 视觉套图",
};

export function jobTypeLabel(type: JobType): string {
  return JOB_TYPE_LABELS[type];
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
  if (job.status === "awaiting_confirmation") return "生成方案已就绪，等待确认。";
  if (job.status === "cancelling") return "正在安全取消任务。";
  if (job.status === "cancelled") return "任务已取消，未继续处理。";
  if (job.status === "completed") return "任务已完成。";
  return job.stage ? `当前阶段：${job.stage}` : "任务正在处理中。";
}

export function formatDate(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}
