/**
 * 全自动爆款文案的纯函数：平台多选、条数、按平台平分（与后端 video_auto_writing.allocation 同一规则）、
 * 预计耗时、结果按平台分组、旧版本「存入文案库」的请求。
 * 不依赖 React 或接口，也没有相对 import，可直接用 node --test 测。
 */

export type AutoPlatform = "douyin" | "xiaohongshu";
export const AUTO_PLATFORMS: AutoPlatform[] = ["douyin", "xiaohongshu"];
export const AUTO_PLATFORM_LABEL: Record<AutoPlatform, string> = { douyin: "抖音", xiaohongshu: "小红书" };
export const AUTO_PLATFORM_HINT: Record<AutoPlatform, string> = { douyin: "标题 ≤30 字，正文短", xiaohongshu: "标题 ≤20 字，正文分段" };
/** 不传条数时后端写的版数（以前固定 3 版）。 */
export const DEFAULT_COUNT = 3;
export const MIN_COUNT = 1;
export const MAX_COUNT = 10;
/** 每个平台同时写几版（后端每平台 3 个并发）。 */
const PARALLEL_WRITES = 3;

export const isAutoPlatform = (value: unknown): value is AutoPlatform => value === "douyin" || value === "xiaohongshu";

/** 勾选/取消一个平台；按勾选顺序保存，至少留一个。 */
export function togglePlatform(picked: AutoPlatform[], platform: AutoPlatform): AutoPlatform[] {
  if (picked.includes(platform)) return picked.length > 1 ? picked.filter(p => p !== platform) : picked;
  return [...picked, platform];
}

/** 输入框里的条数：1–10 的整数才算数，否则 null（不能提交）。 */
export function parseCount(raw: string | number): number | null {
  const text = String(raw).trim();
  if (!/^\d{1,2}$/.test(text)) return null;
  const n = Number(text);
  return n >= MIN_COUNT && n <= MAX_COUNT ? n : null;
}

export function stepCount(current: number | null, delta: number): number {
  const base = current ?? DEFAULT_COUNT;
  return Math.min(MAX_COUNT, Math.max(MIN_COUNT, base + delta));
}

/** N 条按勾选顺序平分；奇数时多出的 1 条给先勾选的平台。 */
export function allocate(count: number, platforms: AutoPlatform[]): Record<string, number> {
  const out: Record<string, number> = {};
  if (!platforms.length) return out;
  const base = Math.floor(count / platforms.length), extra = count % platforms.length;
  platforms.forEach((p, i) => { out[p] = base + (i < extra ? 1 : 0); });
  return out;
}

/** 「抖音 2 条 · 小红书 1 条」。 */
export function allocationText(count: number, platforms: AutoPlatform[]): string {
  const split = allocate(count, platforms);
  return platforms.map(p => `${AUTO_PLATFORM_LABEL[p]} ${split[p]} 条`).join(" · ");
}

/** 分配预览下面的一句补充；没有要说的返回空串。 */
export function allocationNote(count: number, platforms: AutoPlatform[]): string {
  if (platforms.length < 2) return "";
  if (count < platforms.length) return `只写 1 条时只给先勾选的${AUTO_PLATFORM_LABEL[platforms[0]]}写；想两个平台都有，条数至少填 2。`;
  if (count % platforms.length) return `条数是单数时，多出的 1 条给先勾选的${AUTO_PLATFORM_LABEL[platforms[0]]}。`;
  return "";
}

/** 预计耗时，口径与以前一致：一个平台 3 条约 3–5 分钟；条数多了按每 3 条一轮加时间，两个平台同时进行。 */
export function estimateMinutes(count: number, platforms: AutoPlatform[]): [number, number] {
  const split = allocate(count, platforms);
  const most = Math.max(1, ...Object.values(split));
  const rounds = Math.ceil(most / PARALLEL_WRITES);
  return [2 + rounds, 3 + 2 * rounds];
}

export function estimateText(count: number, platforms: AutoPlatform[]): string {
  const [low, high] = estimateMinutes(count, platforms);
  return `大约 ${low}–${high} 分钟`;
}

/**
 * 要找几次对标：两个平台各搜一次；贴链接时只用你给的链接（一次）；只给一个平台写时一次。
 */
export function searchCount(count: number, platforms: AutoPlatform[], query: string): number {
  if (/https?:\/\//.test(query)) return 1;
  return Object.values(allocate(count, platforms)).filter(n => n > 0).length || 1;
}

/**
 * 积分合计（价格都配置了才有数）：每次找对标 1 次搜索 + 最多 3 次拆解 + 1 次对比，每条稿子 1 次写稿。
 * 价格为空返回 null，页面显示「灰度测试期间不扣积分」。
 */
export function creditTotal(count: number, searches: number, prices: { search: number | null | undefined; write: number | null | undefined }): number | null {
  const { search, write } = prices;
  if (typeof search !== "number" || typeof write !== "number") return null;
  return searches * (search + 4 * write) + count * write;
}

/* ----------------------------------------------------------- 结果 */

export type PlatformDraft = { key: string; platform?: string | null };

/** 按平台分组（顺序 = 请求里的平台顺序，再补上其他出现过的）；每版没写平台时算作请求的第一个平台。 */
export function groupByPlatform<T extends PlatformDraft>(drafts: T[], order: AutoPlatform[]): { platform: AutoPlatform; drafts: T[] }[] {
  const fallback = order[0] || "douyin";
  const of = (d: T): AutoPlatform => isAutoPlatform(d.platform) ? d.platform : fallback;
  const seen = [...order, ...drafts.map(of)].filter((p, i, all) => all.indexOf(p) === i);
  return seen.map(platform => ({ platform, drafts: drafts.filter(d => of(d) === platform) })).filter(g => g.drafts.length > 0);
}

/** 请求里的平台：新请求有 platforms；旧请求只有 platform。 */
export function requestPlatforms(request: { platform?: string; platforms?: string[] } | undefined): AutoPlatform[] {
  const list = (request?.platforms || []).filter(isAutoPlatform);
  if (list.length) return [...new Set(list)];
  return [isAutoPlatform(request?.platform) ? request.platform : "douyin"];
}

export type LaneView = LaneInput & { platform: AutoPlatform | null };
type LaneInput = { search_task_id?: string; benchmarks?: { reference_id: string; analysis_id?: string; platform_id: string; reason: string }[]; main_reference_id?: string; comparison?: unknown; status?: string; message?: string; stage?: string; ranked?: { platform_id: string; reason: string }[] };

/** 对标线：两个平台分开找时各一条（result.lanes），否则就是 result 本身（以前的结构）。 */
export function lanesOf(result: LaneInput & { lanes?: Record<string, LaneInput> }): LaneView[] {
  const lanes = result.lanes;
  if (lanes && Object.keys(lanes).length) return Object.entries(lanes).map(([key, lane]) => ({ ...lane, platform: isAutoPlatform(key) ? key : null }));
  return [{ ...result, platform: null }];
}

/** 旧版本「存入文案库」的请求体：按文稿 id 去重，重复点击、刷新后再点都不会多存。 */
export function storeBody(draft: { document_id: string; platform: AutoPlatform | "" }, parts: { publish_title: string; publish_body: string; script: string }, requestId: string) {
  return {
    request_id: requestId,
    writing_document_id: draft.document_id,
    source: "auto_writing" as const,
    platform: draft.platform,
    publish_title: parts.publish_title.trim().slice(0, 80),
    publish_body: parts.publish_body.trim().slice(0, 2000),
    script: parts.script.trim(),
  };
}
