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
  set_auditing: "图片已生成，整组审核中",
  set_audit_error: "图片已生成，审核异常待确认",
  set_audit_failed: "图片已生成，整组审核未通过",
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
  retry_wait: "等待重试",
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
  selection_mask: "授权选区",
  product_reference: "商品素材",
  product_identity_authority: "商品身份素材",
  white_background_product: "白底商品图",
  product_detail: "商品细节图",
  style_reference: "风格参考",
  package_reference: "包装参考",
  scene_reference: "场景参考",
  brand_reference: "品牌参考",
  local_edit_result: "局部编辑结果",
  product_image_result: "商品图结果",
  reference_remix_result: "参考图重绘结果",
  model_pose_transfer_result: "模特姿势迁移结果",
  creative_image_result: "创意图结果",
  detail_page: "详情页结果",
  amazon_visual: "Amazon 视觉结果",
  domestic_main_image: "国内电商主图结果",
  provider_raw: "生成中间产物",
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
  if (job.status === "partial") return "部分结果已完成，可在详情中查看并重试失败项目。";
  if (job.status === "failed") return "生成未完成，请查看详情中的安全错误摘要。";
  if (job.status === "awaiting_confirmation") return "生成方案已经就绪，等待确认后继续。";
  if (job.status === "cancelling") return "正在安全取消任务。";
  if (job.status === "cancelled") return "任务已取消，不会继续生成。";
  if (job.status === "completed") {
    return job.output_asset_count > 0
      ? `任务已完成，共 ${job.output_asset_count} 个输出结果。`
      : "任务已完成，但没有可交付输出。";
  }
  return job.stage ? `当前阶段：${jobStageLabel(job.stage, job.status)}` : "任务正在处理中。";
}

export function safeJobFailureSummary(errorCode?: string | null): string {
  if (errorCode === "AURORA_SEQUENCE_HALTED") {
    return "前序图片未完成，后续图片已停止生成。";
  }
  if (errorCode?.includes("TIMEOUT")) {
    return "生成服务响应超时，请稍后重试。";
  }
  if (errorCode?.includes("QUOTA") || errorCode?.includes("LIMIT")) {
    return "当前生成额度或服务限额不足，请稍后重试或联系管理员。";
  }
  return "该项目未能生成可交付结果，请按页面提供的操作重试。";
}

export function formatDate(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "-";
  return new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(new Date(value));
}
