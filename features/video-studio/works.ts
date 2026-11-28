/**
 * 我的作品 / 成片：作品卡片的统一视图（纯函数，node --test 直接测）。
 *
 * 三种来源合成一个主页式网格：
 * - 作品条目（契约 C2 work item）：有封面、发布标题、正文、口播稿；进行中的显示阶段角标。
 * - 旧的剪辑成片（/editing-works，没有作品条目）：用视频首帧做封面、项目名做标题。
 * - 旧的口播视频（/generation-tasks，没有作品条目）：用视频首帧、口播稿首句做标题。
 */

export type Platform = "douyin" | "xiaohongshu";
export const TITLE_LIMITS: Record<Platform, number> = { douyin: 30, xiaohongshu: 20 };
export const BODY_LIMIT = 1000;
export const COVER_TEXT_LIMIT = 40;
export const COVER_TEXT_SUGGESTED = 14;

export type WorkStage = "talking" | "editing" | "finishing" | "done";
export type WorkStatus = "pending" | "queued" | "running" | "succeeded" | "failed" | "canceled";

export type WorkItemLike = {
  id: string; batch_id: string; position: number; created_at: string; updated_at?: string; version: number;
  script_document_id?: string | null; publish_title?: string | null; publish_body?: string | null; script_text?: string | null;
  generation_task_id?: string | null; editing_task_id?: string | null; cover_asset_id?: string | null;
  source_video_ref?: { kind: string; id: string } | null;
  stage: WorkStage; status: WorkStatus; error?: string | null;
  /** B1 软删除：有值即已从「我的作品」移除（文件保留）。 */
  deleted_at?: string | null;
  /** C10 已发布标记（商家自己标，不接平台）。 */
  published_at?: string | null;
};

/** 与后端 group_of 同一口径（/work-items?group= 与 /work-items/summary）：每条恰好属于一组。 */
export type WorkGroup = "active" | "failed" | "done" | "finishing" | "other";
export function itemGroup(item: Pick<WorkItemLike, "stage" | "status">): WorkGroup {
  if (item.status === "queued" || item.status === "running") return "active";
  if (item.status === "failed" || item.status === "canceled") return "failed";
  if (item.stage === "done") return "done";
  if (item.stage === "finishing") return "finishing";
  return "other";
}
export type EditingWorkLike = { task_id: string; project_id: string; project_title: string; created_at: string; final: { url: string; duration_ms?: number | null } };
export type TalkJobLike = { id: string; kind: string; status: string; created_at: string; video_url?: string | null; snapshot?: { draft?: { name?: string; text?: string } } | null };

export type ProgressTone = "running" | "waiting" | "failed";
export type WorkCard = {
  key: string;
  source: "item" | "edit" | "talk";
  /** Order inside a batch (C2 position); items of one batch share created_at. */
  position: number;
  itemId: string | null;
  batchId: string | null;
  editingTaskId: string | null;
  generationTaskId: string | null;
  projectId: string | null;
  title: string;
  titleIsFallback: boolean;
  body: string;
  script: string;
  coverId: string | null;
  videoUrl: string | null;
  createdAt: string;
  progress: { label: string; tone: ProgressTone } | null;
  finished: boolean;
  /** A playable video exists (口播 finished or later); otherwise do not ask for one. */
  hasVideo: boolean;
  /** Where the server cuts a grid thumbnail from, when there is no cover. */
  poster: { kind: "editing" | "generation"; id: string } | null;
  /** 作品条目的分组（旧的剪辑/口播卡片按完成与否折算成 done / active）。 */
  group: WorkGroup;
  stage: WorkStage | null;
  version: number | null;
  publishedAt: string | null;
};

/** Server-cut 3:4 thumbnail for a work without a cover (cached, lazy-loaded). */
export function posterPath(workspaceId: string, card: Pick<WorkCard, "poster">): string | null {
  return card.poster ? `/api/v1/video-studio/workspaces/${workspaceId}/work-posters/${card.poster.kind}/${card.poster.id}` : null;
}

const SENTENCE_END = /[。！？!?；;\n]/;

