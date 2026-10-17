import type { JobDetail } from "@/lib/api/types";

export type JobResultAsset = JobDetail["assets"][number];

const REFERENCE_ASSET_ROLES = new Set([
  "brand_reference",
  "competitor_reference",
  "package_reference",
  "pose_reference",
  "scene_reference",
  "style_reference",
]);

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

export function selectJobInputAssets(
  job: Pick<JobDetail, "assets"> | undefined,
): JobResultAsset[] {
  if (!job) return [];
  return job.assets
    .filter(
      (asset) =>
        asset.direction === "input" && !REFERENCE_ASSET_ROLES.has(asset.role),
    )
    .sort((left, right) => left.ordinal - right.ordinal);
}

export function selectJobReferenceAssets(
  job: Pick<JobDetail, "assets"> | undefined,
): JobResultAsset[] {
  if (!job) return [];
  return job.assets
    .filter(
      (asset) =>
        asset.direction === "input" && REFERENCE_ASSET_ROLES.has(asset.role),
    )
    .sort((left, right) => left.ordinal - right.ordinal);
}

export function selectJobIntermediateAssets(
  job: Pick<JobDetail, "assets"> | undefined,
): JobResultAsset[] {
  if (!job) return [];
  return job.assets
    .filter(
      (asset) =>
        asset.direction === "intermediate" ||
        (asset.direction === "output" && !asset.is_deliverable),
    )
    .sort((left, right) => left.ordinal - right.ordinal);
}

export function canRetryJob(
  job: Pick<JobDetail, "allowed_actions"> | undefined,
): boolean {
  return Boolean(job?.allowed_actions.includes("retry"));
}
