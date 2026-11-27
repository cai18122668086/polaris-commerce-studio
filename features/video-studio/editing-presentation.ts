/** User-facing labels only. IDs and immutable native fields stay in API payloads. */
// One user-facing identity per template: a single name, exactly one collection, one short detail.
export const TEMPLATE_COLLECTIONS = [
  { name: "卡片讲解", hint: "白底卡片排版，适合清单、步骤和知识点讲解" },
  { name: "新闻资讯", hint: "深色光框与信息卡，适合资讯、热点和观点解读" },
  { name: "人物出镜", hint: "人物占主画面配大字，适合口播和观点表达" },
  { name: "商品图文", hint: "商品图为主、人物小窗陪讲，适合带货和产品介绍" },
  { name: "彩色主题", hint: "纯色背景加标题栏，适合做成固定风格的系列栏目" },
] as const;

export type TemplateCollection = (typeof TEMPLATE_COLLECTIONS)[number]["name"];

const entries: Record<string, [TemplateCollection, string, string]> = {
  "bihuo-02-v1": ["卡片讲解", "白底胶囊", "清单逐项 · 圆形人物"],
  "bihuo-04-v1": ["卡片讲解", "应用窗口", "误区对照 · 阅读进度"],
  "apple-minimal-v1": ["卡片讲解", "极简留白", "双层标题 · 人物让位"],
  "unified-paper-typewriter-v1": ["卡片讲解", "方格打字", "纸感底纹 · 逐字呈现"],
  "unified-chapter-v1": ["卡片讲解", "章节导航", "章节序号 · 模糊背景"],
  "knowledge-talk-v1": ["卡片讲解", "要点清单", "标题要点 · 结论收束"],

  "bihuo-14-v1": ["新闻资讯", "青绿光窗", "网格底纹 · 荧光描边"],
  "bihuo-23-v1": ["新闻资讯", "快讯直播", "滚动快讯 · 橙色光框"],
  "bihuo-28-v1": ["新闻资讯", "紫夜斜卡", "倾斜资料 · 人物角窗"],
  "bihuo-33-v1": ["新闻资讯", "霓虹光框", "深色网格 · 人物越框"],

  "presenter-openings-v1": ["人物出镜", "人物亮相", "全屏开场 · 大字标题"],
  "bihuo-34-v1": ["人物出镜", "黑底黄字", "极简分割线 · 大字重点"],
  "bihuo-36-v1": ["人物出镜", "居中字幕", "人物全屏 · 字幕接力"],
  "bihuo-40-v1": ["人物出镜", "简洁白卡", "倾斜画框 · 黑黄对比"],
  "bihuo-47-v1": ["人物出镜", "星光商务", "网格空间 · 叠层图文"],
  "bihuo-08-v1": ["人物出镜", "暗夜网格", "透视网格 · 醒目标题"],

  "bihuo-10-v1": ["商品图文", "生活手记", "手写标题 · 纸质卡片"],
  "bihuo-16-v1": ["商品图文", "抠像描边", "人物描边 · 图卡遮挡"],
  "bihuo-19-v1": ["商品图文", "圆孔转场", "柔焦背景 · 悬浮圆窗"],
  "bihuo-32-v1": ["商品图文", "柔焦叠窗", "暖色柔焦 · 纵向图文"],
  "bihuo-48-v1": ["商品图文", "暖白圆窗", "大幅配图 · 圆形人物"],
  "product-explainer-v1": ["商品图文", "竖向分屏", "三图并列 · 人物方窗"],
  "rotation-cards-v1": ["商品图文", "三图轮换", "纵深叠放 · 逐张呈现"],
  "azl-panels-v1": ["商品图文", "杂志多格", "图文分区 · 素材换位"],

  "bihuo-09-v1": ["彩色主题", "古卷纸纹", "米黄底色 · 重点便签"],
  "bihuo-13-v1": ["彩色主题", "薄荷双窗", "薄荷底色 · 上下分区"],
  "bihuo-15-v1": ["彩色主题", "蓝白光晕", "柔和底色 · 悬浮图卡"],
  "bihuo-24-v1": ["彩色主题", "深青标题", "深青底色 · 双行标题"],
  "bihuo-26-v1": ["彩色主题", "靛蓝圆窗", "圆形人物 · 黄色重点"],
};

/** Kept renderable for existing projects, but not offered in the library. */
const hidden = new Set<string>([
  // Near-identical layouts: one of each pair stays.
  "bihuo-03-v1", // = 应用窗口 (bihuo-04)
  "bihuo-11-v1", // = 暖白圆窗 (bihuo-48)
  "bihuo-27-v1", // = 深青标题 (bihuo-24), colour only
  "bihuo-29-v1", // = 青绿光窗 (bihuo-14), colour only
  // No male presenter example yet: the style needs real operation footage.
  "chenxi-broll-v1",
]);

const fallbackCollection: Record<string, TemplateCollection> = {
  知识口播: "卡片讲解", 应用窗口: "卡片讲解", 文字动效: "卡片讲解", 实景教程: "卡片讲解",
  资讯解读: "新闻资讯", 新闻解读: "新闻资讯",
  口播模板: "人物出镜", 人物场景: "人物出镜", 观点叙事: "人物出镜",
  产品展示: "商品图文", 图卡资料: "商品图文", 分享: "商品图文",
};

export function isTemplateListed(id: string): boolean {
  return !hidden.has(id);
}

export function templateDisplayName(id: string | undefined | null): string | undefined {
  return id ? entries[id]?.[1] : undefined;
}

export function templateEntry(id: string): [TemplateCollection, string, string] | undefined {
  return entries[id];
}

export function templateFallbackCollection(category: string): TemplateCollection | undefined {
  return fallbackCollection[category];
}

const technicalText = /\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b|\b[0-9a-f]{24,}\b|\b[A-Z][A-Z0-9]*_[A-Z0-9_]+\b|\b(?:[A-Z]{1,6}-[A-Z]?\d{1,3}|AZL\d+|LYO\d+|YYP\d+)\b|\/(?:content|media|timing|events|items|layout)\//i;

export function editingMessage(value: unknown, fallback: string): string {
  const message = value instanceof Error ? value.message : typeof value === "string" ? value : "";
  return message && !technicalText.test(message) && /[\u3400-\u9fff]/.test(message) ? message : fallback;
}

export function editingTemplateName(id?: string, fallback?: string): string {
  return templateDisplayName(id) || editingMessage(fallback, "动效模板");
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
type PlanningSubmission = { status: string; call_state: string; error_code?: string | null };

/** A pending or uncertain paid request can never become a second paid action. */
export function editingPlanningAction(prepared?: PreparedInput, submitted?: PlanningSubmission): "prepare" | "generate" | "preview" | "recover" | "wait" | "blocked" {
  if (submitted) {
    if (["queued", "running"].includes(submitted.status)) return "wait";
    if (submitted.error_code === "EDITING_PLAN_EMPTY_RESPONSE") return "blocked";
    if (submitted.call_state === "intent_saved") return "blocked";
    if (submitted.status === "completed") return "preview";
    if (["failed", "cancelled"].includes(submitted.status) && submitted.call_state === "response_saved") return "recover";
    return ["failed", "cancelled"].includes(submitted.status) ? "prepare" : "wait";
  }
  if (!prepared) return "prepare";
  return prepared.execution_available && !prepared.template_style_blockers?.length && (prepared.available_template_group_count ?? 1) >= 1 ? "generate" : "blocked";
}
