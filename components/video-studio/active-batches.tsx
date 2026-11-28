"use client";

import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { stepHref } from "@/features/video-studio/flow-params";
import { activeBatchRows, type BatchLike } from "@/features/video-studio/active-batches";
import { useRecentBatches } from "@/features/video-studio/use-done-notice";
import styles from "./video-studio.module.css";

/** B12：首页四步卡上方「进行中的批次」，每批一行，「继续」落在该批现在所处的步骤（带 ?batch=）。没有进行中的批次时不出现。 */
export function ActiveBatches({ workspaceId }: { workspaceId: string }) {
  const batches = useRecentBatches(workspaceId);
  const rows = activeBatchRows((batches.data ?? []) as BatchLike[]);
  if (!rows.length) return null;
  return <section className={styles.activeBatches} aria-label="进行中的批次">
    <h2>进行中的批次</h2>
    <ul>{rows.map(row => <li key={row.id}>
      <span className={styles.batchDate}>{row.date}</span>
      <span className={styles.batchCount}>{row.total} 条</span>
      <span className={styles.batchWhere}><b>{row.where}</b>{row.detail && <small>{row.detail}</small>}</span>
      <Link className={styles.batchGo} href={stepHref(row.step, { batch: row.id })} aria-label={`继续这一批（${row.date}，${row.where}）`}>继续<ArrowRight size={14} /></Link>
    </li>)}</ul>
  </section>;
}
