/**
 * B12「继续上一批」：首页四步卡上方的「进行中的批次」。
 * 输入是 GET /work-batches 的批次（带 items，C2），输出每批一行：日期 · N 条 · 现在在哪一步，以及「继续」去哪一步。
 * 全部做完（每条都 done）的批次不显示；被删除（软删除，B1）的条目不计。
 */
export type BatchItemLike = { stage: string; status: string; deleted_at?: string | null };
export type BatchLike = { id: string; created_at: string; items: BatchItemLike[] };
export type ContinueStep = "voice" | "editing" | "finish";
export type ActiveBatchRow = { id: string; date: string; total: number; where: string; detail: string; step: ContinueStep };

const BUSY = new Set(["pending", "queued", "running"]);

/** 「11月28日 14:05」，按北京时间。 */
export function batchDate(iso: string, now: Date = new Date()): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const parts = (value: Date) => Object.fromEntries(new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Shanghai", year: "numeric", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false })
    .formatToParts(value).map(part => [part.type, part.value]));
  const d = parts(date), n = parts(now);
  const day = d.year === n.year && d.month === n.month && d.day === n.day ? "今天" : `${d.month}月${d.day}日`;
  return `${day} ${d.hour}:${d.minute}`;
}

export function activeBatchRow(batch: BatchLike, now?: Date): ActiveBatchRow | null {
  const items = batch.items.filter(item => !item.deleted_at && item.status !== "canceled");
  const total = items.length;
  if (!total || items.every(item => item.stage === "done")) return null;
  const count = (test: (item: BatchItemLike) => boolean) => items.filter(test).length;
  const talkingBusy = count(item => item.stage === "talking" && BUSY.has(item.status));
  const talkingDone = count(item => item.stage !== "talking" || item.status === "succeeded");
  const editingBusy = count(item => item.stage === "editing" && (item.status === "queued" || item.status === "running"));
  const toEdit = count(item => (item.stage === "talking" && item.status === "succeeded") || (item.stage === "editing" && item.status === "pending"));
  const toFinish = count(item => item.stage === "finishing");
  const done = count(item => item.stage === "done");
  const failed = items.filter(item => item.status === "failed" && item.stage !== "done");
  const failedNote = failed.length ? `${failed.length} 条未完成` : "";
  const join = (...parts: string[]) => parts.filter(Boolean).join(" · ");

  if (talkingBusy) return { id: batch.id, date: batchDate(batch.created_at, now), total, where: `口播 ${talkingDone}/${total}`, detail: join("口播生成中", failedNote), step: "voice" };
  if (editingBusy) return { id: batch.id, date: batchDate(batch.created_at, now), total, where: `剪辑 ${count(item => item.stage === "finishing" || item.stage === "done")}/${total}`, detail: join("剪辑中", toFinish ? `${toFinish} 条可以先去成片` : "", failedNote), step: toFinish ? "finish" : "editing" };
  if (toEdit) return { id: batch.id, date: batchDate(batch.created_at, now), total, where: `待剪辑 ${toEdit} 条`, detail: join(toFinish ? `待成片 ${toFinish} 条` : "", failedNote), step: "editing" };
  if (toFinish) return { id: batch.id, date: batchDate(batch.created_at, now), total, where: `待成片 ${toFinish} 条`, detail: join(done ? `已完成 ${done} 条` : "", failedNote), step: "finish" };
  // 只剩失败的：回到失败的那一步。
  const first = failed[0];
  if (!first) return null;
  return { id: batch.id, date: batchDate(batch.created_at, now), total, where: failedNote, detail: first.stage === "talking" ? "口播没有生成成功，可以重试" : "剪辑没有成功，可以重试", step: first.stage === "talking" ? "voice" : first.stage === "editing" ? "editing" : "finish" };
}

/** 最近的几批里还没做完的，新的在前，最多 limit 行。 */
export function activeBatchRows(batches: BatchLike[], limit = 3, now?: Date): ActiveBatchRow[] {
  return batches.map(batch => activeBatchRow(batch, now)).filter((row): row is ActiveBatchRow => row !== null).slice(0, limit);
}
