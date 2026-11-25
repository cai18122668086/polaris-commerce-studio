import type { Job, JobDetail, JobItemStatus, JobStatus } from "@/lib/api/types";

const JOB_TYPE_LABELS: Record<Job["type"], string> = {
  product_replica: "旧版商品复刻",
  local_edit: "一句话改图",
  product_image: "万能生图",
  reference_remix: "一键模仿",
  model_pose_transfer: "模特换姿势",
  creative_image: "电商创意图",
  detail_pack: "商品详情图",
  domestic_detail_review: "详情整页审核",
  amazon_visual_suite: "亚马逊套图",
  domestic_main_image: "国内电商主图",
};

const JOB_STATUS_LABELS: Record<JobStatus, string> = {
  draft: "草稿",
  queued: "排队中",
  planning: "规划中",
  awaiting_confirmation: "待确认",
  processing: "处理中",
  awaiting_final_review: "等待整组确认",
  cancelling: "取消中",
  partial: "部分完成",
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
  awaiting_final_review: "等待整组确认",
  validating: "校验中",
  validation: "校验中",
  organizing: "整理结果中",
  planning_failed: "规划失败",
  intake_confirmation_required: "等待商品事实确认",
  analyzing_confirmed_sources: "分析已确认商品信息",
  suite_quality_reported: "质量检查已完成",
  suite_quality_passed: "质量检查通过",
  suite_review_reported: "套图审核已完成",
  awaiting_local_edit_review: "等待确认修改效果",
  awaiting_user_final_review: "等待整组确认",
  set_audit_failed: "整组审核未通过",
  reused: "已复用",
  generated: "已生成",
  succeeded: "已完成",
  running: "处理中",
  retry_wait: "等待重试",
  partial: "部分完成",
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
  provider_raw: "完整生成候选",
  locked_candidate: "局部合成候选",
  amazon_contact_sheet: "套图总览（质检用）",
  generated_candidate: "生成候选",
  replica_selected_result: "复刻结果",
};

/** Single-image jobs wait for the customer to check one result, not a whole set. */
const SINGLE_IMAGE_REVIEW_LABELS: Partial<Record<Job["type"], string>> = {
  local_edit: "待确认修改",
  product_image: "待确认结果",
  reference_remix: "待确认结果",
  model_pose_transfer: "待确认结果",
  creative_image: "待确认结果",
};

export function jobTypeLabel(type: Job["type"]): string { return JOB_TYPE_LABELS[type]; }
export function jobStatusLabel(status: JobStatus, type?: Job["type"]): string {
  if (status === "awaiting_final_review" && type && SINGLE_IMAGE_REVIEW_LABELS[type]) return SINGLE_IMAGE_REVIEW_LABELS[type]!;
  return JOB_STATUS_LABELS[status];
}

/** Maps backend stage values to Chinese copy; unknown internal stage codes are never shown raw. */
export function jobStageLabel(stage: string | null | undefined, status: JobStatus, type?: Job["type"]): string {
  if (stage === "awaiting_final_review" || stage === "awaiting_user_final_review") return jobStatusLabel("awaiting_final_review", type);
  if (stage && JOB_STAGE_LABELS[stage]) return JOB_STAGE_LABELS[stage];
  return jobStatusLabel(status, type);
}

/** Item stages are optional detail; unknown internal codes are hidden instead of shown raw. */
export function jobItemStageLabel(stage: string | null | undefined): string | null {
  return stage ? JOB_STAGE_LABELS[stage] ?? null : null;
}

/** Backend item keys are identifiers such as page-003; show them as readable Chinese positions. */
export function jobItemLabel(itemKey: string, ordinal: number): string {
  const page = /^page[-_]?0*(\d+)$/i.exec(itemKey);
  if (page) return `第 ${page[1]} 页`;
  if (/[\u3400-\u9fff]/.test(itemKey)) return itemKey;
  return `第 ${ordinal + 1} 项`;
}

export function jobItemStatusLabel(status: JobItemStatus): string { return JOB_ITEM_STATUS_LABELS[status]; }
export function jobAssetRoleLabel(role: string): string { return JOB_ASSET_ROLE_LABELS[role] ?? "其他素材"; }
export function jobTitle(job: Job | JobDetail): string { return job.display_name?.trim() || `${jobTypeLabel(job.type)} / ${job.id.slice(0, 8)}`; }
export function jobCount(job: Job | JobDetail): string { return `${job.succeeded_item_count} / ${job.expected_item_count} 项`; }

