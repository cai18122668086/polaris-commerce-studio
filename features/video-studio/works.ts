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
};
export type EditingWorkLike = { task_id: string; project_id: string; project_title: string; created_at: string; final: { url: string; duration_ms?: number | null } };
export type TalkJobLike = { id: string; kind: string; status: string; created_at: string; video_url?: string | null; snapshot?: { draft?: { name?: string; text?: string } } | null };

export type ProgressTone = "running" | "waiting" | "failed";
export type WorkCard = {
  key: string;
  source: "item" | "edit" | "talk";
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
    key: `item:${item.id}`, source: "item", itemId: item.id, batchId: item.batch_id,
    editingTaskId: item.editing_task_id ?? null, generationTaskId: item.generation_task_id ?? null, projectId: null,
    title: title || fallback || "未命名作品", titleIsFallback: !title,
    body: item.publish_body ?? "", script: item.script_text ?? "",
    coverId: item.cover_asset_id ?? null, videoUrl: null, createdAt: item.created_at,
    progress: itemProgress(item), finished: item.stage === "done",
    hasVideo: item.stage !== "talking" || item.status === "succeeded",
    poster: item.editing_task_id ? { kind: "editing", id: item.editing_task_id }
      : item.generation_task_id && (item.stage !== "talking" || item.status === "succeeded") ? { kind: "generation", id: item.generation_task_id } : null,
  };
}

export function editCard(work: EditingWorkLike): WorkCard {
  const title = work.project_title && work.project_title !== "未命名项目" ? work.project_title : "";
  return {
    key: `edit:${work.task_id}`, source: "edit", itemId: null, batchId: null, editingTaskId: work.task_id,
    generationTaskId: null, projectId: work.project_id,
    title: title || "未命名作品", titleIsFallback: true, body: "", script: "",
    coverId: null, videoUrl: work.final.url, createdAt: work.created_at, progress: null, finished: true, hasVideo: true,
    poster: { kind: "editing", id: work.task_id },
  };
}

const TALK_RUNNING = new Set(["queued", "running", "submitted", "processing", "unknown", "awaiting_result"]);

export function talkCard(job: TalkJobLike): WorkCard | null {
  if (job.kind !== "lipsync" || !(job.status === "completed" || TALK_RUNNING.has(job.status))) return null;
  const script = job.snapshot?.draft?.text ?? "";
  const name = (job.snapshot?.draft?.name ?? "").trim();
  const title = firstSentence(script) || (name && name !== "未命名视频" ? name : "") || "未命名作品";
  return {
    key: `talk:${job.id}`, source: "talk", itemId: null, batchId: null, editingTaskId: null, generationTaskId: job.id, projectId: null,
    title, titleIsFallback: true, body: "", script,
    coverId: null, videoUrl: job.status === "completed" ? job.video_url ?? null : null, createdAt: job.created_at,
    progress: job.status === "completed" ? null : { label: "口播生成中", tone: "running" }, finished: job.status === "completed",
    hasVideo: job.status === "completed",
    poster: job.status === "completed" ? { kind: "generation", id: job.id } : null,
  };
}

/** 合成网格：作品条目优先；已被作品条目引用的旧剪辑/口播不再单独出现。新的在前。 */
export function mergeWorkCards(items: WorkItemLike[], edits: EditingWorkLike[], jobs: TalkJobLike[]): WorkCard[] {
  const editIds = new Set(items.map(item => item.editing_task_id).filter(Boolean));
  const talkIds = new Set(items.flatMap(item => [item.generation_task_id, item.source_video_ref?.kind === "talking" ? item.source_video_ref.id : null]).filter(Boolean));
  const cards = [
    ...items.map(itemCard),
    ...edits.filter(work => !editIds.has(work.task_id)).map(editCard),
    ...jobs.filter(job => !talkIds.has(job.id)).map(talkCard).filter((card): card is WorkCard => card !== null),
  ];
  return cards.sort((a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt) || a.key.localeCompare(b.key));
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
