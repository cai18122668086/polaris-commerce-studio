"use client";

/* 首页 → 创作首页 → 套图工作台：创作描述的一次性交接。
   - 描述存在 sessionStorage（只在当前标签页内有效，关掉标签页即清空）。
   - 只有从创作首页的套图卡片进入（链接带 ?from=create）时才交接；交接后立刻去掉该参数，刷新或从别处打开都不会再填。
   - 工作台对应栏里已有内容（用户写过的草稿）时不覆盖，以用户的为准；带入后用户的修改照常存为该工作台的草稿。 */

import { useEffect, useRef } from "react";

export const CREATION_BRIEF_KEY = "polaris.creationBrief";
const HANDOFF_PARAM = "from";
const HANDOFF_VALUE = "create";

/** 给创作首页的套图链接加上交接标记 */
export function withBriefHandoff(href: string) {
  const [path, query = ""] = href.split("?");
  const params = new URLSearchParams(query);
  params.set(HANDOFF_PARAM, HANDOFF_VALUE);
  return `${path}?${params}`;
}

/** 工作台里调用：ready 表示工作区已就绪且不是在查看已有任务；current 为目标栏当前内容 */
export function useCreationBriefHandoff(ready: boolean, current: string, apply: (value: string) => void) {
  const handled = useRef(false);
  useEffect(() => {
    if (!ready || handled.current) return;
    const url = new URL(window.location.href);
    if (url.searchParams.get(HANDOFF_PARAM) !== HANDOFF_VALUE) return;
    handled.current = true;
    url.searchParams.delete(HANDOFF_PARAM);
    window.history.replaceState(window.history.state, "", url.pathname + url.search + url.hash);
    if (current.trim()) return;
    const brief = window.sessionStorage.getItem(CREATION_BRIEF_KEY)?.trim();
    if (brief) apply(brief);
  }, [ready, current, apply]);
}