export function jobNote(job: Job | JobDetail): string {
  if (job.type === "detail_pack" && job.stage === "intake_confirmation_required") return "请先确认商品事实，随后审阅完整详情规划。";
  if (job.status === "failed" && "items" in job) {
    const failed = job.items.find((item) => item.status === "failed");
    if (failed?.error_code) return safeJobFailureSummary(failed.error_code, failed.error_details);
  }
  if (job.status === "partial") {
    if (job.allowed_actions.includes("retry")) return "部分结果已完成，可在详情中查看并重试失败项目。";
    if (job.allowed_actions.includes("clone")) return "部分结果已完成，可在详情中查看已生成的图片，或重新生成整组。";
    return "部分结果已完成，可在详情中查看已生成的图片。";
  }
  if (job.status === "awaiting_final_review" && job.type === "local_edit") return "修改版已生成，请确认效果后采用，或调整要求再生成。";
  if (job.status === "failed") return "生成未完成，请查看详情中的安全错误摘要。";
  if (job.status === "awaiting_confirmation") return "生成方案已经就绪，等待确认后继续。";
  if (job.status === "cancelling") return "正在安全取消任务。";
  if (job.status === "cancelled") return "任务已取消，不会继续生成。";
  if (job.status === "completed") {
    return job.output_asset_count > 0
      ? `任务已完成，共 ${job.output_asset_count} 个输出结果。`
      : "任务已完成，但没有可交付输出。";
  }
  return job.stage ? `当前阶段：${jobStageLabel(job.stage, job.status, job.type)}` : "任务正在处理中。";
}

const GENERIC_FAILURE_SUMMARY = "这一项没有生成可交付的结果，原始记录已保留。可重新提交，或联系帮助并关联此任务。";

const FAILURE_SUMMARIES: Record<string, string> = {
  STORAGE_WRITE_UNAVAILABLE: "结果存储暂不可写，未提交新的生成请求。存储恢复后可重试。",
  STORAGE_RESULT_PENDING: "原图已生成并暂存。存储恢复后，重试会继续交付原图，无需重新生成。",
  OUTPUT_STORAGE_FAILED: "图片交付时写入存储失败，请稍后重试或联系帮助。",
  OUTPUT_STORAGE_UNAVAILABLE: "结果存储暂不可用，本次图片未能保存，请稍后重试。",
  STORAGE_QUOTA_EXCEEDED: "素材存储空间已满，请清理不需要的素材后重试。",
  PROVIDER_OUTCOME_UNKNOWN: "生成请求的结果尚未确认，系统已停止自动重试，请联系帮助核查，避免重复生成。",
  USAGE_RECORD_FAILED: "生成用量未能记录，系统已停止本次生成，请联系帮助处理。",
  PROVIDER_NOT_CONFIGURED: "生成服务暂未开通，请联系帮助。",
  BUDGET_LIMIT_EXCEEDED: "当前可用积分不足，请充值积分后再试。",
  AURORA_SET_AUDIT_FAILED: "图片已生成，但整组一致性检查未通过，这组图暂不能作为完整套图交付。已生成的图片已保留，可查看下载，或重新生成整组。",
  AURORA_NATIVE_PAIR_AUDIT_FAILED: "相邻页面的衔接检查未通过，后续页面没有继续生成。",
  AURORA_SEQUENCE_HALTED: "前序图片未完成，后续图片已停止生成。",
  AURORA_PLANNING_DEADLINE: "画面规划超时，没有开始生成图片，请稍后重新提交。",
  PLANNER_REQUEST_FAILED: "规划服务暂时不可用，请稍后重试。",
  PLANNER_PROVIDER_FAILED: "规划服务暂时不可用，请稍后重试。",
  PLANNER_OUTPUT_TRUNCATED: "规划服务返回的数据不完整，请稍后重试。",
  NATIVE_PLANNING_OUTCOME_UNKNOWN: "规划请求的结果尚未确认，系统已停止重复提交，请联系帮助核查。",
  INTAKE_OUTCOME_UNKNOWN: "素材分析的结果尚未确认，系统已停止重复提交，请联系帮助核查。",
  PLANNER_RECOVERY_RECEIPT_INVALID: "规划记录需要核对，系统已停止后续调用，请联系帮助核查。",
  IMAGE_PROVIDER_FAILED: "生成服务暂时不可用，请稍后重试。",
  IMAGE_OUTPUT_ARTIFACT_MISSING: "生成服务没有返回图片，请稍后重试。",
  IMAGE_OUTPUT_INVALID: "生成服务返回的图片不符合交付要求，请重试。",
  OUTPUT_DIMENSIONS_INVALID: "生成的图片尺寸不符合要求，请重试。",
  DETAIL_OUTPUT_DIMENSIONS_INVALID: "生成的详情图尺寸不符合要求，请重试。",
  DETAIL_OUTPUT_FORMAT_INVALID: "生成的详情图格式不符合要求，请重试。",
  AMAZON_OUTPUT_ARTIFACT_MISSING: "生成服务没有返回图片，请稍后重试。",
  AMAZON_OUTPUT_DIMENSIONS_INVALID: "生成的图片尺寸不符合亚马逊要求，请重试。",
  AMAZON_OUTPUT_FORMAT_INVALID: "生成的图片格式不符合亚马逊要求，请重试。",
  AMAZON_VISUAL_REVIEW_UNAVAILABLE: "图片质检服务暂不可用，请稍后重试。",
  AMAZON_VISUAL_REVIEW_INVALID: "图片质检服务返回的结果无效，请稍后重试。",
  AMAZON_VISUAL_REVIEW_REQUEST_FAILED: "图片质检服务暂不可用，请稍后重试。",
  AMAZON_SUITE_REVIEW_STALE_OUTPUT: "质检对应的图片已更新，请重新检查。",
  LOCAL_EDIT_VISUAL_REVIEW_REJECTED: "系统检查发现这次修改效果有明显问题。修改版已保留，可以预览后仍然采用，或调整要求再生成。",
  LOCAL_EDIT_VISUAL_REVIEW_NEEDS_REVIEW: "修改版已生成，系统检查没有给出确定结论，请预览后决定是否采用。",
  LOCAL_EDIT_VISUAL_REVIEW_SELECTION_REQUIRED: "新版本已生成，请对比保留的版本后选择采用。",
  LOCAL_EDIT_NEW_GENERATION_REQUIRED: "新一版图片需要单独提交生成任务。",
  MOCK_PROVIDER_FAILED: "生成服务暂时不可用，请稍后重试。",
  MOCK_IMAGE_TRANSIENT_FAILURE: "生成服务暂时不可用，请稍后重试。",
};

