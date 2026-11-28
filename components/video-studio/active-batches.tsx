"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight } from "lucide-react";
import { apiClient } from "@/lib/api/client";
import { unwrapApiResponse } from "@/lib/api/request";
import { stepHref } from "@/features/video-studio/flow-params";
import { activeBatchRows, type BatchLike } from "@/features/video-studio/active-batches";
import styles from "./video-studio.module.css";

const route = "/api/v1/video-studio/workspaces/{workspace_id}/work-batches" as const;

/** B12：首页四步卡上方「进行中的批次」，每批一行，「继续」落在该批现在所处的步骤（带 ?batch=）。没有进行中的批次时不出现。 */
export function ActiveBatches({ workspaceId }: { workspaceId: string }) {
  const batches = useQuery({
    queryKey: ["video-studio", "work-batches", workspaceId, "active"],
    staleTime: 15000,
    queryFn: async ({ signal }) => unwrapApiResponse(await apiClient.GET(route, {
      params: { path: { workspace_id: workspaceId }, query: { limit: 5 } },
      signal: AbortSignal.any([signal, AbortSignal.timeout(12000)]),
    })),
    refetchInterval: 30000,
  });
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
