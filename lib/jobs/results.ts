import type { JobDetail } from "@/lib/api/types";

export type JobResultAsset = JobDetail["assets"][number];

export function selectJobResultAssets(
  job: Pick<JobDetail, "assets"> | undefined,
): JobResultAsset[] {
  if (!job) return [];
  return job.assets
    .filter(
      (asset) =>
        asset.direction === "output" &&
        asset.is_deliverable &&
        Boolean(asset.asset_id),
    )
    .sort((left, right) => left.ordinal - right.ordinal);
}

export function canRetryJob(
  job: Pick<JobDetail, "allowed_actions"> | undefined,
): boolean {
  return Boolean(job?.allowed_actions.includes("retry"));
}
