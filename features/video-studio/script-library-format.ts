/**
 * 文案库（契约 C1）的纯函数：条目类型、显示标题、口播字数/时长、多选状态。
 * 跳转参数（`?scripts=`）在 flow-params.ts。不依赖 React 或接口，可直接用 node --test 测。
 */

export type LibraryPlatform = "douyin" | "xiaohongshu";
export type LibrarySource = "auto_writing" | "manual" | "imported";
export type BenchmarkRef = { reference_document_id?: string; platform?: string; title?: string; author_name?: string; source_url?: string };
export type LibraryEntry = {
  id: string; created_at: string; updated_at: string; source: LibrarySource; platform: LibraryPlatform | "";
  publish_title: string; publish_body: string; script: string; benchmark_refs: BenchmarkRef[];
  revision: number; project_id: string | null; writing_document_id: string | null;
  display_title: string; script_chars: number; script_seconds: number;
};
export type LibraryPage = { items: LibraryEntry[]; total: number; limit: number; offset: number; missing_ids: string[] };
export type LibraryEdit = { publish_title: string; publish_body: string; script: string };
export type FillStatus = { task_id: string; status: string; error_code: string | null; message: string; entry: LibraryEntry | null };

/** Only the script: an entry saved before v3 (or by hand) that can get a title and body written. */
export function needsFill(entry: Pick<LibraryEntry, "publish_title" | "publish_body" | "script">): boolean {
  return !entry.publish_title.trim() && !entry.publish_body.trim() && !!entry.script.trim();
}

export const LIBRARY_PLATFORM_LABEL: Record<LibraryPlatform, string> = { douyin: "抖音", xiaohongshu: "小红书" };
export const SOURCE_LABEL: Record<LibrarySource, string> = { auto_writing: "AI 全自动", manual: "手动", imported: "导入" };
export const TITLE_LIMIT: Record<LibraryPlatform, number> = { douyin: 30, xiaohongshu: 20 };
/** At most this many can be chosen at once; the same cap as MAX_SCRIPTS in flow-params.ts. */
export const MAX_SELECTED = 50;
/** Same estimate as the server and the old result cards: about 4.8 spoken characters a second. */
export const CHARS_PER_SECOND = 4.8;


export function spokenChars(text: string): number {
  return (text.match(/[\p{L}\p{N}]/gu) || []).length;
}

export function scriptStats(text: string): { chars: number; seconds: number; label: string } {
  const chars = spokenChars(text);
  const seconds = chars ? Math.max(1, Math.round(chars / CHARS_PER_SECOND)) : 0;
  const time = seconds >= 60 ? `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒` : `${seconds} 秒`;
  return { chars, seconds, label: chars ? `${chars} 字 · 约 ${time}` : "还没有口播稿" };
}

export function firstSentence(text: string, limit = 24): string {
  for (const raw of text.split(/[。！？!?\n]+/)) {
    const piece = raw.replace(/^[\s，,、；;：:]+|[\s，,、；;：:]+$/g, "");
    if (piece) return piece.length <= limit ? piece : `${piece.slice(0, limit)}…`;
  }
  return "";
}

/** The title, or for old entries without one the script's first sentence. */
export function displayTitle(entry: Pick<LibraryEntry, "publish_title" | "script">): string {
  return entry.publish_title.trim() || firstSentence(entry.script) || "未命名文案";
}

export function hashtags(body: string): string[] {
  const tags = body.match(/#[^\s#，,。！？!?、；;：:（）()【】[\]「」]+/g) || [];
  return [...new Set(tags)];
}

/** One line of the body without its hashtags, for the list. */
export function bodySummary(body: string, limit = 60): string {
  const text = body.replace(/#[^\s#，,。！？!?、；;：:（）()【】[\]「」]+/g, "").replace(/\s+/g, " ").trim();
  return text.length <= limit ? text : `${text.slice(0, limit)}…`;
}

export function titleLength(title: string): number {
  return [...title.replace(/[​-‍︎️]/g, "")].length;
}

/** A Chinese hint when the title is longer than the platform allows; "" when fine. */
export function titleWarning(title: string, platform: LibraryPlatform | ""): string {
  if (!platform) return "";
  const n = titleLength(title.trim()), limit = TITLE_LIMIT[platform];
  return n > limit ? `${LIBRARY_PLATFORM_LABEL[platform]}标题最多 ${limit} 字，现在 ${n} 字` : "";
}

/* -------------------------------------------------------------- 多选 */

export function toggle(selected: string[], id: string): string[] {
  return selected.includes(id) ? selected.filter(v => v !== id) : [...selected, id].slice(0, MAX_SELECTED);
}

/** 全选当前页：all of the page if any is missing, otherwise none of the page; other pages stay. */
export function togglePage(selected: string[], pageIds: string[]): string[] {
  const all = pageIds.length > 0 && pageIds.every(id => selected.includes(id));
  if (all) return selected.filter(id => !pageIds.includes(id));
  return [...selected, ...pageIds.filter(id => !selected.includes(id))].slice(0, MAX_SELECTED);
}

export function pageState(selected: string[], pageIds: string[]): "none" | "some" | "all" {
  const n = pageIds.filter(id => selected.includes(id)).length;
  return n === 0 ? "none" : n === pageIds.length ? "all" : "some";
}

/* ------------------------------------------------------------- 编辑 */

export function editOf(entry: Pick<LibraryEntry, "publish_title" | "publish_body" | "script">): LibraryEdit {
  return { publish_title: entry.publish_title, publish_body: entry.publish_body, script: entry.script };
}

export function editChanged(entry: Pick<LibraryEntry, "publish_title" | "publish_body" | "script">, edit: LibraryEdit): boolean {
  return entry.publish_title !== edit.publish_title.trim() || entry.publish_body !== edit.publish_body.trim() || entry.script !== edit.script.trim();
}

/** Text for 「复制」: title, body and script are copied one at a time; this is the whole set. */
export function fullText(entry: Pick<LibraryEntry, "publish_title" | "publish_body" | "script">): string {
  return [entry.publish_title && `标题：${entry.publish_title}`, entry.publish_body && `正文：\n${entry.publish_body}`, `口播稿：\n${entry.script}`].filter(Boolean).join("\n\n");
}
