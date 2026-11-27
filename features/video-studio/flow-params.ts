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
