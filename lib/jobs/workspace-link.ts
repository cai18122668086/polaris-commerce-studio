import { FEATURE_REGISTRY } from "@/lib/feature-registry";
import type { JobType } from "@/lib/api/types";

export function jobWorkspaceHref(job: { id: string; type: JobType }): string {
  const feature = FEATURE_REGISTRY.find((candidate) => candidate.jobType === job.type);
  if (!feature) return `/jobs?jobId=${encodeURIComponent(job.id)}`;
  return `${feature.route}?jobId=${encodeURIComponent(job.id)}`;
}
