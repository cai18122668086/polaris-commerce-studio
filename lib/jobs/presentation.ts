import type { Job, JobDetail, JobItemStatus, JobStatus, JobType } from "@/lib/api/types";

const JOB_TYPE_LABELS: Record<JobType, string> = {
  local_edit: "一句话改图",
  product_image: "万能生图",
  reference_remix: "一键模仿",
  model_pose_transfer: "模特换姿势",
  creative_image: "电商创意图",
  detail_pack: "商品详情图",
  amazon_visual_suite: "亚马逊套图",
  domestic_main_image: "国内电商主图",
};

const JOB_STATUS_LABELS: Record<JobStatus, string> = {
  draft: "草稿",
  queued: "排队中",
  planning: "规划中",
  awaiting_confirmation: "待确认",
  processing: "处理中",
  cancelling: "取消中",
  partial: "部分成功",
  completed: "已完成",
  failed: "失败",
  cancelled: "已取消",
};

const JOB_STAGE_LABELS: Record<string, string> = {
  draft: "草稿",
  queued: "排队中",
  planning: "规划中",
  awaiting_confirmation: "等待确认",
  processing: "处理中",
  generating: "生成中",
  validating: "校验中",
  validation: "校验中",
  organizing: "整理结果中",
  planning_failed: "规划失败",
  suite_quality_reported: "质量检查已完成",
  suite_quality_passed: "质量检查通过",
  suite_review_reported: "套图审核已完成",
  partial: "部分成功",
  completed: "已完成",
  failed: "失败",
  cancelling: "取消中",
  cancelled: "已取消",
};

const JOB_ITEM_STATUS_LABELS: Record<JobItemStatus, string> = {
  pending: "待处理",
  queued: "排队中",
  running: "执行中",
  succeeded: "成功",
  failed: "失败",
  cancelled: "已取消",
  skipped: "已跳过",
  reused: "已复用",
};

const JOB_ASSET_ROLE_LABELS: Record<string, string> = {
  source: "源图",
  product: "商品图",
  product_source: "商品源图",
  model_source: "模特源图",
  pose_reference: "姿势参考",
  reference: "参考图",
  competitor_reference: "竞品参考",
  input: "输入素材",
  output: "输出结果",
  deliverable: "可交付结果",
};

export function jobTypeLabel(type: JobType): string { return JOB_TYPE_LABELS[type]; }
export function jobStatusLabel(status: JobStatus): string { return JOB_STATUS_LABELS[status]; }

/** Uses backend stage values as the source of truth; unknown values remain visible. */
export function jobStageLabel(stage: string | null | undefined, status: JobStatus): string {
  if (stage && JOB_STAGE_LABELS[stage]) return JOB_STAGE_LABELS[stage];
  if (stage) return `阶段：${stage}`;
  return JOB_STATUS_LABELS[status];
}

export function jobItemStatusLabel(status: JobItemStatus): string { return JOB_ITEM_STATUS_LABELS[status]; }
export function jobAssetRoleLabel(role: string): string { return JOB_ASSET_ROLE_LABELS[role] ?? role.replaceAll("_", " "); }
export function jobTitle(job: Job | JobDetail): string { return job.display_name?.trim() || `${jobTypeLabel(job.type)} / ${job.id.slice(0, 8)}`; }
export function jobCount(job: Job | JobDetail): string { return `${job.succeeded_item_count} / ${job.expected_item_count} 项`; }

export function jobNote(job: Job | JobDetail): string {
  if (job.status === "partial") return "Partial success; retry failed items only.";
  if (job.status === "failed") return ("error_message" in job && job.error_message) || "Task failed; view details to retry.";
  if (job.status === "awaiting_confirmation") return "Plan is ready and waiting for confirmation.";
  if (job.status === "cancelling") return "Cancelling the task safely.";
  if (job.status === "cancelled") return "Task cancelled before further processing.";
  if (job.status === "completed") return "Task completed.";
  return job.stage ? `Current stage: ${jobStageLabel(job.stage, job.status)}` : "Task is processing.";
}

export function formatDate(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "-";
  return new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(new Date(value));
}
