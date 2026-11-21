/** One user-facing progress line for planning and rendering: 分析口播 → 编排画面 → 生成视频 → 待你确认. */
export type EditingStep = "analyze" | "arrange" | "render" | "review";
export type EditingOutcome = "active" | "waiting_user" | "done" | "failed" | "cancelled";
export type EditingProgress = { step: EditingStep; outcome: EditingOutcome; label: string; detail: string };

export const EDITING_STEPS: { key: EditingStep; label: string }[] = [
  { key: "analyze", label: "分析口播" },
  { key: "arrange", label: "编排画面" },
  { key: "render", label: "生成视频" },
  { key: "review", label: "待你确认" },
];

const editingStage: Record<string, [EditingStep, string]> = {
  queued: ["analyze", "排队中"],
  preparing: ["analyze", "读取原片"],
  preparing_source: ["render", "准备口播画面"],
  transcribing: ["analyze", "识别口播"],
  aligning: ["analyze", "校准字幕"],
  transcript_ready: ["analyze", "口播已识别"],
  compiling: ["arrange", "编排画面"],
  preparing_foreground: ["render", "准备人物前景"],
  rendering: ["render", "渲染画面"],
  validating: ["render", "检查音视频"],
  building_preview: ["render", "准备预览"],
  storing: ["render", "保存视频"],
};

const planningStage: Record<string, [EditingStep, string]> = {
  queued: ["analyze", "排队中"],
  reading_inputs: ["analyze", "检查口播与素材"],
  building_request: ["analyze", "检查模板是否适用"],
  planning: ["arrange", "正在编排视频"],
  storing: ["arrange", "保存编排"],
};

/** A render (or recognition) task. `mode === "transcript"` tasks only analyze the voice. */
export function editingTaskProgress(task: { status: string; stage: string; mode?: string | null }): EditingProgress {
  const transcriptOnly = task.mode === "transcript";
  if (task.status === "failed") return { step: transcriptOnly ? "analyze" : stepOf(editingStage, task.stage, "render"), outcome: "failed", label: transcriptOnly ? "识别未完成" : "剪辑未完成", detail: "" };
  if (task.status === "cancelled") return { step: stepOf(editingStage, task.stage, "render"), outcome: "cancelled", label: "已取消", detail: "" };
  if (task.status === "awaiting_review") return { step: "review", outcome: "waiting_user", label: "待你确认", detail: "预览已就绪，确认后获取高清" };
  if (task.status === "completed") return transcriptOnly
    ? { step: "analyze", outcome: "done", label: "口播已识别", detail: "" }
    : { step: "review", outcome: "done", label: "已完成", detail: "可下载高清" };
  const [step, detail] = editingStage[task.stage] ?? [transcriptOnly ? "analyze" : "render", "正在处理"];
  return { step: transcriptOnly ? "analyze" : step, outcome: "active", label: EDITING_STEPS.find(s => s.key === (transcriptOnly ? "analyze" : step))!.label, detail };
}

/** A planning job: it covers analysis and arrangement, then hands over to a render task. */
export function planningJobProgress(job: { status: string; stage: string }): EditingProgress {
  if (job.status === "failed") return { step: stepOf(planningStage, job.stage, "arrange"), outcome: "failed", label: "编排未完成", detail: "" };
  if (job.status === "cancelled") return { step: stepOf(planningStage, job.stage, "arrange"), outcome: "cancelled", label: "已取消", detail: "" };
  if (job.status === "prepared") return { step: "arrange", outcome: "waiting_user", label: "待继续", detail: "素材检查完成，可开始编排" };
  if (job.status === "completed") return { step: "render", outcome: "active", label: "生成视频", detail: "编排已完成，正在衔接视频预览" };
  const [step, detail] = planningStage[job.stage] ?? ["analyze", "正在处理"];
  return { step, outcome: "active", label: EDITING_STEPS.find(s => s.key === step)!.label, detail };
}

/** Per-step display state for a progress bar. */
export function stepStates(progress: EditingProgress): { key: EditingStep; label: string; state: "done" | "current" | "todo" }[] {
  const index = EDITING_STEPS.findIndex(s => s.key === progress.step);
  return EDITING_STEPS.map((s, i) => ({
    ...s,
    state: i < index || (i === index && progress.outcome === "done") ? "done" : i === index ? "current" : "todo",
  }));
}

function stepOf(map: Record<string, [EditingStep, string]>, stage: string, fallback: EditingStep): EditingStep {
  return map[stage]?.[0] ?? fallback;
}
