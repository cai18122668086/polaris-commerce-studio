/**
 * 重新打开智能剪辑时，从服务端已有记录恢复上次进行到的位置。
 * 只恢复「看到什么」：口播来源、模板和上次的编排准备；不会替用户发起新的计费请求。
 */
type ResumeTask = {
  id: string;
  status: string;
  created_at: string;
  options: { mode: string };
  artifacts: { role: string }[];
};
type ResumeJob = {
  id: string;
  mode: "prepare" | "generate";
  status: string;
  call_state: string;
  error_code: string | null;
  base_task_id: string;
  prepared_task_id: string | null;
  created_at: string;
  overlay_template?: { id: string } | null;
  template_id?: string | null;
  /** 同一原片、模板、素材和设置得到同一个值；用来认出「已经剪过的同一份请求」。 */
  request_sha256?: string | null;
};

const newestFirst = <T extends { created_at: string }>(rows: T[]) => [...rows].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at));
const jobTemplate = (job: ResumeJob) => job.overlay_template?.id || job.template_id || undefined;
const usableTranscript = (task: ResumeTask) => task.options.mode === "transcript"
  && (["queued", "running"].includes(task.status) || (task.status === "completed" && task.artifacts.some(a => a.role === "transcript")));

/** 上次的口播识别任务（以及编排用的模板）。识别中的任务也会恢复，让页面继续显示进度。 */
export function resumableEditing(tasks: ResumeTask[], jobs: ResumeJob[]): { taskId: string; templateId?: string } | undefined {
  const transcripts = newestFirst(tasks.filter(usableTranscript));
  const latest = transcripts[0];
  const job = newestFirst(jobs).find(row => transcripts.some(task => task.id === row.base_task_id));
  // 之后又识别了新口播，就以新口播为准（模板仍沿用上次编排的）。
  if (job && (!latest || latest.id === job.base_task_id || Date.parse(latest.created_at) <= Date.parse(job.created_at))) {
    return { taskId: job.base_task_id, templateId: jobTemplate(job) };
  }
  return latest ? { taskId: latest.id, templateId: job ? jobTemplate(job) : undefined } : undefined;
}

const liveGenerate = (job: ResumeJob) => job.mode === "generate" && ["queued", "running", "completed"].includes(job.status);
const recoverableGenerate = (job: ResumeJob) => job.mode === "generate"
  && ["failed", "cancelled"].includes(job.status) && job.call_state === "response_saved" && job.error_code !== "EDITING_PLAN_EMPTY_RESPONSE";

/**
 * 重新打开页面时，找回这条口播 + 这个模板已经提交过的编排（进行中、已完成或可免费恢复）。
 * 已完成的也要找回：否则主按钮会回到「开始智能剪辑」，再点一次就是重新编排、重复扣费，
 * 而原来那条预览一直停在「待确认」，用户拿不到高清。
 */
export function resumablePreparation(jobs: ResumeJob[], baseTaskId: string, templateId: string): string | undefined {
  if (!baseTaskId || !templateId) return undefined;
  const prepares = new Set(jobs.filter(job => job.mode === "prepare" && job.base_task_id === baseTaskId && jobTemplate(job) === templateId).map(job => job.id));
  const submitted = newestFirst(jobs).filter(job => job.prepared_task_id && prepares.has(job.prepared_task_id));
  const chosen = submitted.find(liveGenerate) ?? submitted.find(recoverableGenerate);
  return chosen?.prepared_task_id ?? undefined;
}

/**
 * 某次准备对应的编排提交。先认自己的；没有时认同一份请求（同一请求哈希）已在跑或已完成的那次。
 * 换了设备、或服务端拒绝重复付费时，页面直接接上已有结果，不再发起新的付费编排。
 */
export function planSubmission<T extends ResumeJob>(jobs: T[], prepared: Pick<ResumeJob, "id" | "request_sha256"> | undefined): T | undefined {
  if (!prepared) return undefined;
  const own = jobs.find(job => job.prepared_task_id === prepared.id);
  if (own) return own;
  const sha = prepared.request_sha256;
  return sha ? newestFirst(jobs).find(job => liveGenerate(job) && job.request_sha256 === sha) : undefined;
}
