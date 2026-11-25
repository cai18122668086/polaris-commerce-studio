"use client";

import Link from "next/link";
import { LoaderCircle, RefreshCcw } from "lucide-react";
import { useQuery } from "@tanstack/react-query";

import { useCloneJob } from "@/features/jobs/api/jobs";
import { apiClient } from "@/lib/api/client";
import { errorMessage, unwrapApiResponse } from "@/lib/api/request";
import type { JobCreate, JobDetail } from "@/lib/api/types";
import { allowsJobAction } from "@/lib/jobs/actions";
import { safeJobFailureSummary } from "@/lib/jobs/presentation";

/** The clone endpoint re-creates the job from its stored input and settings; quote the same payload. */
export function cloneQuotePayload(job: Pick<JobDetail, "type" | "display_name" | "configuration">): JobCreate | null {
  const configuration = job.configuration as Record<string, unknown> | undefined;
  const input = configuration?.input;
  const settings = configuration?.settings;
  if (!input || typeof input !== "object" || !settings || typeof settings !== "object") return null;
  return { type: job.type, intent: "submit", display_name: job.display_name ?? undefined, input, configuration: settings } as unknown as JobCreate;
}

/** Shown only when the backend offers clone instead of retry (e.g. a failed whole-set audit). */
export function canRegenerateSet(job: Pick<JobDetail, "status" | "allowed_actions">): boolean {
  return ["partial", "failed"].includes(job.status)
    && allowsJobAction(job.allowed_actions, "clone")
    && !allowsJobAction(job.allowed_actions, "retry");
}

export function JobRegenerateSet({ workspaceId, job, onCreated, compact = false }: {
  workspaceId: string;
  job: JobDetail;
  onCreated: (jobId: string) => void;
  compact?: boolean;
}) {
  const clone = useCloneJob(workspaceId);
  const payload = cloneQuotePayload(job);
  const quote = useQuery({
    queryKey: ["job-clone-quote", workspaceId, job.id],
    enabled: Boolean(payload),
    retry: false,
    staleTime: 60_000,
    queryFn: async ({ signal }) => unwrapApiResponse(await apiClient.POST(
      "/api/v1/workspaces/{workspace_id}/credits/quote",
      { params: { path: { workspace_id: workspaceId } }, body: payload!, signal },
    )),
  });
  const credits = quote.data?.estimated_credits;
  const insufficient = quote.data ? !quote.data.sufficient : false;
  const delivered = job.output_asset_count;
  const total = job.expected_item_count;
  const run = () => {
    if (clone.isPending) return;
    const cost = typeof credits === "number" ? `，预计 ${credits} 积分` : "";
    if (!window.confirm(`将按原方案新建任务，重新生成全部 ${total} 张图片${cost}。原任务和已生成的图片会保留。确定继续？`)) return;
    clone.mutate({ jobId: job.id, allowedActions: job.allowed_actions }, { onSuccess: (next) => onCreated(next.id) });
  };

  return <section className={`job-recovery${compact ? " job-recovery--compact" : ""}`} aria-labelledby={`job-recovery-${job.id}`}>
    <div className="job-recovery__copy">
      <strong id={`job-recovery-${job.id}`}>这组图没有完整交付</strong>
      <p>{safeJobFailureSummary(job.error_code)}</p>
      <p>这个任务不能只补失败的一张。重新生成整组会按原方案新建一个任务，从头生成全部 {total} 张；原任务{delivered > 0 ? "和已生成的图片" : ""}不受影响。</p>
    </div>
    <div className="job-recovery__action">
      <button type="button" className="primary-button" onClick={run} disabled={clone.isPending || insufficient}>
        {clone.isPending ? <LoaderCircle size={15} className="spin" /> : <RefreshCcw size={15} />}重新生成整组
      </button>
      <span className="job-recovery__price">
        {quote.isPending && payload ? "正在计算所需积分…" : typeof credits === "number" ? `预计 ${credits} 积分 · 按成功出图结算` : "按原方案计费，提交前会预留积分"}
        {insufficient && <> · <Link href="/account#membership">积分不足，充值积分</Link></>}
      </span>
    </div>
    {clone.error ? <p className="job-recovery__error" role="alert">{errorMessage(clone.error)}</p> : null}
  </section>;
}
