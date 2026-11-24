import { activeWorkView, type ActiveWork } from "./active-works";

type JobLike = { id: string; kind: string; status: string; created_at: string; snapshot?: { draft?: { name?: string } } | null };

export type TaskItem = { id: string; title: string; label: string; href: string; needsUser: boolean; running: boolean; createdAt: string | null };

const TERMINAL = new Set(["completed", "failed", "cancelled", "rejected"]);

/** Generation jobs that still matter to the user: in flight, waiting to resume, or waiting for approval. */
function jobItem(job: JobLike): TaskItem | undefined {
  if (TERMINAL.has(job.status)) return undefined;
  const avatar = job.kind === "h3_template";
  const review = job.status === "awaiting_review";
  const resume = job.status === "awaiting_resume" || job.status === "unknown";
  return {
    id: `generation:${job.id}`,
    title: job.snapshot?.draft?.name?.trim() || (avatar ? "定制形象" : "数字人口播"),
    label: review ? (avatar ? "形象待确认" : "待确认") : resume ? "结果待查询" : avatar ? "形象生成中" : "口播生成中",
    href: avatar ? "/video-studio/avatars" : "/video-studio/works",
    needsUser: review || resume,
    running: !review && !resume,
    createdAt: job.created_at,
  };
}

/** Missing or unparsable times sort last instead of throwing during render. */
function timeOf(value: string | null | undefined): number {
  const time = typeof value === "string" ? Date.parse(value) : Number.NaN;
  return Number.isFinite(time) ? time : 0;
}

/** One list for the header task center: unfinished edits and generations, items needing the user first. */
export function taskCenterItems(active: ActiveWork[], jobs: JobLike[]): TaskItem[] {
  const edits = active.map(work => {
    const view = activeWorkView(work);
    return { id: `${work.kind}:${work.task_id}`, title: work.project_title, label: view.label, href: view.href, needsUser: view.needsUser, running: view.polling, createdAt: work.created_at };
  });
  const generations = jobs.map(jobItem).filter((item): item is TaskItem => Boolean(item));
  return [...edits, ...generations].sort((a, b) => Number(b.needsUser) - Number(a.needsUser) || timeOf(b.createdAt) - timeOf(a.createdAt));
}

/** Items that were running on the last look and are no longer running: finished, failed or waiting for the user. */
export function settledSince(previous: TaskItem[], next: TaskItem[]): TaskItem[] {
  const now = new Map(next.map(item => [item.id, item]));
  return previous.filter(item => item.running && !now.get(item.id)?.running);
}