function knownJobFailureSummary(errorCode?: string | null, errorDetails?: unknown): string | null {
  const details = errorDetails && typeof errorDetails === "object" ? errorDetails as Record<string, unknown> : {};
  const providerError = details.provider_error && typeof details.provider_error === "object" ? details.provider_error as Record<string, unknown> : {};
  if (errorCode && FAILURE_SUMMARIES[errorCode]) return FAILURE_SUMMARIES[errorCode];
  if (errorCode === "IMAGE_CONTENT_REJECTED" || ["content_policy_violation", "content_policy_rejected", "safety_violation", "moderation_blocked"].includes(String(providerError.code))) {
    return "生成服务因内容限制拒绝了本次请求，未返回图片。原素材和要求已保留。";
  }
  if (errorCode?.startsWith("LOCAL_EDIT_VISUAL_REVIEW")) {
    return "图片已生成，但审核服务暂时不可用。重试会继续审核已保存的图片。";
  }
  if (errorCode?.startsWith("LOCAL_EDIT_RAW_")) {
    return "已保存的候选图未通过完整性校验，请重新提交改图任务。";
  }
  if (errorCode === "IMAGE_REQUEST_FAILED") {
    return "生成服务暂时不可用，请稍后重试。";
  }
  if (errorCode === "CREATIVE_VISUAL_ANALYSIS_INVALID" || errorCode === "PLANNER_SCHEMA_INVALID") {
    return "规划服务返回的数据不完整，请稍后重试。";
  }
  if (errorCode?.includes("TIMEOUT") || errorCode?.includes("DEADLINE")) {
    return "生成服务响应超时，请稍后重试。";
  }
  if (errorCode?.includes("QUOTA") || errorCode?.includes("LIMIT")) {
    return "当前积分或服务限额不足，请稍后重试或联系帮助。";
  }
  if (errorCode?.includes("OUTCOME_UNKNOWN")) {
    return "请求结果尚未确认，系统已停止重复提交，请联系帮助核查。";
  }
  return null;
}

/** Code-only summary: never echoes backend free text. */
export function safeJobFailureSummary(errorCode?: string | null, errorDetails?: unknown): string {
  return knownJobFailureSummary(errorCode, errorDetails) ?? GENERIC_FAILURE_SUMMARY;
}

const HAN = /[\u3400-\u9fff]/;
/** True for Chinese customer copy; English diagnostics or model rationales are rejected. */
export function isChineseUserCopy(text: string | null | undefined): text is string {
  if (!text?.trim() || !HAN.test(text)) return false;
  const latinWords = text.match(/[A-Za-z]{4,}/g) ?? [];
  return latinWords.length <= 2;
}

/** Prefers the mapped code; a backend message is shown only when it is already Chinese copy. */
export function jobFailureMessage(errorCode?: string | null, message?: string | null, errorDetails?: unknown): string | null {
  const known = knownJobFailureSummary(errorCode, errorDetails);
  if (known) return known;
  if (isChineseUserCopy(message)) return message;
  return errorCode || message ? GENERIC_FAILURE_SUMMARY : null;
}

export function formatDate(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "-";
  return new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(new Date(value));
}

const LOCAL_EDIT_REVIEW_REASONS: Record<string, string> = {
  target_not_satisfied: "修改要求没有完全实现",
  unrequested_identity_change: "选区里的商品或文字被意外改动",
  visible_boundary_defect: "选区边缘有明显的接缝或分界",
  visible_artifact: "画面出现明显瑕疵",
};

/** Chinese reasons from the structured review codes; the reviewer's free-text summary is English and never shown. */
export function localEditReviewReasons(codes: unknown): string[] {
  if (!Array.isArray(codes)) return [];
  return [...new Set(codes.map((code) => LOCAL_EDIT_REVIEW_REASONS[String(code)]).filter((value): value is string => Boolean(value)))];
}
