/**
 * 剪辑主按钮的用户文案，与四步进度（分析口播 → 编排画面 → 生成视频 → 待你确认）对齐。
 * 只换说法，不改任何状态判断；防重复提交仍由调用方的 waiting / disabled 控制。
 */
export const CONFIRMING_HINT = "正在确认结果，不会重复扣费";

export type PlanningButtonState = {
  busy: boolean;
  /** 素材检查进行中 */
  checking: boolean;
  /** 编排（模型调用）进行中 */
  arranging: boolean;
  /** 提交是否到达服务方尚未确认 */
  uncertain: boolean;
  /** 模型返回空结果，重新生成会产生新费用 */
  emptyResponse: boolean;
  /** 编排完成后的渲染任务状态 */
  render?: "queued" | "running" | "awaiting_review" | "completed" | "failed" | "cancelled" | string;
  arranged: boolean;
  recover: boolean;
  failed: boolean;
  blocked: boolean;
  unavailable: boolean;
  /** 素材已检查完，下一步会调用模型（计费） */
  ready: boolean;
};

export function planningButtonLabel(s: PlanningButtonState): string {
  if (s.busy) return "正在提交…";
  if (s.checking) return "正在分析口播";
  if (s.arranging) return "正在编排画面";
  if (s.emptyResponse || s.uncertain) return "正在确认结果";
  if (s.arranged) return s.render === "queued" || s.render === "running" ? "正在生成视频" : s.render === "failed" ? "重试" : "查看并确认";
  if (s.recover) return "继续生成";
  if (s.failed) return "重试";
  if (s.blocked) return s.unavailable ? "自动剪辑暂不可用" : "请先补齐素材";
  return s.ready ? "开始智能剪辑（计费）" : "开始智能剪辑";
}

/** 外层操作栏：识别、等待、渲染、预览各阶段的统一说法。 */
export function workspaceActionLabel(s: { busy: boolean; recognizing: boolean; phase?: string; waitingLabel?: string; transcriptReady: boolean }): string {
  if (s.busy) return "正在提交…";
  if (s.recognizing) return "正在分析口播";
  if (s.phase === "waiting") return s.waitingLabel || "正在确认结果";
  if (s.phase === "recover") return "继续生成";
  if (s.phase === "rendering") return "正在生成视频";
  if (s.transcriptReady && s.phase === "preview") return "查看并确认";
  return "开始智能剪辑";
}
