import type { JobDetail } from "@/lib/api/types";

export type JobResultAsset = JobDetail["assets"][number];

/**
 * P-7 switch.  Mirrors `POLARIS_DOMESTIC_PARTIAL_ARCHIVE_ENABLED` on the API:
 * when on, an incomplete domestic main image set is downloadable as a
 * best-effort archive plus a `manifest.json`.  Off by default.
 */
function domesticPartialArchiveEnabled(): boolean {
  return (
    typeof process !== "undefined" &&
    process.env.NEXT_PUBLIC_POLARIS_DOMESTIC_PARTIAL_ARCHIVE === "true"
  );
}

export function canDownloadJobArchive(job: JobDetail | undefined): boolean {
  if (!job || !["detail_pack", "amazon_visual_suite", "domestic_main_image"].includes(job.type)) return false;
  if (
    domesticPartialArchiveEnabled() &&
    job.type === "domestic_main_image" &&
    job.status === "partial"
  ) {
    return selectJobResultAssets(job).length >= 1;
  }
  if (job.expected_item_count < 1 || selectJobResultAssets(job).length !== job.expected_item_count) return false;
  if (job.status === "completed") return true;
  if (job.type !== "amazon_visual_suite" || job.status !== "partial" || job.expected_item_count !== 21 || job.items.length !== 21 || job.succeeded_item_count + job.failed_item_count !== 21) return false;
  const preservedFailure = (item: JobDetail["items"][number]) => {
    const details = item.error_details;
    return item.status === "failed" && details?.failure_kind === "review_infrastructure_failure" && details.image_quality_failed === false && details.generated_asset_preserved === true;
  };
  const failures = job.items.filter(preservedFailure);
  return failures.length > 0 && failures.length === job.failed_item_count && job.items.every(item => ["succeeded", "reused"].includes(item.status) || preservedFailure(item));
}

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
