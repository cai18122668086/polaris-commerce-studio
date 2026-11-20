export type ActiveWorkStatus = "queued" | "running" | "prepared" | "awaiting_review" | "failed";

export type ActiveWork = {
  kind: "planning" | "editing";
  task_id: string;
  project_id: string;
  project_title: string;
  status: ActiveWorkStatus;
  created_at: string;
  preview: { url: string } | null;
};

export type ActiveWorkView = {
  label: string;
  action: string;
  href: string;
  needsUser: boolean;
  polling: boolean;
};

const editingCopy: Record<ActiveWorkStatus, Pick<ActiveWorkView, "label" | "action">> = {
  queued: { label: "正在剪辑", action: "查看进度" },
  running: { label: "正在剪辑", action: "查看进度" },
  prepared: { label: "正在剪辑", action: "查看进度" },
  awaiting_review: { label: "待确认预览", action: "去确认" },
  failed: { label: "剪辑未完成", action: "查看原任务" },
};

const planningCopy: Record<ActiveWorkStatus, Pick<ActiveWorkView, "label" | "action">> = {
  queued: { label: "正在编排", action: "查看进度" },
  running: { label: "正在编排", action: "查看进度" },
  prepared: { label: "待继续", action: "继续剪辑" },
  awaiting_review: { label: "待继续", action: "继续剪辑" },
  failed: { label: "编排未完成", action: "查看原任务" },
};

/** How an unfinished planning or editing task is shown in 我的作品, and where it leads. */
export function activeWorkView(work: ActiveWork): ActiveWorkView {
  const copy = (work.kind === "editing" ? editingCopy : planningCopy)[work.status]
    ?? { label: "处理中", action: "查看原任务" };
  const project = `/video-studio/editing?project=${encodeURIComponent(work.project_id)}`;
  return {
    ...copy,
    href: work.kind === "editing" ? `${project}#editing-task-${encodeURIComponent(work.task_id)}` : project,
    needsUser: work.status === "awaiting_review" || work.status === "prepared" || work.status === "failed",
    polling: work.status === "queued" || work.status === "running",
  };
}

/** Same title match the finished-works search uses, applied to the unfinished list. */
export function matchesKeyword(work: Pick<ActiveWork, "project_title">, keyword: string) {
  const term = keyword.trim().toLocaleLowerCase();
  return !term || work.project_title.toLocaleLowerCase().includes(term);
}
