/**
 * C10 第 3 点「完成提醒」轻量版：页面在后台时，一批口播或剪辑全部跑完，把浏览器标签标题改成提醒；回到页面后恢复。
 * 这里只放纯逻辑（便于单测），挂载在 use-done-notice.ts。
 */
export type NoticeItem = { stage: string; status: string; deleted_at?: string | null };
export type NoticeBatch = { id: string; items: NoticeItem[] };
export type BusyPhase = "talking" | "editing" | null;

/** 这一批现在在跑什么：有口播在排队/生成 → talking；否则有剪辑在排队/剪 → editing；都没有 → null。 */
export function busyPhase(batch: NoticeBatch): BusyPhase {
  const items = batch.items.filter(item => !item.deleted_at);
  const running = (stage: string) => items.some(item => item.stage === stage && (item.status === "queued" || item.status === "running" || (stage === "talking" && item.status === "pending")));
  return running("talking") ? "talking" : running("editing") ? "editing" : null;
}

/** 与上一次相比，哪些批次刚刚跑完（之前在跑、现在不跑了）。第一次看到的批次不算。 */
export function justFinished(previous: Record<string, BusyPhase>, batches: NoticeBatch[]): { phases: Record<string, BusyPhase>; finished: Exclude<BusyPhase, null>[] } {
  const phases: Record<string, BusyPhase> = {};
  const finished: Exclude<BusyPhase, null>[] = [];
  for (const batch of batches) {
    const now = busyPhase(batch);
    phases[batch.id] = now;
    const before = previous[batch.id];
    if (before && before !== now) finished.push(before);
  }
  return { phases, finished };
}

/** 标签标题：「（口播已完成）原标题」「（剪辑已完成）原标题」，两种都有时写「（一批视频已完成）」。 */
export function noticeTitle(finished: Exclude<BusyPhase, null>[], original: string): string {
  const kinds = new Set(finished);
  const label = kinds.size > 1 ? "一批视频已完成" : kinds.has("talking") ? "口播已完成" : "剪辑已完成";
  return `（${label}）${original.replace(/^（[^）]*已完成）/, "")}`;
}
