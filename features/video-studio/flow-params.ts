/**
 * 视频空间各步之间的跳转参数（全局共用，一处解析）：
 * - `?scripts=id1,id2`：文案库选中的文案（W1 生成，口播页 W2 读取）。
 * - `?batch=`：作品批次（W5 在本文件补充）。
 * 纯函数，不依赖 React，可直接用 node --test 测。
 */

export const VOICE_SCREEN = "/video-studio/create";
export const MAX_SCRIPTS = 50;
const ID = /^[0-9A-Za-z-]{1,40}$/;

/** Reads `?scripts=` (string, null or URLSearchParams): unique, valid ids, in order, at most 50. */
export function parseScriptsParam(value: string | null | undefined | URLSearchParams): string[] {
  const raw = value instanceof URLSearchParams ? value.get("scripts") : value;
  const ids: string[] = [];
  for (const piece of (raw || "").split(",")) {
    const id = piece.trim();
    if (id && ID.test(id) && !ids.includes(id)) ids.push(id);
    if (ids.length >= MAX_SCRIPTS) break;
  }
  return ids;
}

/** `/video-studio/create?scripts=id1,id2` (+ project when known), in the order chosen. */
export function voiceHref(ids: string[], projectId?: string): string {
  const clean = parseScriptsParam(ids.join(","));
  const params = new URLSearchParams();
  if (clean.length) params.set("scripts", clean.join(","));
  if (projectId) params.set("project", projectId);
  const query = params.toString().replace(/%2C/gi, ",");
  return query ? `${VOICE_SCREEN}?${query}` : VOICE_SCREEN;
}

// ---------------------------------------------------------------------------
// `?batch=` / `?item=`（W5）：一批作品条目（契约 C2 的 batch）在 口播 → 剪辑 → 成片 → 我的作品 之间传递。
// 口播页建好批次后跳 editingHref(batchId)；剪辑完成跳 finishHref({ batch })；
// 作品里对单条已完成视频重新成片用 finishHref({ item })；保存后回 worksHref(batchId)。

export const WRITING_SCREEN = "/video-studio/writing";
export const EDITING_SCREEN = "/video-studio/editing";
export const FINISH_SCREEN = "/video-studio/finish";
export const WORKS_SCREEN = "/video-studio/works";

export type FlowStep = "writing" | "voice" | "editing" | "finish";
export type FlowContext = { batch?: string | null; item?: string | null; scripts?: string[]; project?: string | null };

function single(value: string | null | undefined | URLSearchParams, key: string): string | null {
  const raw = (value instanceof URLSearchParams ? value.get(key) : value)?.trim() ?? "";
  return raw && ID.test(raw) ? raw : null;
}

/** Reads `?batch=`: one valid id, or null. */
export function parseBatchParam(value: string | null | undefined | URLSearchParams): string | null {
  return single(value, "batch");
}

/** Reads `?item=`: one valid work item id, or null. */
export function parseItemParam(value: string | null | undefined | URLSearchParams): string | null {
  return single(value, "item");
}

/** Reads every flow parameter at once (pages call this once and pass the result down). */
export function parseFlowParams(params: URLSearchParams): FlowContext {
  return {
    batch: parseBatchParam(params),
    item: parseItemParam(params),
    scripts: parseScriptsParam(params),
    project: single(params, "project"),
  };
}

function withQuery(path: string, entries: [string, string | null | undefined][]): string {
  const params = new URLSearchParams();
  for (const [key, value] of entries) {
    const clean = key === "scripts" ? value : single(value, key);
    if (clean) params.set(key, clean);
  }
  const query = params.toString().replace(/%2C/gi, ",");
  return query ? `${path}?${query}` : path;
}

/** `/video-studio/editing?batch=…`：剪辑这一批。 */
export function editingHref(batchId?: string | null, projectId?: string | null): string {
  return withQuery(EDITING_SCREEN, [["batch", batchId], ["project", projectId]]);
}

/** `/video-studio/finish?batch=…` 或 `?item=…`：给这一批（或单条）做封面、定标题正文。 */
export function finishHref(target: { batch?: string | null; item?: string | null }): string {
  return withQuery(FINISH_SCREEN, [["batch", target.batch], ["item", target.batch ? null : target.item]]);
}

/** `/video-studio/works?batch=…`：我的作品，可按批次筛选。 */
export function worksHref(batchId?: string | null): string {
  return withQuery(WORKS_SCREEN, [["batch", batchId]]);
}

/** Where a step-bar step goes, carrying whatever the flow already knows. */
export function stepHref(step: FlowStep, context: FlowContext = {}): string {
  const scripts = parseScriptsParam((context.scripts ?? []).join(","));
  if (step === "writing") return withQuery(WRITING_SCREEN, [["project", context.project]]);
  if (step === "voice") {
    return withQuery(VOICE_SCREEN, [["scripts", scripts.join(",") || null], ["batch", context.batch], ["project", context.project]]);
  }
  if (step === "editing") return editingHref(context.batch, context.project);
  return finishHref({ batch: context.batch, item: context.item });
}
