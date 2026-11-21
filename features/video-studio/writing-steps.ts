import type { AssistantMode } from "./assistance";

export type WritingStep = "benchmark" | "analyze" | "facts" | "rewrite" | "final";

export const WRITING_STEPS: { id: WritingStep; index: number; label: string; hint: string }[] = [
  { id: "benchmark", index: 1, label: "找对标", hint: "按方向找已验证的爆款作品" },
  { id: "analyze", index: 2, label: "提取拆解", hint: "提取原文，拆出钩子、结构和卖点节奏" },
  { id: "facts", index: 3, label: "产品事实", hint: "写清真实卖点和不能写的内容" },
  { id: "rewrite", index: 4, label: "生成改写", hint: "按拆解结构和产品事实改写，或直接原创" },
  { id: "final", index: 5, label: "定稿", hint: "校对后存入文案库，再去做口播" },
];

/** The assistant tool each step drives; the final step is the studio's own editor. */
export function assistantModeFor(step: WritingStep, original = false): AssistantMode | undefined {
  if (step === "benchmark") return "benchmark";
  if (step === "analyze") return "extract";
  if (step === "rewrite") return original ? "create" : "rewrite";
  return undefined;
}

export type WritingProgress = {
  references: number;
  productFacts: string;
  draftText: string;
  savedTexts: string[];
};

/** Which steps already have real output in this project. Nothing is inferred from page visits. */
export function completedSteps(progress: WritingProgress): Set<WritingStep> {
  const done = new Set<WritingStep>();
  if (progress.references > 0) { done.add("benchmark"); done.add("analyze"); }
  if (progress.productFacts.trim()) done.add("facts");
  if (progress.draftText.trim()) done.add("rewrite");
  if (progress.draftText.trim() && progress.savedTexts.includes(progress.draftText)) done.add("final");
  return done;
}

/** First step without output: where a returning user should land. */
export function suggestedStep(progress: WritingProgress): WritingStep {
  const done = completedSteps(progress);
  if (progress.draftText.trim()) return "final";
  return WRITING_STEPS.find(step => !done.has(step.id))?.id ?? "final";
}
