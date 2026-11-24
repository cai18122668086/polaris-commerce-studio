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

/** 已提交过的编排仍在进行，或已保存模型响应可免费重新校验时，返回对应的准备记录。 */
export function resumablePreparation(jobs: ResumeJob[], baseTaskId: string, templateId: string): string | undefined {
  if (!baseTaskId || !templateId) return undefined;
  const latest = newestFirst(jobs).find(job => job.mode === "prepare" && job.base_task_id === baseTaskId && jobTemplate(job) === templateId);
  if (!latest) return undefined;
  const generate = newestFirst(jobs).find(job => job.mode === "generate" && job.prepared_task_id === latest.id);
  if (!generate) return undefined;
  const running = ["queued", "running"].includes(generate.status);
  const recoverable = ["failed", "cancelled"].includes(generate.status) && generate.call_state === "response_saved" && generate.error_code !== "EDITING_PLAN_EMPTY_RESPONSE";
  return running || recoverable ? latest.id : undefined;
}
