"use client";

import { JobProgressFeedback } from "@/components/job-progress-feedback";
import type { Job, JobDetail } from "@/lib/api/types";

export function JobProgress({ job, error, lastSyncedAt, refreshing, onRefresh, suppressFailureDetails }: {
  job: Job | JobDetail;
  error?: unknown;
  lastSyncedAt?: number;
  refreshing?: boolean;
  onRefresh?: () => void;
  suppressFailureDetails?: boolean;
}) {
  return <JobProgressFeedback job={job} error={error} lastSyncedAt={lastSyncedAt} refreshing={refreshing} onRefresh={onRefresh} suppressFailureDetails={suppressFailureDetails} />;
}