/** 口播稿首句（旧作品兜底标题）：到第一个句末标点，最多 max 字。 */
export function firstSentence(text: string | null | undefined, max = 28): string {
  const clean = (text ?? "").replace(/\s+/g, " ").trim();
  if (!clean) return "";
  const cut = clean.search(SENTENCE_END);
  const sentence = (cut > 0 ? clean.slice(0, cut) : clean).trim();
  const chars = Array.from(sentence);
  return chars.length > max ? chars.slice(0, max).join("") + "…" : sentence;
}

/** 字数按字符（emoji 算 1 个）计。 */
export function countChars(text: string | null | undefined): number {
  return Array.from(text ?? "").length;
}

/** 封面大字默认值：发布标题去掉话题标签和 emoji（字体里没有）。与后端 default_cover_text 一致。 */
export function defaultCoverText(title: string | null | undefined): string {
  const words = (title ?? "").replace(/　/g, " ").split(/\s+/).filter(word => word && !word.startsWith("#"));
  const kept = Array.from(words.join(" ")).filter(ch => !/\p{Extended_Pictographic}|[\u{FE0F}\u{200D}]/u.test(ch)).join("");
  return Array.from(kept.replace(/\s+/g, " ").trim()).slice(0, COVER_TEXT_LIMIT).join("");
}

/** 正文拆成普通文字与 #话题，预览里话题单独着色。 */
export function splitTopics(body: string): { text: string; topic: boolean }[] {
  const parts: { text: string; topic: boolean }[] = [];
  const pattern = /#[^\s#]+/gu;
  let last = 0;
  for (const match of body.matchAll(pattern)) {
    if (match.index! > last) parts.push({ text: body.slice(last, match.index), topic: false });
    parts.push({ text: match[0], topic: true });
    last = match.index! + match[0].length;
  }
  if (last < body.length) parts.push({ text: body.slice(last), topic: false });
  return parts;
}

const STAGE_COPY: Record<WorkStage, { running: string; failed: string }> = {
  talking: { running: "口播生成中", failed: "口播未完成" },
  editing: { running: "剪辑中", failed: "剪辑未完成" },
  finishing: { running: "待成片", failed: "待成片" },
  done: { running: "", failed: "" },
};

/** 进行中作品的角标；已完成的没有角标。 */
export function itemProgress(item: Pick<WorkItemLike, "stage" | "status">): WorkCard["progress"] {
  if (item.stage === "done") return null;
  if (item.status === "failed" || item.status === "canceled") return { label: STAGE_COPY[item.stage].failed, tone: item.stage === "finishing" ? "waiting" : "failed" };
  if (item.stage === "finishing") return { label: "待成片", tone: "waiting" };
  return { label: STAGE_COPY[item.stage].running, tone: "running" };
}

export function itemCard(item: WorkItemLike): WorkCard {
  const title = (item.publish_title ?? "").trim();
  const fallback = firstSentence(item.script_text);
  return {
    key: `item:${item.id}`, source: "item", position: item.position ?? 0, itemId: item.id, batchId: item.batch_id,
    editingTaskId: item.editing_task_id ?? null, generationTaskId: item.generation_task_id ?? null, projectId: null,
    title: title || fallback || "未命名作品", titleIsFallback: !title,
    body: item.publish_body ?? "", script: item.script_text ?? "",
    coverId: item.cover_asset_id ?? null, videoUrl: null, createdAt: item.created_at,
    progress: itemProgress(item), finished: item.stage === "done",
    hasVideo: item.stage !== "talking" || item.status === "succeeded",
    poster: item.editing_task_id ? { kind: "editing", id: item.editing_task_id }
      : item.generation_task_id && (item.stage !== "talking" || item.status === "succeeded") ? { kind: "generation", id: item.generation_task_id } : null,
    group: itemGroup(item), stage: item.stage, version: item.version ?? null, publishedAt: item.published_at ?? null,
  };
}

