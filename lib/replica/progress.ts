export type ReplicaProgressDocument = {
  id: string;
  status: string;
  updated_at?: string;
  payload: {
    analysis_attempt_id?: string;
    progress?: number;
    job_ids?: string[];
    submission_complete?: boolean;
    execution_progress?: { percentage: number };
    analysis_progress?: { stage: string; total: number; planned: number; reviewed: number; accepted: number; pending_corrections: number };
  };
};

const terminal = new Set(["completed", "partial", "failed", "cancelled"]);

export function replicaAnalysisMessage(document: ReplicaProgressDocument): string | undefined {
  const progress = document.payload.analysis_progress;
  if (!progress) return undefined;
  if (progress.total > 0) {
    if (progress.accepted === progress.total) return `${progress.total} 屏方案已确认，正在准备生成`;
    if (progress.stage === "review_plan") return `已确认 ${progress.accepted} / ${progress.total} 屏方案，正在处理剩余部分`;
    if (progress.stage === "plan") return `已规划 ${progress.planned} / ${progress.total} 屏${progress.pending_corrections ? "，正在调整剩余方案" : "，保留整套画面的顺序与风格"}`;
  }
  if (progress.stage === "facts" || progress.stage === "product") return "正在统一商品信息，供整套画面使用";
  return undefined;
}

export function replicaWorkflowStep(document: ReplicaProgressDocument | undefined, jobStatuses: Readonly<Record<string, string>>): number {
  if (!document) return 0;
  const jobs = document.payload.job_ids ?? [];
  if (jobs.length) return document.payload.submission_complete !== false && jobs.every(id => jobStatuses[id] === "completed") ? 5 : 4;
  return document.status === "awaiting_confirmation" ? 3 : document.status === "analysing" ? 1 : 0;
}

export function replicaOverallProgress(document: ReplicaProgressDocument): number {
  if (document.status === "completed") return 100;
  if (document.payload.execution_progress) return Math.min(99, Math.max(25, document.payload.execution_progress.percentage));
  if (document.payload.job_ids?.length || document.status === "awaiting_confirmation") return 25;
  return Math.min(24, Math.max(0, Math.round((document.payload.progress ?? 0) * .24)));
}

/** Reject older poll replies while allowing explicit new attempts to start at zero. */
export function mergeReplicaProgress<T extends ReplicaProgressDocument>(current: T | undefined, incoming: T): T {
  if (!current || current.id !== incoming.id) return incoming;
  if (current.updated_at && incoming.updated_at && Date.parse(incoming.updated_at) < Date.parse(current.updated_at)) return current;
  if (current.payload.analysis_attempt_id !== incoming.payload.analysis_attempt_id) return incoming;
  if (JSON.stringify(current.payload.job_ids) !== JSON.stringify(incoming.payload.job_ids)) return incoming;
  if (terminal.has(current.status) && !terminal.has(incoming.status)) return current;
  const execution = incoming.payload.execution_progress;
  return {
    ...incoming,
    payload: {
      ...incoming.payload,
      progress: Math.max(current.payload.progress ?? 0, incoming.payload.progress ?? 0),
      ...(execution && { execution_progress: {
        ...execution,
        percentage: Math.max(current.payload.execution_progress?.percentage ?? 0, execution.percentage),
      } }),
    },
  };
}
