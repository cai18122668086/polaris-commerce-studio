/** 剪辑页的三步：① 选视频 → ② 选模板 → ③ 预览确认并下载。状态只看真实数据，不看用户点过哪里。 */
export type EditingFlowStep = "source" | "template" | "review";
export type EditingFlowState = "done" | "current" | "todo";

export const EDITING_FLOW_STEPS: { key: EditingFlowStep; index: number; label: string; anchor: string }[] = [
  { key: "source", index: 1, label: "选视频", anchor: "editing-source" },
  { key: "template", index: 2, label: "选模板", anchor: "editing-templates" },
  { key: "review", index: 3, label: "预览确认", anchor: "editing-results" },
];

export type EditingFlowInput = {
  hasSource: boolean;
  hasTemplate: boolean;
  /** 识别、编排或渲染正在进行 */
  working: boolean;
  /** 有待确认的预览 */
  previewReady: boolean;
  /** 有已确认、可下载的成片 */
  finalReady: boolean;
};

export function editingFlowSteps(input: EditingFlowInput): { key: EditingFlowStep; index: number; label: string; anchor: string; state: EditingFlowState; hint: string }[] {
  const done: Record<EditingFlowStep, boolean> = {
    source: input.hasSource,
    template: input.hasTemplate,
    review: input.finalReady,
  };
  const current = EDITING_FLOW_STEPS.find(step => !done[step.key])?.key;
  return EDITING_FLOW_STEPS.map(step => ({
    ...step,
    state: done[step.key] ? "done" : step.key === current ? "current" : "todo",
    hint: hintFor(step.key, input, done[step.key]),
  }));
}

function hintFor(step: EditingFlowStep, input: EditingFlowInput, done: boolean): string {
  if (step === "source") return done ? "已选好口播" : "选一条口播或上传视频";
  if (step === "template") return done ? "已选模板" : "挑一个视频风格";
  if (input.finalReady) return "可下载高清";
  if (input.previewReady) return "预览已就绪，等你确认";
  if (input.working) return "正在生成";
  return "生成后在这里预览";
}