export function editCard(work: EditingWorkLike): WorkCard {
  const title = work.project_title && work.project_title !== "未命名项目" ? work.project_title : "";
  return {
    key: `edit:${work.task_id}`, source: "edit", position: 0, itemId: null, batchId: null, editingTaskId: work.task_id,
    generationTaskId: null, projectId: work.project_id,
    title: title || "未命名作品", titleIsFallback: true, body: "", script: "",
    coverId: null, videoUrl: work.final.url, createdAt: work.created_at, progress: null, finished: true, hasVideo: true,
    poster: { kind: "editing", id: work.task_id },
    group: "done", stage: null, version: null, publishedAt: null,
  };
}

const TALK_RUNNING = new Set(["queued", "running", "submitted", "processing", "unknown", "awaiting_result"]);

export function talkCard(job: TalkJobLike): WorkCard | null {
  if (job.kind !== "lipsync" || !(job.status === "completed" || TALK_RUNNING.has(job.status))) return null;
  const script = job.snapshot?.draft?.text ?? "";
  const name = (job.snapshot?.draft?.name ?? "").trim();
  const title = firstSentence(script) || (name && name !== "未命名视频" ? name : "") || "未命名作品";
  return {
    key: `talk:${job.id}`, source: "talk", position: 0, itemId: null, batchId: null, editingTaskId: null, generationTaskId: job.id, projectId: null,
    title, titleIsFallback: true, body: "", script,
    coverId: null, videoUrl: job.status === "completed" ? job.video_url ?? null : null, createdAt: job.created_at,
    progress: job.status === "completed" ? null : { label: "口播生成中", tone: "running" }, finished: job.status === "completed",
    hasVideo: job.status === "completed",
    poster: job.status === "completed" ? { kind: "generation", id: job.id } : null,
    group: job.status === "completed" ? "done" : "active", stage: null, version: null, publishedAt: null,
  };
}

/**
 * 合成网格：作品条目优先；已被作品条目引用的旧剪辑/口播不再单独出现。新的在前。
 * B2：作品条目分页加载时（itemsComplete=false），比已加载的最早一条作品条目还早的旧剪辑/口播先不出——
 * 它们可能属于还没翻到的作品条目，避免以「没封面、没标题」的旧卡片重复出现；翻到底后再全部放出。
 * B1：已删除（deleted_at）的条目不出现，它引用的剪辑/口播也不会以旧卡片冒出来。
 */
export function mergeWorkCards(items: WorkItemLike[], edits: EditingWorkLike[], jobs: TalkJobLike[], options: { itemsComplete?: boolean } = {}): WorkCard[] {
  const editIds = new Set(items.map(item => item.editing_task_id).filter(Boolean));
  const talkIds = new Set(items.flatMap(item => [item.generation_task_id, item.source_video_ref?.kind === "talking" ? item.source_video_ref.id : null]).filter(Boolean));
  const live = items.filter(item => !item.deleted_at);
  const oldest = options.itemsComplete === false && live.length ? Math.min(...live.map(item => Date.parse(item.created_at))) : -Infinity;
  const loaded = (createdAt: string) => Date.parse(createdAt) >= oldest;
  const cards = [
    ...live.map(itemCard),
    ...edits.filter(work => !editIds.has(work.task_id) && loaded(work.created_at)).map(editCard),
    ...jobs.filter(job => !talkIds.has(job.id) && loaded(job.created_at)).map(talkCard).filter((card): card is WorkCard => card !== null),
  ];
  return cards.sort((a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt) || a.position - b.position || a.key.localeCompare(b.key));
}

export type WorkRange = "all" | "7d" | "30d";
export type WorkFilter = { batch?: string | null; range?: WorkRange; keyword?: string; now?: number };

export function filterWorkCards(cards: WorkCard[], filter: WorkFilter): WorkCard[] {
  const now = filter.now ?? Date.now();
  const days = filter.range === "7d" ? 7 : filter.range === "30d" ? 30 : 0;
  const term = (filter.keyword ?? "").trim().toLocaleLowerCase();
  return cards.filter(card =>
    (!filter.batch || card.batchId === filter.batch)
    && (!days || now - Date.parse(card.createdAt) <= days * 86400000)
    && (!term || `${card.title} ${card.body} ${card.script}`.toLocaleLowerCase().includes(term)));
}

