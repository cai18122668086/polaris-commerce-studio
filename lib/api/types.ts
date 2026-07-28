import type { components } from "./generated/openapi";

export type Workspace = components["schemas"]["WorkspaceResponse"];
export type Asset = components["schemas"]["AssetResponse"];
export type AssetList = components["schemas"]["AssetListResponse"];
export type AssetOriginKind = components["schemas"]["AssetOriginKind"];
export type Job = components["schemas"]["JobListItemResponse"];
export type JobDetail = components["schemas"]["JobDetailResponse"];
export type JobList = components["schemas"]["JobListResponse"];
export type JobStatus = components["schemas"]["JobStatus"];
export type JobType = components["schemas"]["JobType"];
export type LocalEditJobCreate = components["schemas"]["LocalEditJobCreate"];
export type DetailPackJobCreate = components["schemas"]["DetailPackJobCreate"];
export type RuntimeStatus = components["schemas"]["RuntimeStatusResponse"];

export const activeJobStatuses: JobStatus[] = [
  "queued",
  "planning",
  "awaiting_confirmation",
  "processing",
  "cancelling",
];

export const terminalJobStatuses: JobStatus[] = [
  "partial",
  "completed",
  "failed",
  "cancelled",
];

export function isActiveJob(status: JobStatus): boolean {
  return activeJobStatuses.includes(status);
}
