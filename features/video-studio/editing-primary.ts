import { billableLabel } from "./credit-notes";

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
  /** 编排 + 出片的积分；null = 未定价 */
  credits?: number | null;
};

export function planningButtonLabel(s: PlanningButtonState): string {
  if (s.busy) return "正在提交…";
  if (s.checking) return "正在分析口播";
  if (s.arranging) return "正在编排画面";
  if (s.emptyResponse || s.uncertain) return "正在确认结果";
  if (s.arranged) return s.render === "queued" || s.render === "running" ? "正在生成视频" : s.render === "failed" ? "重试" : s.render === "completed" ? "查看高清成片" : "确认效果，获取高清";
  if (s.recover) return "继续生成";
  if (s.failed) return "重试";
  if (s.blocked) return s.unavailable ? "自动剪辑暂不可用" : "请先补齐素材";
  return s.ready ? billableLabel("开始智能剪辑", s.credits) : "开始智能剪辑";
}

/** 外层操作栏：识别、等待、渲染、预览各阶段的统一说法。 */
export function workspaceActionLabel(s: { busy: boolean; recognizing: boolean; phase?: string; waitingLabel?: string; transcriptReady: boolean; /** 传入时按计费按钮展示（null = 未定价） */ credits?: number | null;
  /** 当前这次剪辑的结果：待确认预览 / 已有高清成片。主按钮直接完成这一步，不再只是滚动页面。 */ result?: "awaiting_review" | "completed" }): string {
  if (s.busy) return "正在提交…";
  if (s.result === "awaiting_review") return "确认效果，获取高清";
  if (s.result === "completed") return "查看高清成片";
  if (s.recognizing) return "正在分析口播";
  if (s.phase === "waiting") return s.waitingLabel || "正在确认结果";
  if (s.phase === "recover") return "继续生成";
  if (s.phase === "rendering") return "正在生成视频";
  if (s.transcriptReady && s.phase === "preview") return "查看预览";
  return s.credits === undefined ? "开始智能剪辑" : billableLabel("开始智能剪辑", s.credits);
}
