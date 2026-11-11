/** User-facing labels only. IDs and immutable native fields stay in API payloads. */
const templateNames: Record<string, string> = {
  "product-explainer-v1": "产品讲解",
  "knowledge-talk-v1": "知识口播",
  "presenter-openings-v1": "人物亮相",
  "rotation-cards-v1": "三图轮换",
  "azl-panels-v1": "杂志多格",
  "unified-chapter-v1": "章节导航",
  "unified-paper-typewriter-v1": "方格纸打字",
  "chenxi-broll-v1": "操作实景",
};

const technicalText = /\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b|\b[0-9a-f]{24,}\b|\b[A-Z][A-Z0-9]*_[A-Z0-9_]+\b|\b(?:[A-Z]{1,6}-[A-Z]?\d{1,3}|AZL\d+|LYO\d+|YYP\d+)\b|\/(?:content|media|timing|events|items|layout)\//i;

export function editingMessage(value: unknown, fallback: string): string {
  const message = value instanceof Error ? value.message : typeof value === "string" ? value : "";
  return message && !technicalText.test(message) && /[\u3400-\u9fff]/.test(message) ? message : fallback;
}

export function editingTemplateName(id?: string, fallback?: string): string {
  return (id && templateNames[id]) || editingMessage(fallback, "动效模板");
}

export function editingFieldName(path: string, fallback: string): string {
  const roles: Record<string, string> = {
    title: "标题", main: "主题文字", body: "说明文字", detail: "补充说明",
    subtitle: "说明文字", tagline: "补充文字", label: "图卡标题",
    focus: "重点文字", keyword: "重点文字", emphasis: "重点文字",
    english_before: "前段英文", english_after: "后段英文",
  };
  return roles[path.split("/").at(-1) || ""] || fallback;
}

export function editingEffectName(name: string, index: number): string {
  const clean = name.replace(/\b(?:[A-Z]{1,6}-[A-Z]?\d{1,3}|AZL\d+|LYO\d+|YYP\d+)\b[ ·:：-]*/g, "").trim();
  return editingMessage(clean, `文字样式 ${index + 1}`);
}

export function editingMusicName(name: string, index?: number): string {
  return /[\\/_]|\b[0-9a-f]{16,}\b|^(?:bgm|sfx)-/i.test(name)
    ? index == null ? "当前配乐" : `配乐 ${index + 1}`
    : name.replace(/\.(?:mp3|wav|m4a|ogg)$/i, "");
}

type PreparedInput = {
  execution_available: boolean;
  template_style_blockers?: string[] | null;
  available_template_group_count?: number | null;
};
type PlanningSubmission = { status: string; call_state: string };

/** A pending or uncertain paid request can never become a second paid action. */
export function editingPlanningAction(prepared?: PreparedInput, submitted?: PlanningSubmission): "prepare" | "generate" | "preview" | "wait" | "blocked" {
  if (submitted) {
    if (["queued", "running"].includes(submitted.status)) return "wait";
    if (submitted.call_state === "intent_saved") return "blocked";
    if (submitted.status === "completed") return "preview";
    return ["failed", "cancelled"].includes(submitted.status) ? "prepare" : "wait";
  }
  if (!prepared) return "prepare";
  return prepared.execution_available && !prepared.template_style_blockers?.length && (prepared.available_template_group_count ?? 5) >= 5 ? "generate" : "blocked";
}
