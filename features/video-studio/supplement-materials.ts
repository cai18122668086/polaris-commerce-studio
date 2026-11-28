// 补充素材面板（契约 C5，W4）：值结构、纯函数、接口类型。
// 默认 mode=none：什么都不加；用户不操作就不传任何素材。

import { FREE_TRIAL_TEXT, isPriced } from "@/features/video-studio/credit-notes";

export type SupplementSourceKey = "mine" | "stock" | "ai_image" | "mg";
export type SupplementStyle = "paper" | "ink" | "ember";
export type MaterialSourceKey = Exclude<SupplementSourceKey, "mg">;

export interface SupplementWorkItem {
  id: string;
  project_id: string;
  title?: string;
  script_text: string;
  template_id?: string | null;
  supports_images?: boolean;
  supports_mg?: boolean;
}

export interface SupplementItemSelection {
  material_ids: string[];
  pins?: Record<string, number>;
  by_source?: Partial<Record<MaterialSourceKey, string[]>>;
}

export interface SupplementMaterialsValue {
  mode: "none" | "custom";
  sources: {
    mine?: { enabled: boolean; placement: "auto" | "manual" };
    stock?: { enabled: boolean };
    ai_image?: { enabled: boolean; max_images: number };
    mg?: { enabled: boolean; style: SupplementStyle };
  };
  items: Record<string, SupplementItemSelection>;
  pending: number;
}

export const DEFAULT_SUPPLEMENT: SupplementMaterialsValue = { mode: "none", sources: {}, items: {}, pending: 0 };
export const SOURCE_ORDER: SupplementSourceKey[] = ["mine", "stock", "ai_image", "mg"];
export const MATERIAL_SOURCES: MaterialSourceKey[] = ["mine", "stock", "ai_image"];

export const SOURCE_COPY: Record<SupplementSourceKey, { title: string; line: string }> = {
  mine: { title: "我的素材", line: "上传自己的图片或视频，放到合适的句子" },
  stock: { title: "网上免费素材", line: "按口播稿从免费可商用的素材库找图和视频" },
  ai_image: { title: "AI 生成素材", line: "按口播稿画配图，只给画得出来的句子配" },
  mg: { title: "MG 动效", line: "没有素材的段落，用文字动效补充画面" },
};

export const STYLE_COPY: Record<SupplementStyle, string> = { paper: "暖纸", ink: "墨白", ember: "熔光" };

// ---------------------------------------------------------------- API types

export interface SourceState {
  key: SupplementSourceKey;
  available: boolean;
  reason: string | null;
  price: string;
  credits_per_image?: number | null;
  max_images?: number;
}

export interface SourcesResponse {
  sources: SourceState[];
  stock_providers: { provider: string; label: string; available: boolean; reason: string | null }[];
  mg_styles: { key: SupplementStyle; label: string }[];
  mg_templates?: string[];
  mg_unsupported_reason?: string;
  mg_components: { key: string; label: string; use: string }[];
}

export interface StockCandidate {
  key: string;
  token: string;
  provider: string;
  provider_label: string;
  kind: "image" | "video";
  width: number;
  height: number;
  duration_ms: number | null;
  author: string;
  license: string;
  license_url: string;
  page_url: string;
  attribution: string | null;
}

export interface StockSentence { index: number; text: string; queries: string[]; candidates: StockCandidate[] }
export interface StockSearchResponse { analysis_source: string; providers: string[]; sentences: StockSentence[] }

export interface AiEstimateItem { sentence_index: number; sentence: string; subject: string; purpose: string }
export interface AiEstimateResponse {
  analysis_source: string;
  items: AiEstimateItem[];
  count: number;
  credits_per_image: number | null;
  total_credits: number;
}

export interface MaterialRow {
  id: string;
  asset_id: string;
  label: string;
  description: string;
  kind: "image" | "video";
  mime: string;
  width: number;
  height: number;
  duration_ms: number | null;
  url: string;
  origin?: string | null;
  provenance?: Record<string, unknown> | null;
}

