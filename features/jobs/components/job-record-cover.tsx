"use client";

import { LoaderCircle } from "lucide-react";
import { useAssetAccessUrl } from "@/features/assets/api/assets";
import { useJob } from "@/features/jobs/api/jobs";
import type { Job } from "@/lib/api/types";
import { jobTypeLabel } from "@/lib/jobs/presentation";
import { selectJobResultAssets } from "@/lib/jobs/results";

const resultStatuses = new Set(["completed", "partial", "failed"]);

export function JobRecordCover({ workspaceId, job }: { workspaceId: string; job: Job }) {
  const canHaveResults = resultStatuses.has(job.status);
  const detail = useJob(workspaceId, canHaveResults ? job.id : undefined);
  const resultAsset = selectJobResultAssets(detail.data)?.[0];
  const access = useAssetAccessUrl(workspaceId, resultAsset?.asset_id);
  const title = job.display_name?.trim() || jobTypeLabel(job.type);

  return (
    <div className="record-cover api-job-cover" aria-label={`${title}生成结果预览`}>
      {access.data?.url ? (
        <img src={access.data.url} alt={`${title}生成结果`} />
      ) : detail.isFetching || access.isFetching ? (
        <LoaderCircle className="spin" size={20} aria-label="正在加载结果预览" />
      ) : (
        <span className="record-cover__empty">暂无结果</span>
      )}
    </div>
  );
}
