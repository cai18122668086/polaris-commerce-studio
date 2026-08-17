export type WorkspaceLinkFeature = {
  jobType: string;
  route: string;
  taskPreset?: string;
};

export type WorkspaceLinkJob = {
  id: string;
  type: string;
  task_preset?: string | null;
  configuration?: Record<string, unknown>;
};

function productImageTaskPreset(job: WorkspaceLinkJob): string | undefined {
  if (job.task_preset) return job.task_preset;
  const settings = job.configuration?.settings;
  const configuredPreset = settings && typeof settings === "object" && !Array.isArray(settings)
    ? (settings as Record<string, unknown>).task_type
    : undefined;
  return typeof configuredPreset === "string" ? configuredPreset : undefined;
}

export function resolveJobWorkspaceHref(
  job: WorkspaceLinkJob,
  features: readonly WorkspaceLinkFeature[],
): string {
  const fallback = `/jobs?jobId=${encodeURIComponent(job.id)}`;
  const feature = job.type === "product_image"
    ? features.find(
        (candidate) =>
          candidate.jobType === job.type &&
          candidate.taskPreset === productImageTaskPreset(job),
      )
    : features.find((candidate) => candidate.jobType === job.type);

  return feature ? `${feature.route}?jobId=${encodeURIComponent(job.id)}` : fallback;
}