export interface AiImageRow {
  id: string;
  request_id: string;
  work_item_ref: string | null;
  sentence_index: number;
  sentence: string;
  subject: string;
  status: "queued" | "running" | "succeeded" | "failed";
  reused: boolean;
  material_id: string | null;
  error: string | null;
  material?: MaterialRow | null;
}

// ---------------------------------------------------------------- pure helpers

export function splitSentences(text: string): string[] {
  const rows: string[] = [];
  for (const part of (text || "").split(/(?<=[。！？!?；;\n])/)) {
    const trimmed = part.trim();
    if (!trimmed) continue;
    if (trimmed.length <= 46) { rows.push(trimmed); continue; }
    let buffer = "";
    for (const piece of trimmed.split(/(?<=[，,])/)) {
      if (buffer && buffer.length + piece.length > 46) { rows.push(buffer.trim()); buffer = ""; }
      buffer += piece;
    }
    if (buffer.trim()) rows.push(buffer.trim());
  }
  return rows.slice(0, 40);
}

export const MG_UNSUPPORTED = "此模板画面已有信息卡，暂不支持 MG";

/** MG 只在后端白名单模板上开放（人物铺满画面、背景层没有信息卡）。 */
export function mgSupported(item: SupplementWorkItem, mgTemplates?: string[]): boolean {
  if (item.supports_mg === false) return false;
  return !mgTemplates || !item.template_id || mgTemplates.includes(item.template_id);
}

export function sourceBlocker(key: SupplementSourceKey, items: SupplementWorkItem[], states?: SourceState[], mgTemplates?: string[]): string | null {
  const state = states?.find(row => row.key === key);
  if (states && (!state || !state.available)) return state?.reason || "暂未开通";
  if (key === "mg") {
    if (items.length && items.every(item => !mgSupported(item, mgTemplates))) return MG_UNSUPPORTED;
    return null;
  }
  if (items.length && items.every(item => item.supports_images === false)) return "当前模板没有配图位置，换一个支持配图的模板后可用";
  if ((key === "stock" || key === "ai_image") && items.length && items.every(item => !item.script_text.trim())) {
    return "需要口播稿才能按句匹配";
  }
  return null;
}

function unique(ids: string[]): string[] {
  return [...new Set(ids)];
}

export function deriveMaterialIds(value: SupplementMaterialsValue, selection: SupplementItemSelection | undefined): string[] {
  if (!selection || value.mode !== "custom") return [];
  const by = selection.by_source ?? {};
  return unique(MATERIAL_SOURCES.flatMap(source => (value.sources[source]?.enabled ? by[source] ?? [] : [])));
}

function rederive(value: SupplementMaterialsValue): SupplementMaterialsValue {
  const items: Record<string, SupplementItemSelection> = {};
  for (const [id, selection] of Object.entries(value.items)) {
    const ids = deriveMaterialIds(value, selection);
    const pins = Object.fromEntries(Object.entries(selection.pins ?? {}).filter(([material]) => ids.includes(material)));
    items[id] = { ...selection, material_ids: ids, pins };
  }
  return { ...value, items };
}

export function setMode(value: SupplementMaterialsValue, mode: "none" | "custom"): SupplementMaterialsValue {
  return rederive({ ...value, mode });
}

export function toggleSource(value: SupplementMaterialsValue, key: SupplementSourceKey, enabled: boolean, maxImages = 4): SupplementMaterialsValue {
  const current = value.sources;
  const sources = { ...current };
  if (key === "mine") sources.mine = { placement: current.mine?.placement ?? "auto", enabled };
  if (key === "stock") sources.stock = { enabled };
  if (key === "ai_image") sources.ai_image = { max_images: current.ai_image?.max_images ?? maxImages, enabled };
  if (key === "mg") sources.mg = { style: current.mg?.style ?? "paper", enabled };
  return rederive({ ...value, sources });
}

