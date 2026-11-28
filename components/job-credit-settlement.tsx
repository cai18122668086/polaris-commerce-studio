"use client";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api/client";
import { unwrapApiResponse } from "@/lib/api/request";
import type { JobDetail } from "@/lib/api/types";

// The settlement read shares the browser's per-host connection pool with result
// thumbnails. On a slow link it could sit queued indefinitely, leaving
// 「正在同步本次积分…」 on screen. Bound it and fall back to the job's own figures.
const SETTLEMENT_TIMEOUT_MS = 8_000;

export function JobCreditSettlement({ workspaceId, jobId, job }: { workspaceId: string; jobId: string; job?: Pick<JobDetail, "cost"> }) {
  const query = useQuery({
    queryKey: ["job-credit-settlement", workspaceId, jobId],
    queryFn: async ({ signal }) => {
      const timeout = AbortSignal.timeout(SETTLEMENT_TIMEOUT_MS);
      const combined = AbortSignal.any([signal, timeout]);
      try {
        return unwrapApiResponse(await apiClient.GET(
          "/api/v1/workspaces/{workspace_id}/credits/jobs/{job_id}", { params: { path: { workspace_id: workspaceId, job_id: jobId } }, signal: combined },
        ));
      } catch (error) {
        if (timeout.aborted && !signal.aborted) throw new Error("积分记录读取超时");
        throw error;
      }
    },
    retry: false,
    refetchInterval: current => !current.state.error && current.state.data?.settled_credits == null ? 5000 : false,
  });
  const estimated = job?.cost.estimated_credits;
  const actual = job?.cost.actual_credits;
  const fallback = typeof actual === "number" && actual > 0
    ? `已结算 ${actual} 积分`
    : typeof estimated === "number" ? `预计 ${estimated} 积分，按成功交付图片结算` : null;
  return <section className="job-detail-section" aria-label="本次任务积分"><h3>本次任务积分</h3>
    {query.data
      ? <><p>预留 {query.data.reserved_credits} 积分</p>{query.data.settled_credits != null ? <p>已结算 {query.data.settled_credits} 积分 · 已释放 {query.data.released_credits} 积分</p> : <p>等待结算，按成功交付图片收取积分，未使用部分会自动释放。</p>}</>
      : query.isError
        ? <p>{fallback ? `${fallback}。明细暂未读取到，可在积分明细中核对。` : "暂无可读取的积分预留记录，可在明细中核对。"}{" "}<button type="button" className="text-button" onClick={() => void query.refetch()}>重新读取</button></p>
        : <p>{fallback ?? "正在读取本次积分…"}</p>}
    <Link href="/account#credits">查看积分明细</Link>
  </section>;
}
