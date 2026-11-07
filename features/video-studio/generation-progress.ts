import type { GenerationJob } from "./library";

const labels: Record<string, string> = {
  queued: "正在准备", tts_submitting: "正在生成配音", tts_generated: "配音已生成",
  uploading_tts_audio: "正在准备配音", audio_ready: "配音已就绪", uploading_audio: "正在上传音频",
  downloading_audio: "正在保存音频", measuring_audio: "正在检查配音", audio_measured: "配音已确认",
  resolving_source: "正在准备形象", downloading_source: "正在准备形象", measuring_source: "正在检查动作",
  source_measured: "动作已确认", preparing_forward_template: "正在匹配完整动作", uploading_forward_template: "正在保存动作",
  forward_template_prepared: "完整动作已就绪", forward_template_uploaded: "完整动作已保存", forward_model_submitting: "正在准备形象",
  forward_model_ready: "形象已就绪", template_duration_ready: "形象已就绪", lipsync_submitting: "正在准备口型驱动",
  backup_avatar_preparing: "正在准备备用生成", backup_lipsync_submitting: "正在提交备用生成", backup_lipsync_generating: "备用渠道正在生成口播视频",
  lipsync_generating: "正在生成口播视频", provider_completed: "正在整理成片", downloading_video: "正在保存成片",
  uploading_reference: "正在准备参考图片", reference_ready: "参考图片已就绪", h3_submitting: "正在准备动作生成",
  h3_generating: "正在生成形象动作", downloading_template: "正在保存动作预览", uploading_template: "正在保存形象",
  template_ready: "形象已保存", model_submitting: "正在加入我的形象", completed: "视频已完成",
};
const motionStages = new Set(["resolving_source", "downloading_source", "measuring_source", "source_measured", "preparing_forward_template", "forward_template_prepared", "uploading_forward_template", "forward_template_uploaded", "forward_model_submitting", "forward_model_ready", "template_duration_ready"]);

export function generationProgress(job: Pick<GenerationJob, "status" | "stage" | "kind" | "lipsync_routing">) {
  const active = ["queued", "running"].includes(job.status);
  const waiting = job.status === "awaiting_resume";
  const waitingForResult = waiting && ["lipsync_generating", "h3_generating", "backup_lipsync_generating", "backup_avatar_preparing"].includes(job.stage);
  const stopped = ["failed", "unknown", "rejected"].includes(job.status);
  const review = job.status === "awaiting_review";
  const done = job.status === "completed";
  const step = done ? 4 : review ? 3 : ["provider_completed", "downloading_video", "downloading_template", "uploading_template", "template_ready", "model_submitting"].includes(job.stage) ? 3 : (["lipsync_submitting", "lipsync_generating"].includes(job.stage) || job.stage.startsWith("backup_")) ? 2 : motionStages.has(job.stage) || job.stage.startsWith("h3_") ? 1 : 0;
  const title = review ? "预览并确认你的形象" : job.status === "failed" ? "处理暂停，已保留完成的步骤" : job.status === "unknown" ? "提交结果待确认" : waitingForResult ? "生成耗时较长，等待结果" : waiting ? "等待继续处理" : job.status === "rejected" ? "形象未加入素材库" : done ? job.kind === "h3_template" ? "形象已准备好" : "视频已完成" : job.lipsync_routing?.long_wait && job.stage === "lipsync_generating" ? "生成耗时较长，继续查询原任务" : labels[job.stage] || "正在处理";
  const resumeLabel = waitingForResult ? "继续查询结果" : "继续处理";
  return { active, stopped, waiting, waitingForResult, review, done, step, title, resumeLabel, width: [8, 32, 62, 94, 100][step] };
}

export function elapsedLabel(seconds: number) {
  const value = Math.max(0, Math.floor(seconds));
  return value < 60 ? `${value} 秒` : `${Math.floor(value / 60)} 分 ${value % 60} 秒`;
}