export function setPlacement(value: SupplementMaterialsValue, placement: "auto" | "manual"): SupplementMaterialsValue {
  const next = { ...value, sources: { ...value.sources, mine: { enabled: value.sources.mine?.enabled ?? true, placement } } };
  if (placement === "auto") {
    next.items = Object.fromEntries(Object.entries(next.items).map(([id, row]) => [id, { ...row, pins: {} }]));
  }
  return rederive(next);
}

export function setMgStyle(value: SupplementMaterialsValue, style: SupplementStyle): SupplementMaterialsValue {
  return { ...value, sources: { ...value.sources, mg: { enabled: value.sources.mg?.enabled ?? true, style } } };
}

export function setSourceMaterials(value: SupplementMaterialsValue, itemId: string, source: MaterialSourceKey, ids: string[]): SupplementMaterialsValue {
  const selection = value.items[itemId] ?? { material_ids: [] };
  const by_source = { ...(selection.by_source ?? {}), [source]: unique(ids) };
  return rederive({ ...value, items: { ...value.items, [itemId]: { ...selection, by_source } } });
}

export function setPin(value: SupplementMaterialsValue, itemId: string, materialId: string, sentence: number | null): SupplementMaterialsValue {
  const selection = value.items[itemId] ?? { material_ids: [] };
  const pins = { ...(selection.pins ?? {}) };
  if (sentence === null) delete pins[materialId];
  else pins[materialId] = sentence;
  return rederive({ ...value, items: { ...value.items, [itemId]: { ...selection, pins } } });
}

export function setPending(value: SupplementMaterialsValue, pending: number): SupplementMaterialsValue {
  return value.pending === pending ? value : { ...value, pending: Math.max(0, pending) };
}

/** What W3 sends with each work item's planning request. */
export function supplementForWorkItem(value: SupplementMaterialsValue, workItemId: string): {
  material_ids: string[];
  supplement?: { mg: { style: SupplementStyle } };
} {
  if (value.mode !== "custom") return { material_ids: [] };
  const material_ids = deriveMaterialIds(value, value.items[workItemId]);
  const mg = value.sources.mg;
  return mg?.enabled ? { material_ids, supplement: { mg: { style: mg.style } } } : { material_ids };
}

export function aiCost(count: number, creditsPerImage: number | null | undefined): string {
  if (!count) return "不生成";
  if (!isPriced(creditsPerImage)) return `${count} 张，${FREE_TRIAL_TEXT}`;
  return `${count} 张 × ${creditsPerImage} 积分 = ${count * creditsPerImage} 积分`;
}

export function supplementSummary(value: SupplementMaterialsValue, counts?: Partial<Record<MaterialSourceKey, number>>): string {
  if (value.mode !== "custom") return "不加素材";
  const parts: string[] = [];
  const total = (source: MaterialSourceKey) =>
    counts?.[source] ?? Object.values(value.items).reduce((sum, row) => sum + (row.by_source?.[source]?.length ?? 0), 0);
  if (value.sources.mine?.enabled) parts.push(`我的素材 ${total("mine")} 个`);
  if (value.sources.stock?.enabled) parts.push(`免费素材 ${total("stock")} 个`);
  if (value.sources.ai_image?.enabled) parts.push(`AI 配图 ${total("ai_image")} 张`);
  if (value.sources.mg?.enabled) parts.push(`MG 动效（${STYLE_COPY[value.sources.mg.style]}）`);
  return parts.length ? `补充素材：${parts.join(" · ")}` : "补充素材：还没选来源";
}

export function licenceLine(provenance: Record<string, unknown> | null | undefined): string {
  if (!provenance) return "";
  const author = typeof provenance.author === "string" ? provenance.author : "";
  const licence = typeof provenance.license === "string" ? provenance.license : "";
  const provider = typeof provenance.provider === "string" ? provenance.provider : "";
  const label = ({ pexels: "Pexels", pixabay: "Pixabay", openverse: "Openverse", commons: "维基共享资源", site_image_gateway: "AI 生成" } as Record<string, string>)[provider] ?? provider;
  return [label, author && `作者 ${author}`, licence].filter(Boolean).join(" · ");
}
