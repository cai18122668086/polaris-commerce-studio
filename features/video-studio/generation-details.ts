import type { GenerationJob, StageTiming } from "./library";

const stageLabels: Record<string, string> = {
  queued:"排队等待", uploading_reference:"上传参考图", reference_ready:"参考图就绪",
  h3_submitting:"提交动作生成", h3_generating:"生成形象动作", downloading_template:"保存动作预览", uploading_template:"上传动作模板", model_submitting:"登记形象", template_ready:"模板就绪",
  tts_submitting:"生成配音", tts_generated:"配音生成完成", uploading_tts_audio:"上传配音", audio_ready:"配音就绪", uploading_audio:"上传音频", downloading_audio:"保存音频", measuring_audio:"检查音频时长", audio_measured:"音频检查完成",
  resolving_source:"读取动作素材", downloading_source:"下载动作素材", measuring_source:"检查动作时长", source_measured:"动作检查完成", preparing_forward_template:"匹配完整动作", forward_template_prepared:"动作匹配完成", uploading_forward_template:"上传完整动作", forward_template_uploaded:"动作上传完成", forward_template_ready:"完整动作就绪", forward_model_submitting:"准备出镜形象", forward_model_ready:"形象准备完成", template_duration_ready:"动作时长就绪",
  backup_avatar_preparing:"准备备用形象", backup_lipsync_submitting:"提交备用生成", backup_lipsync_generating:"备用渠道生成口播视频",
  lipsync_submitting:"提交视频生成", lipsync_generating:"生成口播视频", provider_completed:"视频生成完成", downloading_video:"保存成片", completed:"处理完成", awaiting_review:"等待预览确认", uploading_avatar_video:"上传出镜视频", avatar_model_submitting:"登记出镜形象",
};
const motionStages = new Set(["resolving_source","downloading_source","measuring_source","source_measured","preparing_forward_template","forward_template_prepared","uploading_forward_template","forward_template_uploaded","forward_template_ready","forward_model_submitting","forward_model_ready","template_duration_ready"]);
export function stageLabel(stage: string) { return stageLabels[stage] || "其他处理"; }

export function durationLabel(seconds: number | null) {
  if (seconds === null || !Number.isFinite(seconds) || seconds < 0) return "等待记录";
  if (seconds > 0 && seconds < 0.1) return "不足 0.1 秒";
  if (seconds < 60) return `${Number(seconds.toFixed(1))} 秒`;
  const minutes = Math.floor(seconds / 60);
  const rest = Math.floor(seconds % 60);
  return rest ? `${minutes} 分 ${rest} 秒` : `${minutes} 分钟`;
}

export function generationTimings(job: Pick<GenerationJob,"kind" | "stage_history">) {
  const labels = job.kind === "h3_template" ? ["素材准备","动作生成","保存预览","形象登记"] : ["配音准备","动作匹配","视频生成","成片保存"];
  const groups = labels.map(label => ({ label, seconds:0, recorded:false, pending:false, interrupted:false, waiting:false, stages:[] as StageTiming[] }));
  for (const timing of job.stage_history || []) {
    const stage = timing.stage;
    const index = job.kind === "h3_template"
      ? stage.startsWith("h3_") ? 1 : ["uploading_template","model_submitting","avatar_model_submitting","template_ready","completed"].includes(stage) ? 3 : ["downloading_template","awaiting_review"].includes(stage) ? 2 : 0
      : motionStages.has(stage) ? 1 : (["lipsync_submitting","lipsync_generating"].includes(stage) || stage.startsWith("backup_")) ? 2 : ["provider_completed","downloading_video","completed"].includes(stage) ? 3 : 0;
    const group = groups[index];
    group.stages.push(timing);
    if (timing.duration_seconds !== null && Number.isFinite(timing.duration_seconds) && timing.duration_seconds >= 0) { group.seconds += timing.duration_seconds; group.recorded = true; }
    if (timing.duration_seconds === null && !timing.finished_at) group.pending = true;
    if (timing.outcome === "failed" || timing.outcome === "unknown") group.interrupted = true;
    if (timing.outcome === "awaiting_resume") group.waiting = true;
  }
  return { groups, total:groups.reduce((sum, group) => sum + group.seconds,0) };
}