/** 批次筛选项：按批次第一次出现的时间，新的在前。 */
export function batchOptions(cards: WorkCard[]): { id: string; label: string; count: number }[] {
  const seen = new Map<string, { createdAt: string; count: number }>();
  for (const card of cards) {
    if (!card.batchId) continue;
    const entry = seen.get(card.batchId);
    if (entry) entry.count += 1; else seen.set(card.batchId, { createdAt: card.createdAt, count: 1 });
  }
  return [...seen.entries()]
    .sort((a, b) => Date.parse(b[1].createdAt) - Date.parse(a[1].createdAt))
    .map(([id, entry]) => ({ id, count: entry.count, label: `${shortDate(entry.createdAt)} · ${entry.count} 条` }));
}

export function shortDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return `${date.getMonth() + 1}月${date.getDate()}日 ${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

/** 预览里键盘左右切换：到头不循环。 */
export function neighbour(cards: WorkCard[], key: string, step: 1 | -1): WorkCard | null {
  const index = cards.findIndex(card => card.key === key);
  if (index < 0) return null;
  return cards[index + step] ?? null;
}

/**
 * B1：主页网格只放有可播放视频的（已完成 + 待成片 + 旧的已完成成片）；
 * 生成中、失败、口播完成待剪辑的放到网格下方「未完成」区。
 */
export function splitWorkCards(cards: WorkCard[]): { grid: WorkCard[]; running: WorkCard[]; unfinished: WorkCard[] } {
  return {
    grid: cards.filter(card => card.group === "done" || card.group === "finishing"),
    running: cards.filter(card => card.group === "active"),
    unfinished: cards.filter(card => card.group === "failed" || card.group === "other"),
  };
}

export type WorkSummary = { total: number; active: number; failed: number; done: number; finishing: number; other: number };

/** 顶部计数「作品 / 待成片 / 生成中 / 未完成」：作品条目用服务端计数，旧的已完成成片按已加载的加上。 */
export function workCounts(summary: WorkSummary | undefined, cards: WorkCard[]): { works: number; finishing: number; running: number; unfinished: number } {
  const legacy = cards.filter(card => card.source !== "item");
  const legacyDone = legacy.filter(card => card.group === "done").length;
  const legacyRunning = legacy.filter(card => card.group === "active").length;
  if (!summary) {
    const split = splitWorkCards(cards);
    return { works: split.grid.filter(card => card.group === "done").length, finishing: split.grid.filter(card => card.group === "finishing").length, running: split.running.length, unfinished: split.unfinished.length };
  }
  return { works: summary.done + legacyDone, finishing: summary.finishing, running: summary.active + legacyRunning, unfinished: summary.failed + summary.other };
}

/** 未完成区每条的说明与可做的事。 */
export function unfinishedState(card: Pick<WorkCard, "group" | "stage">): { label: string; retry: "talking" | "editing" | null; step: "voice" | "editing" | "finish"; deletable: boolean } {
  const stage = card.stage ?? "talking";
  const step = stage === "talking" ? "voice" : stage === "editing" ? "editing" : "finish";
  if (card.group === "active") return { label: stage === "talking" ? "口播生成中" : stage === "editing" ? "剪辑中" : "处理中", retry: null, step, deletable: false };
  if (card.group === "failed") return { label: stage === "talking" ? "口播没有生成成功" : stage === "editing" ? "剪辑没有成功" : "没有完成", retry: stage === "talking" ? "talking" : stage === "editing" ? "editing" : null, step, deletable: true };
  return { label: stage === "talking" ? "口播已完成，还没剪辑" : stage === "editing" ? "还没开始剪辑" : "待处理", retry: null, step: stage === "talking" ? "editing" : step, deletable: true };
}

export type PublishFilter = "all" | "published" | "unpublished";
/** C10：按已发布标记筛选（只对网格里的作品生效）。 */
export function filterPublished(cards: WorkCard[], filter: PublishFilter): WorkCard[] {
  if (filter === "all") return cards;
  return cards.filter(card => filter === "published" ? Boolean(card.publishedAt) : !card.publishedAt);
}
